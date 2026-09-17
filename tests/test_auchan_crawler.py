"""The daily Auchan crawl: resume, category changes and failure classification."""

import copy
import json
import logging
from datetime import datetime
from pathlib import Path

from stores.auchan import crawler, repository
from stores.auchan.client import AuchanContractError, AuchanUnavailable


FIXTURE = Path(__file__).parent / "fixtures" / "auchan" / "product_list.json"
PRODUCTS = json.loads(FIXTURE.read_text(encoding="utf-8"))["results"]
NOW = datetime(2026, 9, 17, 6, 30)


class FakeClient:
    def __init__(self, pages, tree_ids=(1, 2), fail_on=None):
        self.pages = pages          # {(category, page): (results, page_count)}
        self.tree_ids = tree_ids
        self.fail_on = fail_on or {}
        self.requested = []

    def category_tree(self):
        return [{"id": category_id} for category_id in self.tree_ids]

    def list_products(self, category_id, page):
        self.requested.append((category_id, page))
        if (category_id, page) in self.fail_on:
            raise self.fail_on[(category_id, page)]
        results, page_count = self.pages[(category_id, page)]
        return {"results": results, "pageCount": page_count, "itemCount": len(results)}


class FakeRepository:
    def __init__(self, run=None):
        self.runs = {} if run is None else {run["date"]: copy.deepcopy(run)}
        self.saved = []

    def install(self, monkeypatch):
        monkeypatch.setattr(repository, "load_run", lambda date: copy.deepcopy(self.runs.get(date)))
        monkeypatch.setattr(repository, "save_run", lambda state: self.runs.__setitem__(state["date"], copy.deepcopy(state)))
        monkeypatch.setattr(repository, "save_page", self.save_page)
        monkeypatch.setattr(crawler, "fetch_missing_details", lambda *_: {"fetched": 0, "failed": 0})

    def save_page(self, fields_list, today, now=None):
        self.saved.extend(fields["store_product_id"] for fields in fields_list)
        return len(fields_list)


def run(client, repo, monkeypatch, categories=(1, 2)):
    repo.install(monkeypatch)
    return crawler.run_crawl(client=client, category_ids=categories, now=lambda: NOW)


def events(caplog, action):
    return [r for r in caplog.records if getattr(r, "Action", None) == action]


def test_full_crawl_saves_every_page_and_completes(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    client = FakeClient({(1, 1): (PRODUCTS[:2], 2), (1, 2): (PRODUCTS[2:3], 2), (2, 1): (PRODUCTS[3:], 1)})
    repo = FakeRepository()

    state = run(client, repo, monkeypatch)

    assert state["completed"] is True
    assert state["saved_count"] == 4
    assert repo.saved == ["942428", "632009", "469034", "658866"]
    assert client.requested == [(1, 1), (1, 2), (2, 1)]
    assert repo.runs["2026-09-17"]["categories"]["1"] == {"next_page": 3, "page_count": 2, "item_count": 1, "done": True}
    assert len(events(caplog, "scrape.completed")) == 1


def test_finished_day_is_not_crawled_again(monkeypatch):
    client = FakeClient({})
    repo = FakeRepository({"date": "2026-09-17", "completed": True})
    assert run(client, repo, monkeypatch)["completed"] is True
    assert client.requested == []


def test_rate_limit_leaves_a_resumable_state(monkeypatch, caplog):
    client = FakeClient(
        {(1, 1): (PRODUCTS[:1], 2), (2, 1): (PRODUCTS[1:2], 1)},
        fail_on={(1, 2): AuchanUnavailable("HTTP 429", retry_after=600, status_code=429)},
    )
    repo = FakeRepository()

    state = run(client, repo, monkeypatch)

    assert state["completed"] is False and state["retryable"] is True
    assert "upstream_blocked_until" in state
    assert state["categories"]["1"]["next_page"] == 2
    assert len(events(caplog, "scrape.incomplete")) == 1

    # The next pass continues at page 2 of category 1 instead of starting over.
    resumed = FakeClient({(1, 2): (PRODUCTS[2:3], 2), (2, 1): (PRODUCTS[3:], 1)})
    state = run(resumed, repo, monkeypatch)
    assert state["completed"] is True
    assert resumed.requested == [(1, 2), (2, 1)]
    assert "upstream_blocked_until" not in state


def test_contract_change_stops_without_retry(monkeypatch, caplog):
    client = FakeClient({}, fail_on={(1, 1): AuchanContractError("results missing")})
    state = run(client, FakeRepository(), monkeypatch)
    assert state["completed"] is False and state["retryable"] is False
    assert len(events(caplog, "scrape.fatal")) == 1


def test_removed_category_is_skipped_with_a_warning(monkeypatch, caplog):
    client = FakeClient({(1, 1): (PRODUCTS, 1)}, tree_ids=(1,))
    state = run(client, FakeRepository(), monkeypatch)
    assert state["completed"] is True
    assert state["categories"]["2"]["missing"] is True
    assert len(events(caplog, "auchan.category_missing")) == 1


def test_empty_catalogue_is_treated_as_a_contract_failure(monkeypatch):
    client = FakeClient({(1, 1): ([], 0), (2, 1): ([], 0)})
    state = run(client, FakeRepository(), monkeypatch)
    assert state["completed"] is False and state["retryable"] is False


def test_unusable_products_are_counted_not_fatal(monkeypatch):
    client = FakeClient({(1, 1): ([{"id": 5, "selectedVariant": None}, *PRODUCTS[:1]], 1)})
    state = run(client, FakeRepository(), monkeypatch, categories=(1,))
    assert state["completed"] is True
    assert state["skipped_count"] == 1 and state["saved_count"] == 1


def test_configured_categories_from_environment(monkeypatch):
    monkeypatch.setenv("AUCHAN_CATEGORY_IDS", "14740, 14479")
    assert crawler.configured_category_ids() == (14740, 14479)
    monkeypatch.delenv("AUCHAN_CATEGORY_IDS")
    assert crawler.configured_category_ids() == crawler.DEFAULT_CATEGORY_IDS


def test_details_fetch_is_bounded_and_best_effort(monkeypatch):
    pending = [{"_id": "1", "variant_id": 10}, {"_id": "2", "variant_id": None}, {"_id": "3", "variant_id": 30}]
    saved, failed = {}, {}
    monkeypatch.setattr(repository, "products_needing_details", lambda limit: pending[:limit])
    monkeypatch.setattr(repository, "save_details", lambda pid, text: saved.__setitem__(pid, text))
    monkeypatch.setattr(repository, "mark_details_failed", lambda pid, reason: failed.__setitem__(pid, reason))

    class Client:
        def product_details(self, product_id, variant_id):
            if product_id == "3":
                raise AuchanUnavailable("HTTP 503")
            return [{"sectionType": "description", "description": "Leírás"}]

    counts = crawler.fetch_missing_details(Client(), limit=3)
    assert counts == {"fetched": 1, "failed": 1}
    assert saved == {"1": {"description": "Leírás"}}
    assert failed == {"2": "no variant id"}
    assert crawler.fetch_missing_details(Client(), limit=0) == {"fetched": 0, "failed": 0}
