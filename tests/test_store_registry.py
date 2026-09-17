"""Store identifiers and the store registry (switches, caching, request parsing)."""

import pytest
from pymongo import errors as mongo_errors

from stores.ids import InvalidReference, is_restricted_circulation, make_ref, normalize_gtin, parse_ref
from stores.registry import DEFAULT_STORES, DisabledStore, StoreRegistry, UnknownStore


class FakeCollection:
    def __init__(self, docs=None, fail=False):
        self.docs = {doc["_id"]: dict(doc) for doc in (docs or [])}
        self.fail = fail
        self.find_calls = 0

    def find(self, _query):
        self.find_calls += 1
        if self.fail:
            raise mongo_errors.ServerSelectionTimeoutError("down")
        return [dict(doc) for doc in self.docs.values()]

    def update_one(self, query, update, upsert=False):
        doc = self.docs.get(query["_id"])
        if doc is None:
            if not upsert:
                return
            doc = {"_id": query["_id"], **update.get("$setOnInsert", {})}
            self.docs[query["_id"]] = doc
        doc.update(update.get("$set", {}))


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make_registry(collection, clock=None):
    return StoreRegistry(lambda: collection, ttl_seconds=60, clock=clock or Clock())


# -- identifiers ------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("00000054026193", "54026193"),       # Tesco GTIN-14
    ("54026193", "54026193"),             # Auchan EAN-8
    ("5998200485596", "5998200485596"),
    (5998200485596, "5998200485596"),
    (" 05999566110184 ", "5999566110184"),
    (None, None),
    ("", None),
    ("000012", None),                     # too short to be a barcode
])
def test_normalize_gtin(raw, expected):
    assert normalize_gtin(raw) == expected


def test_in_store_codes_are_restricted():
    assert is_restricted_circulation("2802590000000")
    assert not is_restricted_circulation("5998200485596")
    assert not is_restricted_circulation("54026193")
    assert not is_restricted_circulation(None)


def test_refs_round_trip_and_reject_garbage():
    assert parse_ref(make_ref("auchan", "678170")) == ("auchan", "678170")
    assert parse_ref("tesco:12:3") == ("tesco", "12:3")
    for bad in ("", "tesco", "tesco:", ":123", "Tesco:1", "x:1"):
        with pytest.raises(InvalidReference):
            parse_ref(bad)


# -- registry ---------------------------------------------------------------------

def test_defaults_apply_when_nothing_is_stored():
    registry = make_registry(FakeCollection())
    assert [store.id for store in registry.enabled()] == ["tesco", "auchan"]
    assert registry.scrape_enabled("auchan")
    assert not registry.loyalty_enabled("auchan")


def test_seed_does_not_overwrite_existing_switches():
    collection = FakeCollection([{"_id": "auchan", "enabled": False}])
    registry = make_registry(collection)
    registry.seed()
    assert collection.docs["auchan"]["enabled"] is False
    assert collection.docs["tesco"]["enabled"] is True
    assert not registry.is_enabled("auchan")


def test_reads_are_cached_until_the_ttl_expires():
    clock = Clock()
    collection = FakeCollection([{"_id": "auchan", "enabled": True}])
    registry = make_registry(collection, clock)
    assert registry.is_enabled("auchan")
    collection.docs["auchan"]["enabled"] = False
    clock.now = 59
    assert registry.is_enabled("auchan")
    clock.now = 60
    assert not registry.is_enabled("auchan")
    assert collection.find_calls == 2


def test_set_flags_takes_effect_immediately_and_validates():
    collection = FakeCollection()
    registry = make_registry(collection)
    registry.all()
    assert registry.set_flags("tesco", enabled=False).enabled is False
    assert [store.id for store in registry.enabled()] == ["auchan"]
    with pytest.raises(UnknownStore):
        registry.set_flags("lidl", enabled=False)
    with pytest.raises(ValueError):
        registry.set_flags("tesco", name="Other")
    with pytest.raises(ValueError):
        registry.set_flags("tesco", enabled="no")


def test_unavailable_database_falls_back_to_defaults():
    registry = make_registry(FakeCollection(fail=True))
    assert [store.id for store in registry.all()] == [store.id for store in DEFAULT_STORES]


def test_resolve_stores_parameter():
    collection = FakeCollection([{"_id": "tesco", "enabled": False}])
    registry = make_registry(collection)

    assert registry.resolve("") == ["auchan"]
    assert registry.resolve(None) == ["auchan"]
    assert registry.resolve(" Auchan , auchan ") == ["auchan"]
    with pytest.raises(DisabledStore):
        registry.resolve("tesco")
    with pytest.raises(UnknownStore):
        registry.resolve("lidl")
    with pytest.raises(UnknownStore):
        registry.resolve("../etc")


def test_resolve_keeps_registry_order_not_request_order():
    registry = make_registry(FakeCollection())
    assert registry.resolve("auchan,tesco") == ["tesco", "auchan"]


def test_order_and_names_can_be_overridden_but_unknown_documents_are_ignored():
    collection = FakeCollection([
        {"_id": "auchan", "order": 1},
        {"_id": "spar", "enabled": True},
    ])
    registry = make_registry(collection)
    assert [store.id for store in registry.all()] == ["auchan", "tesco"]
