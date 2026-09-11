import os
import time
from datetime import datetime, timedelta
from unittest.mock import Mock

from scheduler import healthcheck


def _stale_heartbeat_file(path):
    path.touch()
    age = healthcheck.MAX_LOOP_HEARTBEAT_AGE + timedelta(minutes=1)
    stale = time.time() - age.total_seconds()
    os.utime(path, (stale, stale))
    return path


def test_idle_loop_is_healthy_without_reading_run_state(tmp_path, monkeypatch):
    """Before the daily cron there is no run state for today; that is not a fault."""
    heartbeat = tmp_path / "heartbeat"
    heartbeat.touch()
    load_state = Mock(side_effect=AssertionError("an idle loop must not need Mongo"))
    monkeypatch.setattr(healthcheck.db, "load_latest_run_state", load_state)

    assert healthcheck.main(str(heartbeat)) == 0


def test_blocked_loop_is_healthy_only_while_its_pass_advances(tmp_path, monkeypatch):
    heartbeat = _stale_heartbeat_file(tmp_path / "heartbeat")
    now = datetime.now()
    stale = now - healthcheck.MAX_ACTIVE_HEARTBEAT_AGE - timedelta(seconds=1)

    for state, expected in (
        ({"started_at": stale.isoformat(), "heartbeat_at": now.isoformat()}, 0),
        ({"heartbeat_at": stale.isoformat()}, 1),
        ({"heartbeat_at": now.isoformat(), "finished_at": now.isoformat()}, 1),
        (None, 1),
    ):
        monkeypatch.setattr(healthcheck.db, "load_latest_run_state", lambda state=state: state)
        assert healthcheck.main(str(heartbeat)) == expected


def test_missing_heartbeat_file_falls_back_to_the_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(healthcheck.db, "load_latest_run_state", lambda: None)

    assert healthcheck.main(str(tmp_path / "never-written")) == 1


def test_latest_run_state_is_read_regardless_of_date(monkeypatch):
    runs = Mock()
    runs.find_one.return_value = {"_id": "2026-09-10"}
    monkeypatch.setattr(healthcheck.db, "get_runs_collection", lambda: runs)

    assert healthcheck.db.load_latest_run_state() == {"_id": "2026-09-10"}
    runs.find_one.assert_called_once_with(sort=[("_id", healthcheck.db.DESCENDING)])
