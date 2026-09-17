"""Scheduler behaviour tied to the store registry, and the Auchan scheduler."""

import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytz

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEDULER_DIR = REPO_ROOT / "scheduler"
if str(SCHEDULER_DIR) not in sys.path:
    sys.path.append(str(SCHEDULER_DIR))

from scheduler import auchan_healthcheck, auchan_scheduler, scheduler  # noqa: E402
from stores import admin  # noqa: E402


TZ = pytz.timezone("Europe/Budapest")


def _now(hour=10):
    return TZ.localize(datetime(2026, 9, 17, hour, 0))


class Switch:
    def __init__(self, enabled):
        self.enabled = enabled

    def scrape_enabled(self, _store):
        return self.enabled


def test_tesco_scheduler_logs_disabled_once_per_day(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    switch = Switch(False)
    monkeypatch.setattr(scheduler, "registry", switch)
    notice = scheduler._DisabledNotice()
    day = _now().date()

    assert notice.scrape_allowed(day) is False
    assert notice.scrape_allowed(day) is False
    assert notice.scrape_allowed(day + timedelta(days=1)) is False
    switch.enabled = True
    assert notice.scrape_allowed(day + timedelta(days=1)) is True

    disabled = [r for r in caplog.records if getattr(r, "Action", None) == "scrape.disabled"]
    assert len(disabled) == 2


def _retry_settings(monkeypatch):
    monkeypatch.setattr(auchan_scheduler, "SCHEDULER_RETRY_INITIAL_SECONDS", 600)
    monkeypatch.setattr(auchan_scheduler, "SCHEDULER_RETRY_MAX_SECONDS", 1800)
    monkeypatch.setattr(auchan_scheduler, "SCHEDULER_MAX_RETRIES_PER_DAY", 3)
    monkeypatch.setattr(auchan_scheduler, "SCHEDULER_RETRY_CUTOFF_HOUR", 23)


def test_auchan_retry_backoff_is_bounded(monkeypatch):
    _retry_settings(monkeypatch)
    incomplete = {"completed": False, "retryable": True}
    assert auchan_scheduler.next_retry(incomplete, 0, _now()) == (_now() + timedelta(seconds=600), 1)
    assert auchan_scheduler.next_retry(incomplete, 2, _now()) == (_now() + timedelta(seconds=1800), 3)
    assert auchan_scheduler.next_retry(incomplete, 3, _now()) == (None, 3)


def test_auchan_no_retry_for_finished_fatal_or_late_passes(monkeypatch):
    _retry_settings(monkeypatch)
    published = {"completed": True, "alerts_notified_at": "2026-09-17T07:00:00"}
    assert auchan_scheduler.next_retry(published, 0, _now()) == (None, 0)
    assert auchan_scheduler.next_retry({"completed": False, "retryable": False}, 0, _now()) == (None, 0)
    assert auchan_scheduler.next_retry({"completed": False}, 0, _now(hour=23)) == (None, 0)
    assert auchan_scheduler.next_retry(None, 0, _now()) == (None, 0)


def test_auchan_completed_day_with_unsent_alerts_is_retried(monkeypatch):
    _retry_settings(monkeypatch)
    retry_at, count = auchan_scheduler.next_retry({"completed": True, "retryable": True}, 0, _now())
    assert retry_at == _now() + timedelta(seconds=600) and count == 1


def test_auchan_retry_waits_for_rate_limit_window(monkeypatch):
    _retry_settings(monkeypatch)
    blocked = (_now() + timedelta(hours=2)).astimezone(timezone.utc).isoformat()
    retry_at, _ = auchan_scheduler.next_retry({"completed": False, "upstream_blocked_until": blocked}, 0, _now())
    assert retry_at == _now() + timedelta(hours=2)


def test_auchan_healthcheck(tmp_path, monkeypatch):
    heartbeat = tmp_path / "hb"
    heartbeat.touch()
    assert auchan_healthcheck.is_loop_alive(str(heartbeat))
    stale = time.time() - (auchan_healthcheck.MAX_LOOP_HEARTBEAT_AGE + timedelta(minutes=1)).total_seconds()
    os.utime(heartbeat, (stale, stale))
    assert not auchan_healthcheck.is_loop_alive(str(heartbeat))

    now = datetime(2026, 9, 17, 7, 0)
    assert auchan_healthcheck.is_crawl_progressing({"heartbeat_at": "2026-09-17T06:50:00"}, now)
    assert not auchan_healthcheck.is_crawl_progressing({"heartbeat_at": "2026-09-17T06:30:00"}, now)
    assert not auchan_healthcheck.is_crawl_progressing(
        {"heartbeat_at": "2026-09-17T06:59:00", "finished_at": "2026-09-17T06:59:00"}, now)
    assert not auchan_healthcheck.is_crawl_progressing(None, now)


def test_admin_cli_sets_and_lists_switches(monkeypatch, capsys):
    calls = []

    class Registry:
        def seed(self):
            calls.append("seed")

        def set_flags(self, store, **flags):
            calls.append((store, flags))

        def all(self):
            return []

    monkeypatch.setattr(admin, "registry", Registry())
    assert admin.main(["set", "auchan", "enabled=false", "scrape_enabled=true"]) == 0
    assert calls == ["seed", ("auchan", {"enabled": False, "scrape_enabled": True})]


def test_admin_cli_rejects_bad_flags(monkeypatch):
    import pytest
    with pytest.raises(SystemExit):
        admin.main(["set", "auchan", "name=x"])
    with pytest.raises(SystemExit):
        admin.main(["set", "auchan", "enabled=maybe"])
