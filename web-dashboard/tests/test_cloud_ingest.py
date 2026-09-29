"""The bridge from the Pi's Firebase node into SQLite.

The payloads used here are taken from a real export of the device's node, so
the awkward shapes are the ones the hardware actually produces rather than ones
imagined for the test.
"""

from __future__ import annotations

import pytest

from core.cloud_ingest import IngestError, fetch_payloads, ingest, to_reading

DEVICE = "pi-01"


def payload(**overrides):
    """A healthy device payload, before the test spoils part of it."""
    base = {
        "components": {"dht22": "OK", "lcd": "OK", "mq135": "OK"},
        "device_id": DEVICE,
        "gas_raw": 9722,
        "humidity": 46.5,
        "system_status": "HEALTHY",
        "temp_c": 24.5,
        "ts": "2026-09-29T05:21:50Z",
    }
    base.update(overrides)
    return base


class TestTranslation:
    def test_a_healthy_payload_keeps_every_value(self):
        reading = to_reading(payload())
        assert reading.temp_c == 24.5
        assert reading.humidity == 46.5
        assert reading.gas_raw == 9722
        assert reading.healthy

    def test_a_disconnected_gas_sensor_discards_its_stale_value(self):
        """The device keeps sending its last good number while unplugged.

        This is the one that matters: storing 5793 would show a steady, healthy
        gas level for a sensor that is not connected.
        """
        spoiled = payload(
            components={"dht22": "OK", "lcd": "OK", "mq135": "I2C_DISCONNECTED"},
            gas_raw=5793,
            system_status="NEEDS_ATTENTION",
        )
        reading = to_reading(spoiled)

        assert reading.gas_raw is None
        assert reading.gas_ok is False
        # The working sensors are untouched by the gas fault.
        assert reading.temp_c == 24.5
        assert reading.humidity == 46.5

    def test_a_missing_key_is_a_fault_not_a_zero(self):
        """Firebase drops null values, so a failed read arrives as no key."""
        without_temp = payload()
        del without_temp["temp_c"]
        reading = to_reading(without_temp)

        assert reading.temp_c is None
        assert reading.temp_ok is False
        assert reading.humidity == 46.5

    def test_the_earliest_firmware_without_components_is_trusted(self):
        """The first readings carried no components block and honest values."""
        early = {
            "device_id": DEVICE,
            "humidity": 45.8,
            "temp_c": 24.7,
            "ts": "2026-09-29T04:54:51Z",
        }
        reading = to_reading(early)

        assert reading.temp_c == 24.7
        assert reading.humidity == 45.8
        # No gas key at all, so the gas sensor is faulted rather than invented.
        assert reading.gas_raw is None
        assert reading.gas_ok is False

    def test_a_payload_with_only_gas_still_translates(self):
        sparse = {"device_id": DEVICE, "gas_raw": 5056, "ts": "2026-09-29T05:05:19Z"}
        reading = to_reading(sparse)

        assert reading.gas_raw == 5056
        assert reading.temp_ok is False
        assert reading.humidity_ok is False

    def test_an_implausible_value_is_refused(self):
        reading = to_reading(payload(temp_c=999))
        assert reading.temp_c is None
        assert reading.temp_ok is False

    def test_a_payload_without_a_timestamp_is_rejected(self):
        broken = payload()
        del broken["ts"]
        with pytest.raises(ValueError, match="timestamp"):
            to_reading(broken)

    def test_the_door_is_recorded_closed_because_there_is_no_reed_switch(self):
        assert to_reading(payload()).door_open is False


class TestIngest:
    def test_readings_reach_the_database(self, conn, zone_id):
        payloads = {
            "-P2fbAQFS": payload(ts="2026-09-29T05:21:50Z"),
            "-P2fbEJEZ": payload(ts="2026-09-29T05:22:06Z", humidity=46.6),
        }
        result = ingest(conn, payloads, zone_id)

        assert result.stored == 2
        rows = conn.execute("SELECT ts, temp_c, gas_raw FROM readings ORDER BY ts").fetchall()
        assert [r["ts"] for r in rows] == ["2026-09-29T05:21:50Z", "2026-09-29T05:22:06Z"]

    def test_running_twice_stores_nothing_the_second_time(self, conn, zone_id):
        payloads = {"-P2fbAQFS": payload()}

        first = ingest(conn, payloads, zone_id)
        second = ingest(conn, payloads, zone_id)

        assert first.stored == 1
        assert second.stored == 0
        assert second.skipped == 1
        total = conn.execute("SELECT COUNT(*) AS n FROM readings").fetchone()["n"]
        assert total == 1

    def test_a_faulted_reading_is_stored_as_a_fault(self, conn, zone_id):
        payloads = {
            "-P2fbEJEZ": payload(
                components={"dht22": "OK", "lcd": "OK", "mq135": "I2C_DISCONNECTED"},
                gas_raw=5793,
            )
        }
        ingest(conn, payloads, zone_id)

        row = conn.execute("SELECT gas_raw, gas_ok, temp_ok FROM readings").fetchone()
        assert row["gas_raw"] is None
        assert row["gas_ok"] == 0
        assert row["temp_ok"] == 1

    def test_an_unusable_payload_does_not_stop_the_others(self, conn, zone_id):
        payloads = {
            "-P2fbAQFS": payload(),
            "-P2fbEJEZ": {"device_id": DEVICE},  # no timestamp
        }
        result = ingest(conn, payloads, zone_id)

        assert result.stored == 1
        assert result.rejected == 1

    def test_nothing_to_do_is_not_an_error(self, conn, zone_id):
        assert ingest(conn, {}, zone_id).stored == 0

    def test_the_outbox_is_left_alone_unless_asked(self, conn, zone_id):
        ingest(conn, {"-P2fbAQFS": payload()}, zone_id)
        queued = conn.execute("SELECT COUNT(*) AS n FROM outbox").fetchone()["n"]
        assert queued == 0

    def test_mirroring_queues_the_reading_for_the_cloud(self, conn, zone_id):
        ingest(conn, {"-P2fbAQFS": payload()}, zone_id, queue_event=True)
        queued = conn.execute(
            "SELECT COUNT(*) AS n FROM outbox WHERE entity = 'reading'"
        ).fetchone()["n"]
        assert queued == 1


class TestFetch:
    def test_a_cloud_failure_is_reported_not_raised_raw(self):
        class Broken:
            def child(self, _path):
                raise RuntimeError("network down")

        with pytest.raises(IngestError, match="could not read"):
            fetch_payloads(Broken(), DEVICE)

    def test_an_empty_node_returns_an_empty_mapping(self):
        class Empty:
            def child(self, _path):
                return self

            def order_by_key(self):
                return self

            def limit_to_last(self, _n):
                return self

            def get(self):
                return None

        assert fetch_payloads(Empty(), DEVICE) == {}
