"""Store-aware alerts: targets, watched stores, evaluation and migration."""

import asyncio
import sys
import types
from pathlib import Path

import pytest

ALERT_SERVICE = Path(__file__).resolve().parents[1] / "alert-service"
sys.path.insert(0, str(ALERT_SERVICE))

import targets  # noqa: E402

# evaluator is a pure module; import it without the service package stubs
# other tests install.
_spec_path = ALERT_SERVICE / "services" / "evaluator.py"
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("alert_evaluator_under_test", _spec_path)
evaluator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(evaluator)


@pytest.mark.parametrize("value, expected", [
    ("121262922", ("tesco:121262922", "121262922")),        # extension / old clients
    ("tesco:121262922", ("tesco:121262922", "121262922")),  # productId stays the tpnc
    ("auchan:678170", ("auchan:678170", "auchan:678170")),
    ("g:54026193", ("g:54026193", "g:54026193")),
])
def test_normalize_targets(value, expected):
    assert targets.normalize(value) == expected


@pytest.mark.parametrize("value", ["", "g:0054026193", "g:2802590000000", "lidl:1", "Auchan:1", "auchan:"])
def test_invalid_targets(value):
    with pytest.raises(targets.InvalidTarget):
        targets.normalize(value)


def test_watched_stores():
    enabled = {"tesco", "auchan"}
    assert targets.resolve_stores("auchan:1", ["tesco"], enabled) == ["auchan"]
    assert targets.resolve_stores("g:54026193", None, enabled) == ["tesco", "auchan"]
    assert targets.resolve_stores("g:54026193", None, {"auchan"}) == ["auchan"]
    assert targets.resolve_stores("g:54026193", ["Auchan", " tesco "], enabled) == ["tesco", "auchan"]
    with pytest.raises(targets.InvalidTarget):
        targets.resolve_stores("g:54026193", ["lidl"], enabled)
    with pytest.raises(targets.InvalidTarget):
        targets.resolve_stores("g:54026193", [], enabled)


def alert(target, stores, **kwargs):
    base = {"userId": "u1", "productId": target, "target": target, "stores": stores, "alertType": "TARGET_PRICE", "targetPrice": 300.0}
    return {**base, **kwargs}


def drop(ref, store, new, old=None, group=None):
    return {"ref": ref, "store": store, "groupId": group, "newPrice": new, "oldPrice": old, "productName": "Tej"}


def test_group_alert_fires_for_each_watched_store():
    drops = [
        drop("tesco:1", "tesco", 290.0, 400.0, "g:5998200557699"),
        drop("auchan:2", "auchan", 280.0, 350.0, "g:5998200557699"),
    ]
    triggered = evaluator.evaluate([alert("g:5998200557699", ["tesco", "auchan"])], drops, {"tesco", "auchan"})
    assert [(t["store"], t["productId"]) for t in triggered] == [("tesco", "tesco:1"), ("auchan", "auchan:2")]
    assert triggered[0]["target"] == "g:5998200557699"


def test_unwatched_or_disabled_stores_do_not_fire():
    drops = [drop("tesco:1", "tesco", 290.0, group="g:5998200557699"), drop("auchan:2", "auchan", 280.0, group="g:5998200557699")]
    only_auchan = evaluator.evaluate([alert("g:5998200557699", ["auchan"])], drops, {"tesco", "auchan"})
    assert [t["store"] for t in only_auchan] == ["auchan"]
    auchan_off = evaluator.evaluate([alert("g:5998200557699", ["tesco", "auchan"])], drops, {"tesco"})
    assert [t["store"] for t in auchan_off] == ["tesco"]


def test_offer_alerts_match_their_listing_and_old_alerts_still_work():
    drops = [drop("tesco:1", "tesco", 250.0, 400.0, "g:5998200557699")]
    legacy = {"userId": "u1", "productId": "1", "alertType": "PERCENTAGE_DROP", "dropPercentage": 20.0, "basePriceAtCreation": 400.0}
    assert len(evaluator.evaluate([legacy], drops, {"tesco"})) == 1
    assert evaluator.evaluate([alert("tesco:1", ["tesco"], targetPrice=200.0)], drops, {"tesco"}) == []
    assert evaluator.evaluate([alert("auchan:9", ["auchan"])], drops, {"tesco", "auchan"}) == []


class AsyncAlerts:
    def __init__(self, docs):
        self.docs = docs
        self.calls = []

    async def update_many(self, query, pipeline):
        self.calls.append((query, pipeline))
        changed = 0
        for doc in self.docs:
            if "target" not in doc:
                doc["target"] = f"tesco:{doc['productId']}"
                doc["stores"] = ["tesco"]
                changed += 1
        return types.SimpleNamespace(modified_count=changed)


def test_legacy_alert_migration_is_idempotent(monkeypatch):
    for name in ("motor", "motor.motor_asyncio"):
        module = types.ModuleType(name)
        module.AsyncIOMotorClient = object
        module.AsyncIOMotorDatabase = object
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("alert_db_under_test", ALERT_SERVICE / "db.py")
    alert_db = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(alert_db)

    alerts = AsyncAlerts([{"productId": "121262922"}, {"productId": "g:1", "target": "g:5998200557699", "stores": ["auchan"]}])
    assert asyncio.run(alert_db.migrate_legacy_alerts(alerts)) == 1
    assert asyncio.run(alert_db.migrate_legacy_alerts(alerts)) == 0
    assert alerts.docs[0] == {"productId": "121262922", "target": "tesco:121262922", "stores": ["tesco"]}
    query, pipeline = alerts.calls[0]
    assert query == {"target": {"$exists": False}}
    assert pipeline[0]["$set"]["stores"] == ["tesco"]
