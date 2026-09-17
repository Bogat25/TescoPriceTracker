"""Container health check for the Auchan scheduler: liveness only.

The loop touches a heartbeat file, but blocks while a crawl runs; during a
crawl the persisted run heartbeat, saved after every page, must keep moving.
"""

import os
import sys
from datetime import datetime, timedelta

from stores.auchan import repository


HEARTBEAT_FILE = os.getenv("AUCHAN_SCHEDULER_HEARTBEAT_FILE", "/tmp/auchan-scheduler-heartbeat")
MAX_LOOP_HEARTBEAT_AGE = timedelta(minutes=10)
MAX_ACTIVE_HEARTBEAT_AGE = timedelta(minutes=15)


def is_loop_alive(path: str = HEARTBEAT_FILE, now: datetime = None) -> bool:
    try:
        touched = datetime.fromtimestamp(os.path.getmtime(path))
    except OSError:
        return False
    return (now or datetime.now()) - touched <= MAX_LOOP_HEARTBEAT_AGE


def is_crawl_progressing(state, now: datetime = None) -> bool:
    if not state or state.get("finished_at"):
        return False
    try:
        heartbeat = datetime.fromisoformat(state.get("heartbeat_at") or state.get("started_at"))
    except (TypeError, ValueError):
        return False
    if heartbeat.tzinfo is not None:
        heartbeat = heartbeat.replace(tzinfo=None)
    return (now or datetime.now()) - heartbeat <= MAX_ACTIVE_HEARTBEAT_AGE


def main() -> int:
    if is_loop_alive():
        return 0
    try:
        return 0 if is_crawl_progressing(repository.latest_run()) else 1
    except repository.RepositoryError:
        return 1


if __name__ == "__main__":
    sys.exit(main())
