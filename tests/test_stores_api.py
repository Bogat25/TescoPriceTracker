"""Store-neutral API routes and the Tesco switch for legacy endpoints."""

import importlib.util
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stores import offers
from stores.registry import StoreRegistry


ROUTER_FILE = Path(__file__).resolve().parents[1] / "backend-api" / "routers" / "stores_api.py"
SPEC = importlib.util.spec_from_file_location("backend_stores_api", ROUTER_FILE)
stores_api = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(stores_api)


class Collection:
    def __init__(self, docs):
        self.docs = {doc["_id"]: doc for doc in docs}

    def find(self, _query):
        return list(self.docs.values())

    def update_one(self, *_args, **_kwargs):
        pass


def make_offer(store, product_id, name):
    return offers.build_offer(store_id=store, store_product_id=product_id, name=name,
                              price_set=offers.prices(regular=100))


class Queries:
    ADAPTERS = {"tesco": object(), "auchan": object()}
    WindowTooLarge = stores_api.queries.WindowTooLarge

    def __init__(self):
        self.calls = []
        self.offers = {"tesco:1": make_offer("tesco", "1", "Tej"), "auchan:2": make_offer("auchan", "2", "Túró")}

    def search(self, store_ids, q, skip, limit):
        self.calls.append(("search", store_ids, q, skip, limit))
        if skip + limit > 1000:
            raise self.WindowTooLarge("too deep")
        return {"results": [], "total": 0, "skip": skip, "limit": limit, "stores": store_ids}

    def browse(self, store_ids, skip, limit, sort_by, sort_dir):
        self.calls.append(("browse", store_ids, skip, limit, sort_by, sort_dir))
        return {"results": [], "total": 0, "skip": skip, "limit": limit, "stores": store_ids}

    def get_offer(self, ref):
        return self.offers.get(ref)

    def get_history(self, ref):
        return [] if ref in self.offers else None


@pytest.fixture
def api(monkeypatch):
    def build(stored_switches=()):
        registry = StoreRegistry(lambda: Collection(list(stored_switches)))
        fake_queries = Queries()
        monkeypatch.setattr(stores_api, "registry", registry)
        monkeypatch.setattr(stores_api, "queries", fake_queries)
        app = FastAPI()
        app.include_router(stores_api.router)
        app.middleware("http")(stores_api.tesco_switch_middleware())

        @app.get("/api/v1/products/search")
        def legacy_search():
            return {"legacy": True}

        @app.get("/{tpnc}.json")
        def legacy_json(tpnc: str):
            return {"tpnc": tpnc}

        return TestClient(app), fake_queries
    return build


def test_stores_lists_only_enabled_stores(api):
    client, _ = api([{"_id": "tesco", "enabled": False}])
    body = client.get("/api/v1/stores").json()
    assert [store["id"] for store in body["stores"]] == ["auchan"]
    assert set(body["stores"][0]) == {"id", "name", "order", "website"}


def test_search_defaults_to_all_enabled_stores(api):
    client, fake = api()
    assert client.get("/api/v1/search", params={"q": " tej "}).status_code == 200
    assert fake.calls == [("search", ["tesco", "auchan"], "tej", 0, 50)]


def test_search_rejects_unknown_and_disabled_stores(api):
    client, _ = api([{"_id": "auchan", "enabled": False}])
    assert client.get("/api/v1/search", params={"q": "tej", "stores": "lidl"}).status_code == 400
    assert client.get("/api/v1/search", params={"q": "tej", "stores": "auchan"}).status_code == 404
    assert client.get("/api/v1/search", params={"q": ""}).status_code == 422
    assert client.get("/api/v1/search", params={"q": "tej", "skip": 990, "limit": 20}).status_code == 400


def test_browse_validates_sort(api):
    client, fake = api()
    assert client.get("/api/v1/browse", params={"stores": "auchan", "sort_by": "price", "sort_dir": "desc"}).status_code == 200
    assert fake.calls[-1] == ("browse", ["auchan"], 0, 50, "price", "desc")
    assert client.get("/api/v1/browse", params={"sort_by": "rating"}).status_code == 422


def test_offer_and_history(api):
    client, _ = api()
    assert client.get("/api/v1/offers/auchan:2").json()["name"] == "Túró"
    assert client.get("/api/v1/offers/auchan:2/history").json() == {"ref": "auchan:2", "history": []}
    assert client.get("/api/v1/offers/auchan:404").status_code == 404
    assert client.get("/api/v1/offers/not-a-ref").status_code == 400


def test_offer_of_disabled_store_is_not_found(api):
    client, _ = api([{"_id": "auchan", "enabled": False}])
    assert client.get("/api/v1/offers/auchan:2").status_code == 404
    assert client.get("/api/v1/offers/auchan:2/history").status_code == 404


def test_legacy_tesco_endpoints_follow_the_tesco_switch(api):
    client, _ = api()
    assert client.get("/api/v1/products/search").status_code == 200
    assert client.get("/123.json").status_code == 200

    client, _ = api([{"_id": "tesco", "enabled": False}])
    assert client.get("/api/v1/products/search").status_code == 404
    assert client.get("/123.json").status_code == 404
    # Store-neutral routes and the OpenAPI document stay available.
    assert client.get("/api/v1/stores").status_code == 200
    assert client.get("/openapi.json").status_code == 200
