"""Stale product metadata is repaired within a per-pass budget."""

from datetime import datetime, timedelta

import pytest

from scraper import scraper


NOW = datetime(2026, 9, 17, 8, 0)


def test_metadata_without_a_stamp_counts_as_stale():
    assert scraper._metadata_is_stale({"tpnc": "1"}, NOW) is True
    assert scraper._metadata_is_stale({"metadata_at": "not-a-date"}, NOW) is True
    assert scraper._metadata_is_stale(None, NOW) is False  # a new product is fetched in full anyway


def test_metadata_is_stale_only_after_the_max_age():
    fresh = (NOW - timedelta(days=scraper.METADATA_MAX_AGE_DAYS - 1)).isoformat()
    old = (NOW - timedelta(days=scraper.METADATA_MAX_AGE_DAYS + 1)).isoformat()
    assert scraper._metadata_is_stale({"metadata_at": fresh}, NOW) is False
    assert scraper._metadata_is_stale({"metadata_at": old}, NOW) is True


def test_budget_limits_how_many_products_a_pass_refreshes():
    budget = scraper.MetadataRefreshBudget(2)
    assert [budget.take() for _ in range(4)] == [True, True, False, False]
    budget.reset()
    assert budget.take() is True
    assert scraper.MetadataRefreshBudget(0).take() is False


@pytest.fixture
def product(monkeypatch):
    asked = []
    monkeypatch.setattr(scraper, "needs_scraping", lambda tpnc: True)
    monkeypatch.setattr(scraper, "get_product_api",
                        lambda tpnc, query_type: asked.append(query_type) or {"data": {"product": None}})
    return asked


def test_a_stored_product_with_stale_metadata_is_fetched_in_full(monkeypatch, product):
    monkeypatch.setattr(scraper.db, "get_product", lambda tpnc: {"tpnc": tpnc})
    monkeypatch.setattr(scraper, "_metadata_budget", scraper.MetadataRefreshBudget(1))

    assert scraper.process_product("1") == scraper.ProductResult.UNAVAILABLE
    assert scraper.process_product("2") == scraper.ProductResult.UNAVAILABLE
    # Only the first fits in the budget; the second falls back to prices only.
    assert product == ["full", "price"]


def test_fresh_metadata_keeps_the_cheap_price_query(monkeypatch, product):
    monkeypatch.setattr(scraper.db, "get_product", lambda tpnc: {"tpnc": tpnc, "metadata_at": datetime.now().isoformat()})
    monkeypatch.setattr(scraper, "_metadata_budget", scraper.MetadataRefreshBudget(10))

    scraper.process_product("1")

    assert product == ["price"]


def test_unknown_products_are_always_fetched_in_full(monkeypatch, product):
    monkeypatch.setattr(scraper.db, "get_product", lambda tpnc: None)
    monkeypatch.setattr(scraper, "_metadata_budget", scraper.MetadataRefreshBudget(0))

    scraper.process_product("1")

    assert product == ["full"]
