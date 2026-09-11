import logging
import time
from datetime import datetime, timedelta

import pycron
import pytz

from config import (
    DEFAULT_THREADS,
    SCHEDULER_CRON,
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
    is_today_scrape_done,
    run_scraper,
)


setup_logging()
logger = logging.getLogger(__name__)


def now_in_tz():
    return datetime.now(pytz.timezone(SCHEDULER_TIMEZONE))


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


def _upstream_blocked_until(state):
    """Return when Tesco accepts requests again, in the scheduler timezone."""
    value = state.get("upstream_blocked_until") if state else None
    try:
        blocked_until = datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None
    if blocked_until is None or blocked_until.tzinfo is None:
        return None
    return blocked_until.astimezone(pytz.timezone(SCHEDULER_TIMEZONE))


def calculate_next_retry(state, retries_scheduled, current_time):
    """Return ``(next_retry_at, count)`` or ``(None, count)`` when exhausted."""
    if state and state.get("completed"):
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
        if state and not state.get("completed"):
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


def run_scheduler():
    logger.info("Container started. Checking today's run state...")
    retries_scheduled = 0
    next_retry_at = None
    retry_date = now_in_tz().date()

    if not is_today_scrape_done():
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
        current_time = now_in_tz()
        if current_time.date() != retry_date:
            retry_date = current_time.date()
            retries_scheduled = 0
            next_retry_at = None

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
