"""Price drops sent to the alert service by stores other than Tesco."""

from datetime import date

import pytest
import requests

from stores import alerts_feed, queries


TODAY = date(2026, 9, 17)


class HistoryAdapter:
    def __init__(self, products):
        self.products = products

    def iter_histories(self, gtin_norms=None):
        for product_id, name, gtin, rows in self.products:
            yield f"auchan:{product_id}", name, "Italok", gtin, rows


@pytest.fixture
def adapter(monkeypatch):
    adapter = HistoryAdapter([
        ("1", "Tej", "5998200557699", [("2026-09-16", 400.0, None, None), ("2026-09-17", 400.0, None, 350.0)]),
        ("2", "Kávé", None, [("2026-09-16", 1000.0, None, None), ("2026-09-17", 1100.0, None, None)]),
        ("3", "Back after months", None, [("2026-05-01", 900.0, None, None), ("2026-09-17", 500.0, None, None)]),
        ("4", "Not today", None, [("2026-09-15", 900.0, None, None), ("2026-09-16", 500.0, None, None)]),
        ("5", "New", None, [("2026-09-17", 10.0, None, None)]),
        ("6", "Weighed", "2802590000000", [("2026-09-16", 10.0, 9.0, None), ("2026-09-17", 8.0, None, None)]),
    ])
    monkeypatch.setattr(queries, "ADAPTERS", {"auchan": adapter})
    return adapter


def test_todays_drops_use_the_best_price_of_each_day(adapter):
    drops = alerts_feed.todays_drops("auchan", TODAY)
    assert [d["productId"] for d in drops] == ["auchan:1", "auchan:6"]
    assert drops[0] == {
        "productId": "auchan:1", "store": "auchan", "groupId": "g:5998200557699",
        "productName": "Tej", "oldPrice": 400.0, "newPrice": 350.0,
    }
    assert drops[1]["groupId"] is None  # in-store codes never link stores


class Response:
    def __init__(self, status):
        self.status_code = status


@pytest.mark.real_alerts_feed
def test_notify_posts_once_with_a_store_run_key(adapter, monkeypatch):
    sent = []
    monkeypatch.setenv("INTERNAL_TRIGGER_TOKEN", "secret")
    monkeypatch.setattr(alerts_feed.requests, "post", lambda url, json, headers, timeout: sent.append((json, headers)) or Response(200))
    assert alerts_feed.notify("auchan", TODAY) is True
    payload, headers = sent[0]
    assert payload["runKey"] == "auchan:2026-09-17"
    assert len(payload["drops"]) == 2
    assert headers["X-Internal-Token"] == "secret"


@pytest.mark.real_alerts_feed
def test_notify_failures_are_reported_for_retry(adapter, monkeypatch):
    monkeypatch.setenv("INTERNAL_TRIGGER_TOKEN", "secret")
    monkeypatch.setattr(alerts_feed.requests, "post", lambda *a, **k: Response(503))
    assert alerts_feed.notify("auchan", TODAY) is False

    def boom(*_a, **_k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(alerts_feed.requests, "post", boom)
    assert alerts_feed.notify("auchan", TODAY) is False


@pytest.mark.real_alerts_feed
def test_notify_without_token_or_drops_has_nothing_to_deliver(monkeypatch):
    monkeypatch.delenv("INTERNAL_TRIGGER_TOKEN", raising=False)
    assert alerts_feed.notify("auchan", TODAY) is True
    monkeypatch.setenv("INTERNAL_TRIGGER_TOKEN", "secret")
    monkeypatch.setattr(queries, "ADAPTERS", {"auchan": HistoryAdapter([])})
    assert alerts_feed.notify("auchan", TODAY) is True
