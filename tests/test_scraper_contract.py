from unittest.mock import Mock

import pytest

from mongo.queries import FULL_PRODUCT_QUERY
from scraper import scraper


class FakeResponse:
    def __init__(self, status_code, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        # A real requests.Response always exposes headers; the retry path reads
        # Retry-After from them, so the stub has to model that too.
        self.headers = headers or {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise scraper.requests.HTTPError(str(self.status_code))


def test_full_query_uses_current_tesco_contract_fields():
    assert "nutrition {\n        name\n        value1" in FULL_PRODUCT_QUERY
    assert "gda {\n        name\n        value" in FULL_PRODUCT_QUERY
    assert "icons {\n      id\n      caption\n      url" in FULL_PRODUCT_QUERY
    assert "ratingsDistribution {\n          name\n          value" in FULL_PRODUCT_QUERY
    assert "... on ProductType {\n      maxQuantityAllowed" in FULL_PRODUCT_QUERY
    for removed in ("tableType", "imageUrl", "valuePer100", "ratingsDistribution {\n          one"):
        assert removed not in FULL_PRODUCT_QUERY


def test_graphql_400_is_fatal_and_not_retried(monkeypatch):
    post = Mock(return_value=FakeResponse(400, [{"errors": [{"message": "bad field"}]}]))
    monkeypatch.setattr(scraper.requests, "post", post)

    with pytest.raises(scraper.GraphQLContractError):
        scraper.get_product_api("123", "full")

    assert post.call_count == 1


def test_retryable_500_is_retried(monkeypatch):
    post = Mock(side_effect=[
        FakeResponse(500, {}),
        FakeResponse(200, [{"data": {"product": {"id": "123"}}}]),
    ])
    monkeypatch.setattr(scraper.requests, "post", post)
    monkeypatch.setattr(scraper.time, "sleep", lambda _: None)
    monkeypatch.setattr(scraper.random, "uniform", lambda *_: 0)

    result = scraper.get_product_api("123", "full")

    assert result["data"]["product"]["id"] == "123"
    assert post.call_count == 2


def test_rate_limit_waits_at_least_the_servers_retry_after(monkeypatch):
    """A 429 must back off for as long as Tesco asked.

    The generic 2/4/8/16s ladder is shorter than a typical penalty window, so
    ignoring Retry-After burned all five attempts before the limit cleared.
    """
    slept = []
    post = Mock(side_effect=[
        FakeResponse(429, {}, headers={"Retry-After": "45"}),
        FakeResponse(200, [{"data": {"product": {"id": "123"}}}]),
    ])
    monkeypatch.setattr(scraper.requests, "post", post)
    monkeypatch.setattr(scraper.time, "sleep", slept.append)
    monkeypatch.setattr(scraper.random, "uniform", lambda *_: 0)

    result = scraper.get_product_api("123", "full")

    assert result["data"]["product"]["id"] == "123"
    assert slept and slept[0] >= 45


def test_retry_after_is_capped(monkeypatch):
    """One hostile Retry-After must not stall the whole run."""
    slept = []
    post = Mock(side_effect=[
        FakeResponse(429, {}, headers={"Retry-After": "99999"}),
        FakeResponse(200, [{"data": {"product": {"id": "123"}}}]),
    ])
    monkeypatch.setattr(scraper.requests, "post", post)
    monkeypatch.setattr(scraper.time, "sleep", slept.append)
    monkeypatch.setattr(scraper.random, "uniform", lambda *_: 0)

    scraper.get_product_api("123", "full")

    assert slept[0] == scraper.RETRY_AFTER_CAP_SECONDS


def test_backoff_still_grows_without_a_retry_after_header(monkeypatch):
    """Missing header keeps the exponential ladder rather than a flat wait."""
    slept = []
    post = Mock(side_effect=[
        FakeResponse(500, {}),
        FakeResponse(500, {}),
        FakeResponse(200, [{"data": {"product": {"id": "123"}}}]),
    ])
    monkeypatch.setattr(scraper.requests, "post", post)
    monkeypatch.setattr(scraper.time, "sleep", slept.append)
    monkeypatch.setattr(scraper.random, "uniform", lambda *_: 0)

    scraper.get_product_api("123", "full")

    assert slept == [2, 4]


def test_current_object_shapes_are_normalized_for_the_frontend():
    assert scraper._manufacturer_text({"addresses": ["Company", "Budapest"]}) == "Company, Budapest"
    assert scraper._allergens_text([
        {"name": "Contains", "values": ["Milk", "Soy"]},
        {"name": "May contain", "values": ["Nuts"]},
    ]) == "Contains: Milk, Soy; May contain: Nuts"


def test_contract_preflight_aborts_and_persists_failure(monkeypatch):
    saved = []
    monkeypatch.setattr(scraper.db, "init_db", lambda: None)
    monkeypatch.setattr(scraper.db, "product_exists", lambda _: False)
    monkeypatch.setattr(scraper.db, "save_run_state", lambda state: saved.append(dict(state)))
    monkeypatch.setattr(
        scraper,
        "get_product_api",
        Mock(side_effect=scraper.GraphQLContractError("schema drift")),
    )

    with pytest.raises(scraper.GraphQLContractError):
        scraper.run_scraper(specific_items=["123"], threads=1)

    assert saved[-1]["completed"] is False
    assert saved[-1]["failed_count"] == 1
    assert saved[-1]["failure_reason"] == "schema drift"


def test_unavailable_products_are_classified_without_completing_with_failures(monkeypatch):
    saved = []
    monkeypatch.setattr(scraper.db, "init_db", lambda: None)
    monkeypatch.setattr(scraper.db, "product_exists", lambda _: False)
    monkeypatch.setattr(scraper.db, "save_run_state", lambda state: saved.append(dict(state)))
    monkeypatch.setattr(scraper, "get_product_api", lambda *_: {"data": {"product": {"id": "probe"}}})
    monkeypatch.setattr(scraper, "process_product", lambda *_args, **_kwargs: scraper.ProductResult.UNAVAILABLE)
    monkeypatch.setattr(scraper.stats_manager, "rebuild_all_cache", lambda: None)
    monkeypatch.setattr(scraper, "_notify_alert_service", lambda: None)

    state = scraper.run_scraper(specific_items=["123", "456"], threads=1)

    assert state["completed"] is True
    assert state["processed_count"] == 2
    assert state["failed_count"] == 0
    assert state["status_counts"]["unavailable"] == 2
