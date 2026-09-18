"""Integration fixtures: a real MongoDB, seeded with two stores' catalogues.

These tests run against live services instead of fakes, so they cover what unit
tests cannot: the Mongo queries themselves, the text and category indexes, the
barcode linking across two collections and the API on top of all of it.

They are skipped when MongoDB is not reachable, which keeps ``pytest`` on a
laptop the same eleven seconds it always was. CI starts the services (see
``.github/workflows/ci.yml``) and then they run for real.

The data always goes to its own database, never to the one the application is
configured with, so pointing ``MONGO_URI`` at a real server cannot damage it.
"""

import importlib.util
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo import MongoClient
from pymongo import errors as mongo_errors

from config import MONGO_URI
from mongo import database_manager as db
from stores import categories
from stores.auchan import repository as auchan_repository
from stores.registry import registry


TEST_DATABASE = "tesco_tracker_integration"
CONNECT_TIMEOUT_MS = 3000

ROUTER_FILE = Path(__file__).resolve().parents[2] / "backend-api" / "routers" / "stores_api.py"


def _load_router():
    spec = importlib.util.spec_from_file_location("backend_stores_api_integration", ROUTER_FILE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def mongo_client():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=CONNECT_TIMEOUT_MS)
    try:
        client.admin.command("ping")
    except mongo_errors.PyMongoError as exc:
        pytest.skip(f"MongoDB is not reachable at {MONGO_URI}: {exc}")
    yield client
    client.drop_database(TEST_DATABASE)
    client.close()


@pytest.fixture
def database(mongo_client, monkeypatch):
    """A clean database, wired into the modules that reach for one."""
    mongo_client.drop_database(TEST_DATABASE)
    database = mongo_client[TEST_DATABASE]
    monkeypatch.setattr(db, "_client", mongo_client)
    monkeypatch.setattr(db, "_db", database)
    monkeypatch.setattr(db, "_collection", database["products"])
    registry.invalidate()
    categories.invalidate()
    yield database
    registry.invalidate()
    categories.invalidate()
    mongo_client.drop_database(TEST_DATABASE)


def tesco_product(product_id, name, gtin, super_department, department, price, promo=None, loyalty=None):
    """A Tesco document in its stored shape; the backfills add the derived fields."""
    return {
        "_id": product_id,
        "tpnc": product_id,
        "name": name,
        "gtin": gtin,
        "brand_name": "Teszt",
        "default_image_url": f"https://img/{product_id}.jpg",
        "super_department_name": super_department,
        "department_name": department,
        "aisle_name": None,
        "shelf_name": None,
        "pack_size_value": "1",
        "pack_size_unit": "l",
        "is_for_sale": True,
        "last_scraped_price": "2026-09-17T05:12:00",
        "price_history": [
            {"date": "2026-09-16", "normal": {"price": price}, "discount": None, "clubcard": None},
            {"date": "2026-09-17", "normal": {"price": price},
             "discount": {"price": promo} if promo else None,
             "clubcard": {"price": loyalty} if loyalty else None},
        ],
    }


def auchan_product(product_id, name, ean, category_path, price, promo=None):
    from stores.auchan import repository
    from stores.ids import normalize_gtin

    current = {"date": "2026-09-17", "regular": float(price),
               "promo": float(promo) if promo else None, "loyalty": None,
               "unit_price": None, "unit": None}
    return {
        "_id": product_id,
        "name": name,
        "brand": "Teszt",
        "ean": ean,
        "gtin_norm": normalize_gtin(ean),
        "category_path": list(category_path),
        "pack_size": 1.0,
        "pack_unit": "l",
        "is_loose": False,
        "availability": "available",
        "image_url": f"https://img/a{product_id}.jpg",
        "url": f"https://auchan.hu/shop/x.p-{product_id}",
        "flags": [],
        "current": current,
        "browse_sort": repository.browse_sort_fields(current),
        "price_history": [dict(current, availability="available")],
    }


# Three dairy products sold by both stores give the category mapping the
# agreement it needs; the single linked drink deliberately stays below it.
TESCO_PRODUCTS = [
    tesco_product("100", "Teszt tej 1,5% 1 l", "05998200557001", "Alapvető élelmiszerek", "Tejtermékek", 399),
    tesco_product("101", "Teszt tej 2,8% 1 l", "05998200557002", "Alapvető élelmiszerek", "Tejtermékek", 459, promo=419),
    tesco_product("102", "Teszt kefir 1 l", "05998200557003", "Alapvető élelmiszerek", "Tejtermékek", 529),
    tesco_product("103", "Teszt vaj 200 g", "05998200557006", "Alapvető élelmiszerek", "Tejtermékek", 999),
    tesco_product("104", "Teszt kóla 500 ml", "05998200557004", "Italok", "Üdítők", 349),
    tesco_product("105", "Teszt ásványvíz 1,5 l", "05998200557005", "Italok", "Üdítők", 199),
]

AUCHAN_PRODUCTS = [
    auchan_product("200", "Teszt tej 1,5% 1 l", "5998200557001", ("Élelmiszer", "Tej, tojás", "Tej"), 379),
    auchan_product("201", "Teszt tej 2,8% 1 l", "5998200557002", ("Élelmiszer", "Tej, tojás", "Tej"), 479),
    auchan_product("202", "Teszt kefir 1 l", "5998200557003", ("Élelmiszer", "Tej, tojás", "Tej"), 529),
    auchan_product("203", "Teszt tejföl 330 g", "5998200557007", ("Élelmiszer", "Tej, tojás", "Tej"), 449),
    auchan_product("204", "Teszt kóla 500 ml", "5998200557004", ("Ital", "Üdítő"), 359),
]


@pytest.fixture
def catalogue(database):
    """Both stores seeded, indexed and linked, exactly as a scrape would leave them."""
    database["products"].insert_many(TESCO_PRODUCTS)
    database["auchan_products"].insert_many(AUCHAN_PRODUCTS)
    db.init_db()                      # indexes, browse_sort and gtin_norm backfills
    auchan_repository.ensure_indexes()
    registry.seed()
    return database


@pytest.fixture
def api(catalogue):
    """The store-neutral router over the seeded catalogue."""
    stores_api = _load_router()
    app = FastAPI()
    app.include_router(stores_api.router)
    app.middleware("http")(stores_api.tesco_switch_middleware())
    with TestClient(app) as client:
        yield client
