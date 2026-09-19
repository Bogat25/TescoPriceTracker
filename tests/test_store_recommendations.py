"""Recommendation rows: personal picks across every selected store, then discounts."""

import importlib.util
from pathlib import Path

import pytest

from stores import categories, offers, queries, recommendations, semantic
from stores.categories import Mapping


REPO_ROOT = Path(__file__).resolve().parent.parent

DAIRY = "alapveto-elelmiszerek/tejtermekek"
DRINKS = "italok/uditok"
TESCO_DAIRY = ["Alapvető élelmiszerek", "Tejtermékek"]
TESCO_DRINKS = ["Italok", "Üdítők"]
AUCHAN_DAIRY = ["Élelmiszer", "Tej, tojás"]
AUCHAN_DRINKS = ["Ital", "Üdítő"]

MAPPING = Mapping(
    categories={
        DAIRY: {"names": TESCO_DAIRY, "counts": {"tesco": 3, "auchan": 3}},
        DRINKS: {"names": TESCO_DRINKS, "counts": {"tesco": 1, "auchan": 1}},
    },
    paths_by_store={"auchan": {tuple(AUCHAN_DAIRY): DAIRY, tuple(AUCHAN_DRINKS): DRINKS}},
)


def offer(store, product_id, name, regular, category_path, promo=None, gtin=None):
    return offers.build_offer(store_id=store, store_product_id=product_id, name=name, gtin=gtin,
                              category_path=category_path,
                              price_set=offers.prices(regular=regular, promo=promo))


# Tej and Sajt are sold by both stores; Joghurt only by Auchan, Kenyér only by Tesco.
TESCO = [
    offer("tesco", "1", "Tej", 400, TESCO_DAIRY, gtin="5990000000011"),
    offer("tesco", "2", "Sajt", 1000, TESCO_DAIRY, gtin="5990000000022"),
    offer("tesco", "3", "Kenyér", 600, TESCO_DAIRY),
    offer("tesco", "4", "Kóla", 500, TESCO_DRINKS, promo=250, gtin="5990000000044"),
]
AUCHAN = [
    offer("auchan", "a1", "Tej", 380, AUCHAN_DAIRY, gtin="5990000000011"),
    offer("auchan", "a2", "Sajt", 900, AUCHAN_DAIRY, gtin="5990000000022"),
    offer("auchan", "a3", "Joghurt", 300, AUCHAN_DAIRY, promo=150, gtin="5990000000033"),
    offer("auchan", "a4", "Kóla", 520, AUCHAN_DRINKS, gtin="5990000000044"),
]


class Adapter:
    def __init__(self, catalogue):
        self.catalogue = catalogue

    def find_by_ids(self, ids):
        by_id = {o["store_product_id"]: o for o in self.catalogue}
        return [by_id[str(i)] for i in ids if str(i) in by_id]

    def find_by_gtins(self, gtins):
        return [o for o in self.catalogue if o["gtin"] in gtins]

    def browse(self, limit, sort_by, sort_dir, category_query=None):
        ordered = sorted(self.catalogue, key=lambda o: -(o["discount_ratio"] or 0))
        return {"results": ordered[:limit], "total": len(ordered)}


class FakeSemantic:
    """Returns the hits it was given, in order, as if Qdrant had ranked them."""

    SemanticUnavailable = semantic.SemanticUnavailable

    def __init__(self, hits, missing_vectors=False, unavailable=False):
        self.hits = hits
        self.missing_vectors = missing_vectors
        self.unavailable = unavailable
        self.searched_stores = None

    def vectors_for(self, refs):
        if self.unavailable:
            raise semantic.SemanticUnavailable("qdrant down")
        return {} if self.missing_vectors else {ref: [0.1, 0.2] for ref in refs}

    def mean_vector(self, vectors):
        return [0.1, 0.2]

    def nearest(self, vector, store_ids, limit, **_):
        self.searched_stores = list(store_ids)
        return [(ref, score) for ref, score in self.hits if ref.split(":")[0] in store_ids][:limit]


@pytest.fixture
def catalogue(monkeypatch):
    monkeypatch.setattr(queries, "ADAPTERS", {"tesco": Adapter(TESCO), "auchan": Adapter(AUCHAN)})
    monkeypatch.setattr(categories, "mapping", lambda: MAPPING)

    def use(hits, **kwargs):
        fake = FakeSemantic(hits, **kwargs)
        monkeypatch.setattr(recommendations, "semantic", fake)
        return fake
    return use


def alert(target, created_at):
    return {"target": target, "productId": target, "createdAt": created_at}


def refs_of(row):
    return [o["ref"] for o in row["offers"]]


# -- picks now come from every store ------------------------------------------------

def test_a_product_only_the_other_store_sells_can_be_recommended(catalogue):
    """The point of the change: picks are no longer limited to one store's catalogue."""
    catalogue([("auchan:a3", 0.9)])
    result = recommendations.rows(["tesco", "auchan"], 3, [alert("tesco:1", 1)])

    assert result["type"] == "personalized"
    assert refs_of(result["results"][0]) == ["auchan:a3"]


def test_a_product_both_stores_sell_is_one_pick_with_both_prices(catalogue):
    catalogue([("tesco:2", 0.9)])
    result = recommendations.rows(["tesco", "auchan"], 5, [alert("tesco:1", 1)])

    assert result["personalized_count"] == 1
    assert refs_of(result["results"][0]) == ["auchan:a2", "tesco:2"]   # cheapest first


def test_the_vector_search_covers_every_selected_store(catalogue):
    fake = catalogue([("tesco:2", 0.9)])
    recommendations.rows(["tesco", "auchan"], 5, [alert("tesco:1", 1)])
    assert fake.searched_stores == ["tesco", "auchan"]


def test_picks_still_work_when_tesco_is_not_selected(catalogue):
    """Previously the personal path was skipped entirely without Tesco."""
    catalogue([("auchan:a3", 0.9)])
    result = recommendations.rows(["auchan"], 3, [alert("auchan:a1", 1)])

    assert result["type"] == "personalized"
    assert refs_of(result["results"][0]) == ["auchan:a3"]


def test_what_the_user_already_watches_is_not_recommended_back(catalogue):
    catalogue([("tesco:1", 0.99), ("auchan:a1", 0.98), ("auchan:a3", 0.5)])
    result = recommendations.rows(["tesco", "auchan"], 1, [alert("g:5990000000011", 1)])

    # Tej is watched in both stores, so the only pick left is the Joghurt.
    assert refs_of(result["results"][0]) == ["auchan:a3"]


def test_a_hit_from_another_category_is_left_out(catalogue):
    catalogue([("auchan:a4", 0.99), ("auchan:a3", 0.4)])
    result = recommendations.rows(["tesco", "auchan"], 1, [alert("tesco:1", 1)])

    # The cola scores higher but is not in the watched category.
    assert refs_of(result["results"][0]) == ["auchan:a3"]


def test_relevance_and_discount_both_count(catalogue):
    """0.5 x similarity + 0.5 x discount: a big saving beats a slightly closer match."""
    catalogue([("auchan:a2", 0.80), ("auchan:a3", 0.60)])
    result = recommendations.rows(["tesco", "auchan"], 2, [alert("tesco:1", 1)])

    # a3 is half price (0.5 discount), a2 has none: 0.3+0.25 > 0.4+0.0
    assert [refs_of(row)[0] for row in result["results"][:2]] == ["auchan:a3", "auchan:a2"]


def test_one_brand_cannot_fill_the_page(catalogue, monkeypatch):
    """The nearest neighbours of a product are usually the same brand in another size."""
    variants = []
    for index in range(6):
        variant = offer("auchan", f"v{index}", f"Teszt tej {index} l", 300 - index,
                        AUCHAN_DAIRY, gtin=f"599000000{index:04d}")
        variant["brand"] = "Teszt"
        variants.append(variant)
    monkeypatch.setitem(queries.ADAPTERS, "auchan", Adapter(AUCHAN + variants))
    catalogue([(f"auchan:v{index}", 0.9 - index / 100) for index in range(6)])

    result = recommendations.rows(["auchan"], 6, [alert("auchan:a1", 1)])
    picks = result["results"][: result["personalized_count"]]

    assert [row["brand"] for row in picks].count("Teszt") <= recommendations.MAX_PER_BRAND


def test_a_row_without_a_brand_is_never_capped(catalogue):
    catalogue([("auchan:a3", 0.9), ("auchan:a2", 0.8)])
    result = recommendations.rows(["tesco", "auchan"], 4, [alert("tesco:1", 1)])
    assert result["personalized_count"] >= 2


# -- falling back -------------------------------------------------------------------

def test_no_alerts_is_the_discount_listing(catalogue):
    catalogue([])
    cold = recommendations.rows(["tesco", "auchan"], 3, [])

    assert cold["type"] == "cold_start" and cold["personalized_count"] == 0
    assert cold["results"][0]["best_price"] == 150.0          # the biggest saving first


def test_an_unavailable_vector_store_falls_back_to_discounts(catalogue):
    catalogue([], unavailable=True)
    result = recommendations.rows(["tesco", "auchan"], 3, [alert("tesco:1", 1)])

    assert result["type"] == "cold_start"
    assert result["results"]


def test_alerts_without_vectors_fall_back_to_discounts(catalogue):
    catalogue([("auchan:a3", 0.9)], missing_vectors=True)
    result = recommendations.rows(["tesco", "auchan"], 3, [alert("tesco:1", 1)])

    assert result["type"] == "cold_start"


def test_filler_never_repeats_a_pick(catalogue):
    catalogue([("auchan:a3", 0.9)])
    result = recommendations.rows(["tesco", "auchan"], 4, [alert("tesco:1", 1)])

    keys = [row["group_id"] or refs_of(row)[0] for row in result["results"]]
    assert len(keys) == len(set(keys))


# -- the pieces ---------------------------------------------------------------------

@pytest.mark.parametrize("target, expected", [
    ("g:5990000000011", ["auchan:a1", "tesco:1"]),      # a barcode group: both stores
    ("tesco:1", ["tesco:1"]),
    ("auchan:a1", ["auchan:a1"]),
    ("1", ["tesco:1"]),                                  # a legacy alert, before targets existed
    ("lidl:9", []),                                      # a store that is not selected
])
def test_watched_offers_resolves_every_target_shape(catalogue, target, expected):
    catalogue([])
    found = recommendations.watched_offers([alert(target, 1)], ["tesco", "auchan"])
    assert sorted(o["ref"] for o, _ in found) == expected


def test_categories_rank_by_how_much_the_user_watches_them():
    buckets = {
        "a": {"refs": ["r1"], "groups": {"g1"}, "latest": 5},
        "b": {"refs": ["r2", "r3"], "groups": {"g2", "g3"}, "latest": 1},
        "c": {"refs": ["r4"], "groups": {"g4"}, "latest": 9},
    }
    assert recommendations.rank_categories(buckets, top_n=2) == ["b", "c"]


@pytest.mark.parametrize("count, total, expected", [
    (3, 100, [34, 33, 33]),
    (2, 10, [5, 5]),
    (1, 7, [7]),
    (0, 10, []),
    (4, 2, [1, 1, 0, 0]),
])
def test_slots_are_shared_out_evenly(count, total, expected):
    assert recommendations.allocate(count, total) == expected


# -- the legacy Tesco engine still behind /api/v1/recommendations -------------------

def _engine():
    spec = importlib.util.spec_from_file_location(
        "backend_recommendation_engine", REPO_ROOT / "backend-api" / "recommendation_engine.py")
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
