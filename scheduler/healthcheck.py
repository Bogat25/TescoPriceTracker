"""Container health check for the scrape scheduler.

The scheduler has no HTTP server, so health is based on its durable Mongo run
state. A completed run is healthy; an active run must keep advancing its
heartbeat. An explicitly finished incomplete run is unhealthy until retried.
"""

from datetime import datetime, timedelta

from mongo import database_manager as db


MAX_ACTIVE_HEARTBEAT_AGE = timedelta(minutes=15)


def main() -> int:
    state = db.load_run_state()
    if not state:
        return 1
    if state.get("completed") is True:
        return 0
    if state.get("finished_at"):
        return 1

    raw_heartbeat = state.get("heartbeat_at") or state.get("started_at")
    if not raw_heartbeat:
        return 1
    try:
        heartbeat = datetime.fromisoformat(raw_heartbeat)
    except (TypeError, ValueError):
        return 1
    return 0 if datetime.now() - heartbeat <= MAX_ACTIVE_HEARTBEAT_AGE else 1


if __name__ == "__main__":
    raise SystemExit(main())
