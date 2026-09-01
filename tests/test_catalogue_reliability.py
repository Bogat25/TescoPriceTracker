from unittest.mock import Mock

import pytest
from pymongo import errors as mongo_errors

from mongo import database_manager as db
from scraper import scraper


class _Cursor:
    def __init__(self, docs):
        self.docs = docs
        self.sort_spec = None
        self.skipped = None
        self.limited = None

    def sort(self, spec, *args):
        self.sort_spec = spec if not args else (spec, args[0])
        return self

    def skip(self, value):
        self.skipped = value
        return self

    def limit(self, value):
        self.limited = value
        return self

    def __iter__(self):
        return iter(self.docs)


class _BrowseCollection:
    def __init__(self):
        self.cursor = _Cursor([{
            "_id": "123",
            "name": "Apple",
            "browse_sort": {
                "details": {"last_scraped_price": 10.0, "discount_price": 8.0},
            },
        }])
        self.projection = None

    def count_documents(self, _query):
        return 1

    def find(self, _query, projection):
        self.projection = projection
        return self.cursor


def test_price_browse_is_sorted_and_paginated_in_mongodb(monkeypatch):
    collection = _BrowseCollection()
    monkeypatch.setattr(db, "get_db", lambda: collection)

    page = db.browse_products(skip=20, limit=10, sort_by="price", sort_dir="asc")

    assert "price_history" not in collection.projection
    assert collection.projection["browse_sort"] == 1
    assert collection.cursor.skipped == 20
    assert collection.cursor.limited == 10
    assert collection.cursor.sort_spec[0] == ("browse_sort.has_price", -1)
    assert page["results"][0]["discount_price"] == 8.0


def test_current_browse_fields_capture_effective_price_and_discount():
    fields = db._build_browse_sort_fields({
        "price_history": [{
            "date": "2026-09-01",
            "normal": {"price": 100},
            "discount": {"price": 75},
            "clubcard": None,
        }],
    })

    assert fields["effective_price"] == 75.0
    assert fields["has_discount"] is True
    assert fields["discount_ratio"] == 0.25


def test_product_read_and_write_failures_propagate(monkeypatch):
    collection = Mock()
    collection.find_one.side_effect = mongo_errors.AutoReconnect("offline")
    monkeypatch.setattr(db, "get_db", lambda: collection)
    with pytest.raises(db.DatabaseOperationError):
        db.load_product_data("123")

    collection.find_one.side_effect = None
    collection.replace_one.side_effect = mongo_errors.AutoReconnect("offline")
    with pytest.raises(db.DatabaseOperationError):
        db.save_product_data("123", {})


def test_sitemap_failures_do_not_become_an_empty_success(monkeypatch):
    response = Mock(content=b"<sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'/>")
    response.raise_for_status.return_value = None
    monkeypatch.setattr(scraper.requests, "get", Mock(return_value=response))

    with pytest.raises(scraper.SitemapFetchError):
        scraper.fetch_sitemap_index("https://example.invalid/index.xml")


def test_worker_run_state_write_failure_fails_the_scrape(monkeypatch):
    saves = 0

    def fail_second_save(_state):
        nonlocal saves
        saves += 1
        if saves >= 2:
            raise db.DatabaseOperationError("offline")

    monkeypatch.setattr(scraper.db, "init_db", lambda: None)
    monkeypatch.setattr(scraper.db, "product_exists", lambda _tpnc: False)
    monkeypatch.setattr(scraper.db, "save_run_state", fail_second_save)
    monkeypatch.setattr(scraper, "get_product_api", lambda *_args: {"data": {"product": {}}})
    monkeypatch.setattr(scraper, "process_product", lambda *_args, **_kwargs: scraper.ProductResult.SUCCESS)

    with pytest.raises(db.DatabaseOperationError):
        scraper.run_scraper(specific_items=["123"], threads=1)
