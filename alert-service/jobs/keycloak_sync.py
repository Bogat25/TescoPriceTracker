"""Daily Keycloak → local users cache sync.

Runs as its own container. Wakes up on the configured cron expression, walks the
realm via the Admin API, and upserts (sub, email) into the local ``users``
collection. This keeps the alert pipeline self-sufficient when a user hasn't
hit any of the alert API endpoints recently (so JIT didn't refresh them).
"""

# Path bootstrap — must run BEFORE any sibling imports.
# This script lives in alert-service/jobs/ but sibling-imports modules from
# alert-service/ (db, settings, services, logging_setup). Python only adds
# the script's own directory (jobs/) to sys.path, not its parent. Inject the
# parent so `import settings` etc. resolve regardless of how the script is
# invoked (`python jobs/keycloak_sync.py`, `python -m jobs.keycloak_sync`,
# etc.).
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pycron

import db as alert_db
import settings
from services import keycloak_admin, user_repo


from logging_setup import setup_logging, bind_correlation_id, clear_context

setup_logging(level=settings.LOG_LEVEL)
logger = logging.getLogger("alert-keycloak-sync")

TZ = ZoneInfo("Europe/Budapest")


async def run_sync_once() -> tuple[int, int]:
    upserted = 0
    skipped = 0
    async for sub, email in keycloak_admin.iter_users():
        if not email:
            skipped += 1
            continue
        await user_repo.upsert(sub, email)
        upserted += 1
    return upserted, skipped


async def _main_loop() -> None:
    logger.info("Keycloak sync starting (cron=%s, tz=%s)", settings.KEYCLOAK_SYNC_CRON, TZ.key)
    while True:
        try:
            now = datetime.now(TZ)
            if pycron.is_now(settings.KEYCLOAK_SYNC_CRON, dt=now):
                # New correlation ID per sync invocation so log lines from
                # this run share one trace ID and can be filtered together.
                bind_correlation_id()
                try:
                    logger.info("Tick: running Keycloak sync")
                    upserted, skipped = await run_sync_once()
                    logger.info("Sync complete — upserted=%d skipped=%d", upserted, skipped)
                finally:
                    clear_context()
                # Skip past the matched minute so we don't double-fire on the next tick.
                await asyncio.sleep(60)
        except Exception:
            logger.exception("Keycloak sync iteration failed")
        await asyncio.sleep(20)


async def _run_once_and_exit() -> None:
    bind_correlation_id()
    try:
        upserted, skipped = await run_sync_once()
        logger.info("One-shot sync complete — upserted=%d skipped=%d", upserted, skipped)
    finally:
        clear_context()


def _close_db_sync() -> None:
    try:
        asyncio.run(alert_db.close())
    except RuntimeError:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Keycloak users → local cache sync")
    parser.add_argument("--once", action="store_true", help="Run once and exit (skip cron loop)")
    args = parser.parse_args()

    try:
        if args.once:
            asyncio.run(_run_once_and_exit())
        else:
            asyncio.run(_main_loop())
    except KeyboardInterrupt:
        logger.info("interrupted")
    finally:
        _close_db_sync()
