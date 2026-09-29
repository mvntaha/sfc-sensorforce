"""Pull the Raspberry Pi's Firebase readings into SQLite, once or continuously.

Run this alongside the Flask app when the Pi publishes to Firebase rather than
writing to the local database directly. Each cycle fetches the most recent
device readings and stores the ones SQLite does not already have, so the
dashboard, the freshness engine and the charts all see live measurements
through the path they already use.

Safe to run twice, and safe to stop and restart: identity is the reading's
timestamp, so nothing is stored a second time.

Usage:
    python scripts/ingest_pi.py --once        # one cycle, then exit
    python scripts/ingest_pi.py               # loop until interrupted
    python scripts/ingest_pi.py --zone 2      # store into a different zone
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:  # pragma: no cover - convenience for direct runs
    sys.path.insert(0, str(REPO_ROOT))

from core import db  # noqa: E402
from core.cloud_ingest import (  # noqa: E402
    IngestError,
    fetch_payloads,
    fetch_snapshot,
    ingest,
    save_snapshot,
)
from core.config import get_settings  # noqa: E402
from core.paths import snapshot_path  # noqa: E402

logger = logging.getLogger(__name__)

#: Seconds between cycles. The device publishes about every 16 s, so this
#: keeps the dashboard within one reading of live without hammering the link.
DEFAULT_INTERVAL_S = 10.0


def _reference(settings):
    """Open a Firebase reference for the database root."""
    import firebase_admin
    from firebase_admin import credentials
    from firebase_admin import db as firebase_db

    name = "freshguard-ingest"
    try:
        app = firebase_admin.get_app(name)
    except ValueError:
        app = firebase_admin.initialize_app(
            credentials.Certificate(str(settings.firebase.cred_path)),
            {"databaseURL": settings.firebase.db_url},
            name=name,
        )
    return firebase_db.reference("/", app=app)


def main(argv: list[str] | None = None) -> int:
    """Ingest once or in a loop. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="run one cycle and exit")
    parser.add_argument("--zone", type=int, default=1, help="zone to store readings into")
    parser.add_argument("--device", default=None, help="device id (default: FG_DEVICE_ID)")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_S)
    parser.add_argument(
        "--mirror",
        action="store_true",
        help="also queue each ingested reading to the outbox",
    )
    parser.add_argument(
        "--no-snapshot",
        action="store_true",
        help="skip the camera frame, and fetch readings only",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    settings = get_settings()
    if not settings.firebase.configured:
        logger.error("Firebase is not configured; set FIREBASE_DB_URL and FIREBASE_CRED_PATH")
        return 1

    device = args.device or settings.device_id
    reference = _reference(settings)
    conn = db.connect(settings.db_path)

    try:
        while True:
            try:
                payloads = fetch_payloads(reference, device)
                result = ingest(
                    conn, payloads, args.zone, device_id=device, queue_event=args.mirror
                )
                if not args.no_snapshot:
                    # The photograph is a convenience, never a measurement, so a
                    # camera problem must not stop readings being ingested.
                    frame = fetch_snapshot(reference, device)
                    if frame is not None:
                        save_snapshot(frame, snapshot_path(device))
            except IngestError as exc:
                # The link is allowed to fail. The device keeps publishing and
                # the next cycle picks up whatever was missed.
                logger.warning("%s", exc)
            else:
                if result.stored or result.rejected:
                    logger.info(
                        "stored %d, already had %d, unusable %d",
                        result.stored,
                        result.skipped,
                        result.rejected,
                    )
            if args.once:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:  # pragma: no cover - interactive stop
        logger.info("stopped")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(main())
