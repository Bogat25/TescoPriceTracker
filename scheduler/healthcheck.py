"""Container health check for the scrape scheduler.

The scheduler has no HTTP server. Its loop touches a heartbeat file on every
iteration but blocks while a scrape pass runs, so during a pass the durable
Mongo run state must keep advancing instead.

Container health reports liveness only. Whether a day's scrape completed is
reported by the Grafana alerts; judging it here marked the scheduler unhealthy
every night before the daily cron and all evening after retries ran out.
"""

import os
from datetime import datetime, timedelta

from config import SCHEDULER_HEARTBEAT_FILE
from mongo import database_manager as db


# Longer than catalogue discovery, which runs before a pass writes run state.
MAX_LOOP_HEARTBEAT_AGE = timedelta(minutes=30)
MAX_ACTIVE_HEARTBEAT_AGE = timedelta(minutes=15)


def _now_for(timestamp: datetime) -> datetime:
    return datetime.now(timestamp.tzinfo) if timestamp.tzinfo else datetime.now()


def _parse_timestamp(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def loop_heartbeat_at(path: str = SCHEDULER_HEARTBEAT_FILE):
    try:
        return datetime.fromtimestamp(os.path.getmtime(path))
    except OSError:
        return None


def is_loop_alive(heartbeat) -> bool:
    return heartbeat is not None and _now_for(heartbeat) - heartbeat <= MAX_LOOP_HEARTBEAT_AGE


def is_pass_progressing(state) -> bool:
    """True while an unfinished pass keeps advancing its persisted heartbeat."""
    if not state or state.get("finished_at"):
        return False
    heartbeat = _parse_timestamp(
        state.get("heartbeat_at") or state.get("started_at")
    )
    if heartbeat is None:
        return False
    return _now_for(heartbeat) - heartbeat <= MAX_ACTIVE_HEARTBEAT_AGE


def main(heartbeat_path: str = SCHEDULER_HEARTBEAT_FILE) -> int:
    if is_loop_alive(loop_heartbeat_at(heartbeat_path)):
        return 0
    # Mongo is read only while the loop is blocked, so a brief database outage
    # does not fail an idle scheduler. The latest state, not today's, keeps a
    # pass that crosses midnight visible.
    return 0 if is_pass_progressing(db.load_latest_run_state()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
