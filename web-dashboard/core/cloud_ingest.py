"""Bringing the Raspberry Pi's cloud readings into SQLite.

The Pi writes straight to Firebase under ``pi_monitor/readings/<device>``. That
is a useful uplink but it is not the dashboard: Flask reads SQLite, the
freshness engine reads SQLite, and the alert path reads SQLite. This module is
the bridge, so the Pi's measurements arrive in the one place everything else
already looks.

SQLite stays the source of truth. Firebase is the transport the device happens
to use, nothing more, and an ingested reading is an ordinary row indistinguish-
able from one the local sensor loop wrote.

Two things about the device payload force real work here rather than a copy:

* **Firebase drops keys whose value is null.** A failed DHT read arrives as a
  payload with no ``temp_c`` key at all, not as ``temp_c: null``. A missing key
  therefore means a faulted sensor, and is translated into one.
* **The device reports a stale gas value while the MQ-135 is disconnected.**
  Readings carry ``gas_raw: 5793`` unchanged for minutes with
  ``components.mq135 = "I2C_DISCONNECTED"``. That number is the last good
  sample, not a measurement, and storing it would put a steady, healthy-looking
  gas level on the dashboard from a sensor that is not plugged in. When the
  component says the sensor is unhealthy the value is discarded and the reading
  is marked faulty, which is what SRS rule 1 requires.

The device has no reed switch, so ``door_open`` is recorded as closed. That is
a statement about this device's wiring, not a measurement, and it is why the
door-open alert cannot be driven from an ingested reading.
"""

from __future__ import annotations

import base64
import binascii
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.sensors.base import GAS_RAW_RANGE, Reading, is_plausible

logger = logging.getLogger(__name__)

#: Where the device publishes, under the database root.
READINGS_PATH = "pi_monitor/readings"

#: The component name the device uses for the gas sensor, and the value it
#: reports when that sensor is healthy.
GAS_COMPONENT = "mq135"
COMPONENT_OK = "OK"

#: Rows pulled per cycle. Bounded so a long backlog makes steady progress
#: instead of loading the whole history into memory at once.
BATCH_SIZE = 200


class IngestError(RuntimeError):
    """Raised when the device's readings could not be read from the cloud."""


@dataclass(frozen=True, slots=True)
class IngestResult:
    """What one ingest cycle achieved."""

    stored: int = 0
    skipped: int = 0
    rejected: int = 0

    @property
    def made_progress(self) -> bool:
        """True when at least one new reading reached SQLite."""
        return self.stored > 0


def _component_healthy(payload: dict[str, Any], name: str) -> bool:
    """True when the device did not report this component as faulty.

    A payload with no ``components`` block at all is treated as healthy: the
    earliest firmware did not send one, and those readings carry their values
    honestly. Only an explicit non-OK status means a fault.
    """
    components = payload.get("components")
    if not isinstance(components, dict):
        return True
    status = components.get(name)
    if status is None:
        return True
    return str(status) == COMPONENT_OK


def _number(payload: dict[str, Any], key: str) -> float | None:
    """Return a numeric field, or None when it is absent or unusable."""
    value = payload.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.debug("ignoring non-numeric %s=%r", key, value)
        return None


def to_reading(payload: dict[str, Any]) -> Reading:
    """Translate one device payload into a Reading.

    Every sensor that did not produce a usable value becomes a fault, so the
    resulting row can never show a number for a sensor that was not working.
    """
    ts = payload.get("ts")
    if not isinstance(ts, str) or not ts:
        raise ValueError("payload has no timestamp")

    faults: set[str] = set()

    temp = _number(payload, "temp_c")
    if temp is None or not is_plausible("temp", temp):
        if temp is not None:
            logger.warning("discarding implausible temperature %r at %s", temp, ts)
        temp = None
        faults.add("temp")

    humidity = _number(payload, "humidity")
    if humidity is None or not is_plausible("humidity", humidity):
        if humidity is not None:
            logger.warning("discarding implausible humidity %r at %s", humidity, ts)
        humidity = None
        faults.add("humidity")

    # The component status is checked before the value, because a disconnected
    # MQ-135 still ships its last good number.
    gas: int | None = None
    if not _component_healthy(payload, GAS_COMPONENT):
        faults.add("gas")
    else:
        raw = _number(payload, "gas_raw")
        if raw is None:
            faults.add("gas")
        else:
            gas = int(raw)
            low, high = GAS_RAW_RANGE
            if not low <= gas <= high:
                logger.warning("discarding out-of-range gas value %r at %s", gas, ts)
                gas = None
                faults.add("gas")

    return Reading(
        ts=ts,
        temp_c=temp,
        humidity=humidity,
        gas_raw=gas,
        # The device has no reed switch. Recorded as closed, never measured.
        door_open=False,
        faults=frozenset(faults),
    )


def existing_timestamps(conn: sqlite3.Connection, zone_id: int, since: str) -> set[str]:
    """Return the timestamps this zone already holds at or after ``since``.

    Used to make ingest idempotent without touching the frozen schema: running
    the bridge twice over the same window stores nothing the second time.
    """
    rows = conn.execute(
        "SELECT ts FROM readings WHERE zone_id = ? AND ts >= ?",
        (zone_id, since),
    ).fetchall()
    return {row["ts"] for row in rows}


def ingest(
    conn: sqlite3.Connection,
    payloads: dict[str, dict[str, Any]],
    zone_id: int,
    *,
    device_id: str = "pi-01",
    queue_event: bool = False,
) -> IngestResult:
    """Store the device payloads that are not already in SQLite.

    ``payloads`` is the node as Firebase returns it: push key -> payload. The
    keys are only used for ordering; identity is the timestamp, because that is
    what the readings table records.
    """
    # Imported here rather than at module scope: monitor.py imports this module
    # in some deployments, and a top-level import would be circular.
    from monitor import store_reading

    if not payloads:
        return IngestResult()

    ordered = sorted(payloads.items())
    earliest = min(
        (p.get("ts") for _, p in ordered if isinstance(p.get("ts"), str)),
        default=None,
    )
    if earliest is None:
        return IngestResult(rejected=len(ordered))

    seen = existing_timestamps(conn, zone_id, earliest)

    stored = skipped = rejected = 0
    for key, payload in ordered:
        if not isinstance(payload, dict):
            rejected += 1
            continue
        try:
            reading = to_reading(payload)
        except ValueError as exc:
            logger.warning("skipping unusable payload %s: %s", key, exc)
            rejected += 1
            continue

        if reading.ts in seen:
            skipped += 1
            continue

        store_reading(conn, reading, zone_id, queue_event=queue_event, device_id=device_id)
        seen.add(reading.ts)
        stored += 1

    if stored:
        logger.info("ingested %d reading(s) from %s into zone %d", stored, device_id, zone_id)
    return IngestResult(stored=stored, skipped=skipped, rejected=rejected)


#: Where the device publishes its latest camera frame, under the database root.
LIVE_PATH = "pi_monitor/live"

#: The device sends the frame as a data URI. Only JPEG is accepted: the page
#: shows it as a photograph, and anything else is either a mistake or an attempt
#: to put something other than an image in front of a viewer.
_JPEG_PREFIX = "data:image/jpeg;base64,"

#: A frame larger than this is refused rather than written to disk. The frames
#: the device sends are around 26 kB; the ceiling is generous but finite, so a
#: runaway payload cannot fill the disk.
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024


def fetch_snapshot(reference: Any, device_id: str) -> bytes | None:
    """Return the device's latest camera frame as JPEG bytes, or None.

    Returns None rather than raising when the device has sent no frame: a
    missing photograph is an ordinary state, not a failure.
    """
    try:
        raw = reference.child(f"{LIVE_PATH}/{device_id}/image_base64").get()
    except Exception as exc:
        raise IngestError(f"could not read the camera frame: {exc}") from exc

    if not raw or not isinstance(raw, str):
        return None
    if not raw.startswith(_JPEG_PREFIX):
        logger.warning("ignoring a camera frame that is not a JPEG data URI")
        return None

    encoded = raw[len(_JPEG_PREFIX) :]
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        logger.warning("ignoring a camera frame whose base64 could not be decoded")
        return None

    if len(data) > MAX_SNAPSHOT_BYTES:
        logger.warning("ignoring a camera frame of %d bytes; over the limit", len(data))
        return None
    # A JPEG always starts FF D8. Checking it keeps anything that merely decodes
    # from being written out with a .jpg name.
    if not data.startswith(b"\xff\xd8"):
        logger.warning("ignoring a camera frame that does not begin with a JPEG marker")
        return None
    return data


def save_snapshot(data: bytes, path: Path) -> Path:
    """Write the frame, replacing any previous one.

    Written to a temporary name and moved into place, so a page loading the
    picture at the moment it is replaced never sees a half-written file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_bytes(data)
    temporary.replace(path)
    return path


def fetch_payloads(reference: Any, device_id: str, limit: int = BATCH_SIZE) -> dict[str, Any]:
    """Return the most recent device readings from the cloud.

    ``reference`` is a Firebase database reference for the root, kept as a
    parameter so the caller owns the connection and tests can pass a fake.
    """
    try:
        node = reference.child(f"{READINGS_PATH}/{device_id}")
        payloads = node.order_by_key().limit_to_last(limit).get()
    except Exception as exc:
        raise IngestError(f"could not read the device readings: {exc}") from exc
    return payloads or {}
