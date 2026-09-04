"""Container health check for the scrape scheduler.

The scheduler has no HTTP server, so health is based on its durable Mongo run
state. A completed run is healthy; an active run must keep advancing its
heartbeat. A retryable incomplete run is also healthy while it is waiting for
its persisted retry time, rather than appearing dead during expected backoff.
"""

from datetime import datetime, timedelta

from mongo import database_manager as db


MAX_ACTIVE_HEARTBEAT_AGE = timedelta(minutes=15)
MAX_RETRY_START_DELAY = timedelta(minutes=2)


def _now_for(timestamp: datetime) -> datetime:
    return datetime.now(timestamp.tzinfo) if timestamp.tzinfo else datetime.now()


def _parse_timestamp(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def is_state_healthy(state: dict) -> bool:
    """Evaluate scheduler liveness from one persisted daily run state."""
    if state.get("completed") is True:
        return True

    if state.get("finished_at"):
        if state.get("retryable") is not True:
            return False
        next_retry = _parse_timestamp(state.get("next_retry_at"))
        if next_retry is None:
            return False
        return _now_for(next_retry) <= next_retry + MAX_RETRY_START_DELAY

    heartbeat = _parse_timestamp(
        state.get("heartbeat_at") or state.get("started_at")
    )
    if heartbeat is None:
        return False
    return _now_for(heartbeat) - heartbeat <= MAX_ACTIVE_HEARTBEAT_AGE


def main() -> int:
    state = db.load_run_state()
    if not state:
        return 1
    return 0 if is_state_healthy(state) else 1


if __name__ == "__main__":
    raise SystemExit(main())
