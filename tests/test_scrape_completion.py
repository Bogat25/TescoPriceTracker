"""A completed day must publish statistics and price-drop alerts exactly once."""

import copy
import logging
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from scraper import scraper


class _RunStore:
    """Stands in for the Mongo run-state collection: every save is a snapshot."""

    def __init__(self):
        self.state = None

    def save(self, state):
        self.state = copy.deepcopy(state)

    def load(self):
        return copy.deepcopy(self.state)


@pytest.fixture
def store(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    store = _RunStore()
    monkeypatch.setattr(scraper.db, "init_db", lambda: None)
    monkeypatch.setattr(scraper.db, "save_run_state", store.save)
    monkeypatch.setattr(scraper.db, "load_run_state", store.load)
    monkeypatch.setattr(scraper.db, "product_exists", lambda _: True)
    monkeypatch.setattr(scraper.time, "sleep", lambda _: None)
    monkeypatch.setattr(scraper, "fetch_sitemap_index", lambda _: ["sitemap"])
    monkeypatch.setattr(scraper, "fetch_product_urls_from_sitemap", lambda _: ["123"])
    return store


def _completion_events(caplog):
    return [r for r in caplog.records if getattr(r, "Action", None) == "scrape.completed"]


def test_failed_publication_is_resumed_by_the_next_already_current_pass(store, monkeypatch, caplog):
    rebuild = Mock(side_effect=[RuntimeError("stats offline"), None])
    notify = Mock(return_value=True)
    monkeypatch.setattr(scraper.stats_manager, "rebuild_all_cache", rebuild)
    monkeypatch.setattr(scraper, "_notify_alert_service", notify)
    monkeypatch.setattr(scraper, "get_product_api", lambda *_: {"data": {"product": {}}})
    monkeypatch.setattr(scraper, "process_product", lambda *_args, **_kwargs: scraper.ProductResult.SUCCESS)
    monkeypatch.setattr(scraper, "needs_scraping", lambda _: True)

    first = scraper.run_scraper()

    assert first["completed"] is True
    assert first["finalized"] is False
    assert not scraper.is_run_finished(store.load())
    notify.assert_not_called()

    monkeypatch.setattr(scraper, "needs_scraping", lambda _: False)
    second = scraper.run_scraper()

    assert second["finalized"] is True
    assert scraper.is_run_finished(store.load())
    assert rebuild.call_count == 2
    notify.assert_called_once_with(run_key=f"daily:{date.today().isoformat()}")
    assert len(_completion_events(caplog)) == 1


def test_already_current_day_publishes_and_logs_completion_once(store, monkeypatch, caplog):
    rebuild = Mock()
    notify = Mock(return_value=True)
    monkeypatch.setattr(scraper.stats_manager, "rebuild_all_cache", rebuild)
    monkeypatch.setattr(scraper, "_notify_alert_service", notify)
    monkeypatch.setattr(scraper, "needs_scraping", lambda _: False)

    scraper.run_scraper()
    scraper.run_scraper()

    assert scraper.is_run_finished(store.load())
    assert rebuild.call_count == 1
    assert notify.call_count == 1
    assert len(_completion_events(caplog)) == 1


def test_rejected_alert_trigger_is_retried_without_rebuilding_again(store, monkeypatch):
    rebuild = Mock()
    notify = Mock(side_effect=[False, True])
    monkeypatch.setattr(scraper.stats_manager, "rebuild_all_cache", rebuild)
    monkeypatch.setattr(scraper, "_notify_alert_service", notify)
    monkeypatch.setattr(scraper, "needs_scraping", lambda _: False)

    first = scraper.run_scraper()
    second = scraper.run_scraper()

    assert first["finalized"] is False
    assert "alerts_notified_at" not in first
    assert second["finalized"] is True
    assert rebuild.call_count == 1
    assert notify.call_count == 2


def test_day_completed_before_finalization_tracking_is_not_republished(store, monkeypatch):
    today = date.today().isoformat()
    store.state = {"_id": today, "date": today, "completed": True}
    rebuild = Mock()
    notify = Mock(return_value=True)
    monkeypatch.setattr(scraper.stats_manager, "rebuild_all_cache", rebuild)
    monkeypatch.setattr(scraper, "_notify_alert_service", notify)
    monkeypatch.setattr(scraper, "needs_scraping", lambda _: False)

    state = scraper.run_scraper()

    assert state["finalized"] is True
    rebuild.assert_not_called()
    notify.assert_not_called()


def test_alert_trigger_carries_the_run_key_and_reports_failures(monkeypatch):
    # The real import is resolved from the entrypoint directory at runtime.
    monkeypatch.syspath_prepend(str(Path(scraper.__file__).parent))
    monkeypatch.setenv("INTERNAL_TRIGGER_TOKEN", "token")
    monkeypatch.setattr(scraper.db, "get_today_price_drops", lambda: [{"productId": "1", "newPrice": 9}])
    post = Mock(side_effect=[
        requests.ConnectionError("alert-service down"),
        Mock(status_code=503, text="unavailable"),
        Mock(status_code=200, json=lambda: {"emailsSent": 1}),
    ])
    monkeypatch.setattr(scraper.requests, "post", post)

    assert scraper._notify_alert_service(run_key="daily:2026-09-11") is False
    assert scraper._notify_alert_service(run_key="daily:2026-09-11") is False
    assert scraper._notify_alert_service(run_key="daily:2026-09-11") is True
    assert post.call_args.kwargs["json"]["runKey"] == "daily:2026-09-11"
