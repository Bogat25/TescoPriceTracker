from datetime import datetime, timedelta, timezone

from scheduler import healthcheck


def test_completed_run_is_healthy():
    assert healthcheck.is_state_healthy({"completed": True})


def test_active_run_requires_a_fresh_heartbeat():
    now = datetime.now()
    assert healthcheck.is_state_healthy({"heartbeat_at": now.isoformat()})
    assert not healthcheck.is_state_healthy({
        "heartbeat_at": (
            now - healthcheck.MAX_ACTIVE_HEARTBEAT_AGE - timedelta(seconds=1)
        ).isoformat(),
    })


def test_finished_retryable_run_is_healthy_while_waiting(monkeypatch):
    now = datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)
    next_retry = now + timedelta(minutes=30)
    monkeypatch.setattr(healthcheck, "_now_for", lambda _timestamp: now)

    assert healthcheck.is_state_healthy({
        "completed": False,
        "retryable": True,
        "finished_at": now.isoformat(),
        "next_retry_at": next_retry.isoformat(),
    })


def test_missed_or_non_retryable_finished_run_is_unhealthy(monkeypatch):
    now = datetime(2026, 9, 4, 19, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(healthcheck, "_now_for", lambda _timestamp: now)

    assert not healthcheck.is_state_healthy({
        "completed": False,
        "retryable": True,
        "finished_at": now.isoformat(),
        "next_retry_at": (
            now - healthcheck.MAX_RETRY_START_DELAY - timedelta(seconds=1)
        ).isoformat(),
    })
    assert not healthcheck.is_state_healthy({
        "completed": False,
        "retryable": False,
        "finished_at": now.isoformat(),
    })
