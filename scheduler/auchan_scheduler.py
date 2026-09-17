"""Scheduler for the daily Auchan crawl (its own container, ``auchan-scheduler``).

Runs once a day on ``AUCHAN_SCHEDULER_CRON``, and at start-up when today's
crawl is not finished. An incomplete pass is retried with bounded exponential
backoff, never before a rate-limit window has passed.
"""

import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pycron
import pytz

from config import (
    SCHEDULER_MAX_RETRIES_PER_DAY,
    SCHEDULER_RETRY_CUTOFF_HOUR,
    SCHEDULER_RETRY_INITIAL_SECONDS,
    SCHEDULER_RETRY_MAX_SECONDS,
    SCHEDULER_TIMEZONE,
)
from logging_setup import bind_correlation_id, clear_context, setup_logging
from stores.auchan import crawler, repository
from stores.auchan.mapper import STORE_ID
from stores.registry import registry


setup_logging()
logger = logging.getLogger(__name__)

CRON = os.getenv("AUCHAN_SCHEDULER_CRON", "30 6 * * *")
HEARTBEAT_FILE = os.getenv("AUCHAN_SCHEDULER_HEARTBEAT_FILE", "/tmp/auchan-scheduler-heartbeat")


def now_in_tz() -> datetime:
    return datetime.now(pytz.timezone(SCHEDULER_TIMEZONE))


def touch_heartbeat() -> None:
    try:
        Path(HEARTBEAT_FILE).touch()
    except OSError:
        logger.warning("Could not update the Auchan scheduler heartbeat file.", exc_info=True)


def _blocked_until(state):
    try:
        value = datetime.fromisoformat(state["upstream_blocked_until"])
    except (KeyError, TypeError, ValueError):
        return None
    return value.astimezone(pytz.timezone(SCHEDULER_TIMEZONE)) if value.tzinfo else None


def next_retry(state, retries_scheduled: int, current_time: datetime):
    """Return ``(retry_at, count)``; ``retry_at`` is None when no retry is due today."""
    if not state or crawler.is_run_finished(state) or state.get("retryable") is False:
        return None, retries_scheduled
    if retries_scheduled >= SCHEDULER_MAX_RETRIES_PER_DAY or current_time.hour >= SCHEDULER_RETRY_CUTOFF_HOUR:
        return None, retries_scheduled
    count = retries_scheduled + 1
    delay = min(SCHEDULER_RETRY_INITIAL_SECONDS * 2 ** (count - 1), SCHEDULER_RETRY_MAX_SECONDS)
    retry_at = current_time + timedelta(seconds=delay)
    blocked_until = _blocked_until(state)
    if blocked_until is not None and blocked_until > retry_at:
        retry_at = blocked_until
    if retry_at.date() != current_time.date() or retry_at.hour >= SCHEDULER_RETRY_CUTOFF_HOUR:
        return None, retries_scheduled
    return retry_at, count


def run_pass():
    bind_correlation_id()
    try:
        return crawler.run_crawl()
    except Exception as exc:
        logger.exception(
            "Auchan scrape pass crashed: %s", exc,
            extra={"Action": "scrape.crashed", "Category": "job", "Store": STORE_ID},
        )
        return {"completed": False, "retryable": True, "failure_reason": str(exc)[:2000]}
    finally:
        clear_context()


def _schedule_after(state, retries_scheduled):
    retry_at, count = next_retry(state, retries_scheduled, now_in_tz())
    if retry_at is not None:
        logger.warning(
            "Incomplete Auchan scrape scheduled for retry %s at %s.", count, retry_at.isoformat(),
            extra={"Action": "scrape.retry_scheduled", "Category": "job", "Store": STORE_ID},
        )
    elif state and not crawler.is_run_finished(state):
        logger.error(
            "Incomplete Auchan scrape will not be retried again today.",
            extra={"Action": "scrape.retry_exhausted", "Category": "job", "Store": STORE_ID},
        )
    return retry_at, count


def today_finished(current_time: datetime) -> bool:
    return crawler.is_run_finished(repository.load_run(current_time.date().isoformat()))


def run_scheduler() -> None:
    logger.info("Auchan scheduler started (cron: %s, tz: %s).", CRON, SCHEDULER_TIMEZONE)
    registry.seed()
    repository.ensure_indexes()
    day = None
    retry_at = None
    retries = 0
    disabled_logged_for = None
    startup_checked = False

    while True:
        touch_heartbeat()
        current_time = now_in_tz()
        if current_time.date() != day:
            day, retry_at, retries = current_time.date(), None, 0

        if not registry.scrape_enabled(STORE_ID):
            if disabled_logged_for != day:
                disabled_logged_for = day
                logger.info(
                    "Auchan scraping is switched off in the store registry; skipping.",
                    extra={"Action": "scrape.disabled", "Category": "job", "Store": STORE_ID},
                )
            retry_at = None
            startup_checked = False
            time.sleep(60)
            continue
        disabled_logged_for = None

        due = (
            (not startup_checked and not today_finished(current_time))
            or (retry_at is not None and current_time >= retry_at)
            or (pycron.is_now(CRON, dt=current_time) and not today_finished(current_time))
        )
        startup_checked = True
        if due:
            state = run_pass()
            retry_at, retries = _schedule_after(state, retries)
            continue
        time.sleep(30)


if __name__ == "__main__":
    run_scheduler()
