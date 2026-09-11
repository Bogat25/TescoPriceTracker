from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytz


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEDULER_DIR = REPO_ROOT / "scheduler"
if str(SCHEDULER_DIR) not in sys.path:
    sys.path.append(str(SCHEDULER_DIR))

from scheduler import scheduler  # noqa: E402


def _now(hour=10):
    return pytz.timezone("Europe/Budapest").localize(datetime(2026, 9, 1, hour, 0))


def test_incomplete_run_schedules_bounded_exponential_retry(monkeypatch):
    monkeypatch.setattr(scheduler, "SCHEDULER_RETRY_INITIAL_SECONDS", 60)
    monkeypatch.setattr(scheduler, "SCHEDULER_RETRY_MAX_SECONDS", 180)
    monkeypatch.setattr(scheduler, "SCHEDULER_MAX_RETRIES_PER_DAY", 6)
    monkeypatch.setattr(scheduler, "SCHEDULER_RETRY_CUTOFF_HOUR", 23)

    first, count = scheduler.calculate_next_retry(
        {"completed": False, "retryable": True}, 0, _now()
    )
    third, third_count = scheduler.calculate_next_retry(
        {"completed": False, "retryable": True}, 2, _now()
    )

    assert first == _now() + timedelta(seconds=60)
    assert count == 1
    assert third == _now() + timedelta(seconds=180)
    assert third_count == 3


def test_completed_or_non_retryable_run_is_not_rescheduled():
    assert scheduler.calculate_next_retry(
        {"completed": True}, 2, _now()
    ) == (None, 0)
    assert scheduler.calculate_next_retry(
        {"completed": False, "retryable": False}, 2, _now()
    ) == (None, 2)


def test_daily_retry_limit_and_cutoff_are_enforced(monkeypatch):
    monkeypatch.setattr(scheduler, "SCHEDULER_MAX_RETRIES_PER_DAY", 2)
    monkeypatch.setattr(scheduler, "SCHEDULER_RETRY_CUTOFF_HOUR", 23)
    assert scheduler.calculate_next_retry(
        {"completed": False, "retryable": True}, 2, _now()
    ) == (None, 2)

    monkeypatch.setattr(scheduler, "SCHEDULER_RETRY_INITIAL_SECONDS", 7200)
    assert scheduler.calculate_next_retry(
        {"completed": False, "retryable": True}, 0, _now(22)
    ) == (None, 0)


def test_schedule_retry_persists_next_attempt(monkeypatch):
    saved = []
    monkeypatch.setattr(scheduler, "SCHEDULER_RETRY_INITIAL_SECONDS", 60)
    monkeypatch.setattr(scheduler, "SCHEDULER_RETRY_MAX_SECONDS", 60)
    monkeypatch.setattr(scheduler, "SCHEDULER_MAX_RETRIES_PER_DAY", 1)
    monkeypatch.setattr(scheduler, "SCHEDULER_RETRY_CUTOFF_HOUR", 23)
    monkeypatch.setattr(scheduler.db, "save_run_state", lambda state: saved.append(state))

    next_retry, count = scheduler.schedule_retry(
        {"date": "2026-09-01", "completed": False, "retryable": True},
        0,
        _now(),
    )

    assert next_retry == _now() + timedelta(seconds=60)
    assert count == 1
    assert saved[-1]["scheduler_retry_number"] == 1
    assert saved[-1]["next_retry_at"] == next_retry.isoformat()


def test_retry_waits_until_the_upstream_rate_limit_ends(monkeypatch):
    monkeypatch.setattr(scheduler, "SCHEDULER_RETRY_INITIAL_SECONDS", 60)
    monkeypatch.setattr(scheduler, "SCHEDULER_RETRY_MAX_SECONDS", 60)
    monkeypatch.setattr(scheduler, "SCHEDULER_MAX_RETRIES_PER_DAY", 6)
    monkeypatch.setattr(scheduler, "SCHEDULER_RETRY_CUTOFF_HOUR", 23)
    blocked_until = _now() + timedelta(hours=2)

    next_retry, count = scheduler.calculate_next_retry(
        {
            "completed": False,
            "retryable": True,
            "upstream_blocked_until": blocked_until.astimezone(timezone.utc).isoformat(),
        },
        0,
        _now(),
    )

    assert next_retry == blocked_until
    assert count == 1
