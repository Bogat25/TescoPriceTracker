import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import pycron
import pytz

from config import (
    DEFAULT_THREADS,
    SCHEDULER_CRON,
    SCHEDULER_HEARTBEAT_FILE,
    SCHEDULER_MAX_RETRIES_PER_DAY,
    SCHEDULER_RETRY_CUTOFF_HOUR,
    SCHEDULER_RETRY_INITIAL_SECONDS,
    SCHEDULER_RETRY_MAX_SECONDS,
    SCHEDULER_TIMEZONE,
)
from logging_setup import bind_correlation_id, clear_context, setup_logging
from mongo import database_manager as db
from scraper.scraper import (
    GraphQLContractError,
    UpstreamConfigurationError,
    is_run_finished,
    is_today_scrape_done,
    run_scraper,
)
from stores.registry import registry


setup_logging()
logger = logging.getLogger(__name__)

STORE_ID = "tesco"


class _DisabledNotice:
    """Log once per day that scraping is switched off, so staleness alerts can tell."""

    def __init__(self):
        self._logged_for = None

    def scrape_allowed(self, current_date) -> bool:
        if registry.scrape_enabled(STORE_ID):
            self._logged_for = None
            return True
        if self._logged_for != current_date:
            self._logged_for = current_date
            logger.info(
                "Tesco scraping is switched off in the store registry; skipping.",
                extra={"Action": "scrape.disabled", "Category": "job", "Store": STORE_ID},
            )
        return False


def now_in_tz():
    return datetime.now(pytz.timezone(SCHEDULER_TIMEZONE))


def touch_heartbeat():
    """Record that the loop is alive for healthcheck.py, a separate process."""
    try:
        Path(SCHEDULER_HEARTBEAT_FILE).touch()
    except OSError:
        logger.warning("Could not update the scheduler heartbeat file.", exc_info=True)


def job():
    """Run one scrape pass and return enough state for retry scheduling."""
    bind_correlation_id()
    try:
        logger.info(
            "Starting scheduled scrape job.",
            extra={"Action": "scrape.started", "Category": "job"},
        )
        try:
            state = run_scraper(threads=DEFAULT_THREADS)
        except (GraphQLContractError, UpstreamConfigurationError) as exc:
            # The scraper persists the detailed fatal state before raising.
            state = db.load_run_state() or {
                "date": now_in_tz().date().isoformat(),
                "completed": False,
                "failure_reason": str(exc)[:2000],
            }
            state["retryable"] = False
            logger.exception(
                "Scrape job stopped by a non-retryable upstream failure: %s",
                exc,
                extra={"Action": "scrape.fatal", "Category": "job"},
            )
            return state
        except Exception as exc:
            logger.exception(
                "Error during scrape job: %s",
                exc,
                extra={"Action": "scrape.crashed", "Category": "job"},
            )
            return {
                "date": now_in_tz().date().isoformat(),
                "completed": False,
                "retryable": True,
                "failure_reason": str(exc)[:2000],
            }

        logger.info(
            "Scrape job finished.",
            extra={"Action": "scrape.pass_finished", "Category": "job"},
        )
        return state or {
            "date": now_in_tz().date().isoformat(),
            "completed": False,
            "retryable": True,
            "failure_reason": "scraper returned no run state",
        }
    finally:
        clear_context()


def _aware_timestamp(value):
    """Parse a persisted ISO timestamp; naive or malformed values are ignored."""
    try:
        parsed = datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None
    return parsed if parsed is not None and parsed.tzinfo is not None else None


def _upstream_blocked_until(state):
    """Return when Tesco accepts requests again, in the scheduler timezone."""
    blocked_until = _aware_timestamp(state.get("upstream_blocked_until") if state else None)
    if blocked_until is None:
        return None
    return blocked_until.astimezone(pytz.timezone(SCHEDULER_TIMEZONE))


def calculate_next_retry(state, retries_scheduled, current_time):
    """Return ``(next_retry_at, count)`` or ``(None, count)`` when exhausted."""
    if state and is_run_finished(state):
        return None, 0
    if state and state.get("retryable") is False:
        return None, retries_scheduled
    if retries_scheduled >= SCHEDULER_MAX_RETRIES_PER_DAY:
        return None, retries_scheduled
    if current_time.hour >= SCHEDULER_RETRY_CUTOFF_HOUR:
        return None, retries_scheduled

    retry_number = retries_scheduled + 1
    delay = min(
        SCHEDULER_RETRY_INITIAL_SECONDS * (2 ** (retry_number - 1)),
        SCHEDULER_RETRY_MAX_SECONDS,
    )
    next_retry_at = current_time + timedelta(seconds=delay)
    blocked_until = _upstream_blocked_until(state)
    if blocked_until is not None and blocked_until > next_retry_at:
        # A pass inside Tesco's penalty window would only extend it.
        next_retry_at = blocked_until
    if (next_retry_at.date() != current_time.date()
            or next_retry_at.hour >= SCHEDULER_RETRY_CUTOFF_HOUR):
        return None, retries_scheduled
    return next_retry_at, retry_number


def schedule_retry(state, retries_scheduled, current_time):
    next_retry_at, retry_number = calculate_next_retry(
        state, retries_scheduled, current_time
    )
    if next_retry_at is None:
        if state and not is_run_finished(state):
            logger.error(
                "Incomplete scrape will not be retried again today.",
                extra={"Action": "scrape.retry_exhausted", "Category": "job"},
            )
        return None, retry_number

    if state:
        persisted_state = dict(state)
        persisted_state["scheduler_retry_number"] = retry_number
        persisted_state["next_retry_at"] = next_retry_at.isoformat()
        db.save_run_state(persisted_state)
    logger.warning(
        "Incomplete scrape scheduled for retry %s at %s.",
        retry_number,
        next_retry_at.isoformat(),
        extra={"Action": "scrape.retry_scheduled", "Category": "job"},
    )
    return next_retry_at, retry_number


def restore_retry_schedule(state):
    """Return today's persisted ``(next_retry_at, count)`` after a restart.

    A restart during backoff used to start a pass at once, inside any upstream
    penalty, and reset the day's retry budget to zero.
    """
    if not state or is_run_finished(state):
        return None, 0
    return (
        _aware_timestamp(state.get("next_retry_at")),
        int(state.get("scheduler_retry_number") or 0),
    )


def run_scheduler():
    logger.info("Container started. Checking today's run state...")
    touch_heartbeat()
    registry.seed()
    disabled_notice = _DisabledNotice()
    retry_date = now_in_tz().date()
    next_retry_at, retries_scheduled = restore_retry_schedule(db.load_run_state())

    if not disabled_notice.scrape_allowed(retry_date):
        next_retry_at = None
    elif next_retry_at is not None:
        logger.info(
            "Resuming persisted retry %s at %s.",
            retries_scheduled,
            next_retry_at.isoformat(),
            extra={"Action": "scrape.retry_restored", "Category": "job"},
        )
    elif not is_today_scrape_done():
        logger.info("Today's run not found - running initial scrape...")
        state = job()
        next_retry_at, retries_scheduled = schedule_retry(
            state, retries_scheduled, now_in_tz()
        )
    else:
        logger.info("Today's scrape already completed - skipping initial run.")

    logger.info(
        "Entering scheduler loop (cron: %s, tz: %s).",
        SCHEDULER_CRON,
        SCHEDULER_TIMEZONE,
    )

    while True:
        touch_heartbeat()
        current_time = now_in_tz()
        if current_time.date() != retry_date:
            retry_date = current_time.date()
            retries_scheduled = 0
            next_retry_at = None

        if not disabled_notice.scrape_allowed(current_time.date()):
            next_retry_at = None
            time.sleep(60)
            continue

        if next_retry_at is not None and current_time >= next_retry_at:
            state = job()
            next_retry_at, retries_scheduled = schedule_retry(
                state, retries_scheduled, now_in_tz()
            )
            continue

        if pycron.is_now(SCHEDULER_CRON, dt=current_time):
            if not is_today_scrape_done():
                state = job()
                next_retry_at, retries_scheduled = schedule_retry(
                    state, retries_scheduled, now_in_tz()
                )
            else:
                logger.info("Scheduled run skipped - today's scrape already completed.")
            time.sleep(60)
        time.sleep(20)


if __name__ == "__main__":
    run_scheduler()
