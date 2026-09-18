"""Recommendation rows per store selection, and alert targets feeding the Tesco engine."""

import importlib.util
from pathlib import Path

from stores import offers, queries, recommendations, tesco


REPO_ROOT = Path(__file__).resolve().parent.parent


def offer(store, product_id, name, regular, promo=None, gtin=None):
    return offers.build_offer(store_id=store, store_product_id=product_id, name=name, gtin=gtin,
                              price_set=offers.prices(regular=regular, promo=promo))


TESCO = [offer("tesco", "1", "Tej", 400, gtin="5990000000011"), offer("tesco", "2", "Kenyér", 600)]
AUCHAN = [offer("auchan", "a1", "Tej", 380, gtin="5990000000011"), offer("auchan", "a2", "Sajt", 1000, promo=500)]


class Adapter:
    def __init__(self, catalogue):
        self.catalogue = catalogue

    def find_by_gtins(self, gtins):
        return [o for o in self.catalogue if o["gtin"] in gtins]

    def browse(self, limit, sort_by, sort_dir, category_query=None):
        return {"results": self.catalogue[:limit], "total": len(self.catalogue)}


def install(monkeypatch):
    monkeypatch.setattr(queries, "ADAPTERS", {"tesco": Adapter(TESCO), "auchan": Adapter(AUCHAN)})
    by_id = {o["store_product_id"]: o for o in TESCO}
    monkeypatch.setattr(tesco, "find_by_ids", lambda ids: [by_id[i] for i in ids if i in by_id])


def personalized(*tpncs):
    return lambda: {"type": "personalized", "personalized_count": len(tpncs),
                    "recommendations": [{"tpnc": tpnc} for tpnc in tpncs]}


def test_personal_picks_come_first_with_every_selected_store(monkeypatch):
    install(monkeypatch)
    result = recommendations.rows(["tesco", "auchan"], 3, personalized("1"))

    assert result["type"] == "personalized" and result["personalized_count"] == 1
    first = result["results"][0]
    assert [o["ref"] for o in first["offers"]] == ["auchan:a1", "tesco:1"]
    # Filler rows skip the product already picked.
    refs = [row["offers"][0]["ref"] for row in result["results"]]
    assert len(refs) == 3 and refs.count("auchan:a1") == 1


def test_picks_show_only_the_selected_stores(monkeypatch):
    install(monkeypatch)
    result = recommendations.rows(["auchan"], 5, personalized("1", "2"))

    # Kenyér has no Auchan listing, so it is left out; Tej shows the Auchan price only.
    assert result["personalized_count"] == 1
    assert [o["ref"] for o in result["results"][0]["offers"]] == ["auchan:a1"]
    assert all(o["store"] == "auchan" for row in result["results"] for o in row["offers"])


def test_cold_start_is_the_discount_listing(monkeypatch):
    install(monkeypatch)
    cold = recommendations.rows(["auchan"], 5)
    fallback = recommendations.rows(["auchan"], 5, lambda: {"type": "cold_start", "recommendations": []})

    assert cold["type"] == fallback["type"] == "cold_start"
    assert cold["results"][0]["offers"][0]["ref"] == "auchan:a2"
    assert cold["results"] == fallback["results"]


def _engine():
    spec = importlib.util.spec_from_file_location("backend_recommendation_engine", REPO_ROOT / "backend-api" / "recommendation_engine.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Collection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query, _projection=None):
        wanted = query["gtin_norm"]["$in"]
        return [doc for doc in self.docs if doc["gtin_norm"] in wanted]

    def find_one(self, query, _projection=None):
        return next((doc for doc in self.docs if doc["_id"] == query["_id"]), None)


def test_alert_targets_map_to_tesco_products():
    engine = _engine()
    tesco_products = Collection([{"_id": "111", "gtin_norm": "5990000000011"}])
    auchan_products = Collection([{"_id": "a1", "gtin_norm": "5990000000011"}, {"_id": "a9", "gtin_norm": "4000000000009"}])
    alerts = [
        {"productId": "900", "createdAt": 1},                               # legacy alert
        {"productId": "901", "target": "tesco:901", "createdAt": 2},
        {"productId": "g:5990000000011", "target": "g:5990000000011", "createdAt": 3},
        {"productId": "auchan:a1", "target": "auchan:a1", "createdAt": 4},
        {"productId": "auchan:a9", "target": "auchan:a9", "createdAt": 5},  # not sold at Tesco
    ]

    resolved = engine.resolve_alert_products(alerts, tesco_products, auchan_products)

    assert sorted((a["productId"], a["createdAt"]) for a in resolved) == [("111", 3), ("111", 4), ("900", 1), ("901", 2)]
