"""Two stores end to end: linking, every store combination, switches, categories."""

import pytest

from stores import categories
from stores.registry import registry


pytestmark = pytest.mark.integration


def rows(response):
    assert response.status_code == 200, response.text
    return response.json()["results"]


def refs(response):
    return sorted(offer["ref"] for row in rows(response) for offer in row["offers"])


# -- linking and the store combinations ---------------------------------------------

def test_a_shared_barcode_puts_both_stores_in_one_row(api):
    row, = [r for r in rows(api.get("/api/v1/search", params={"q": "kefir", "mode": "text"}))
            if r["group_id"] == "g:5998200557003"]
    assert [offer["store"] for offer in row["offers"]] == ["tesco", "auchan"]
    assert row["store_count"] == 2
    assert row["best_price"] == 529.0
    assert sorted(row["cheapest_stores"]) == ["auchan", "tesco"]


def test_the_cheaper_store_comes_first_in_a_row(api):
    row, = [r for r in rows(api.get("/api/v1/search", params={"q": "tej 1,5", "mode": "text"}))
            if r["group_id"] == "g:5998200557001"]
    assert [(o["store"], o["effective_price"]) for o in row["offers"]] == [("auchan", 379.0), ("tesco", 399.0)]
    assert row["cheapest_stores"] == ["auchan"]


@pytest.mark.parametrize("stores, expected", [
    ("tesco", {"tesco"}),
    ("auchan", {"auchan"}),
    ("", {"tesco", "auchan"}),                  # empty means every enabled store
    ("auchan,tesco", {"tesco", "auchan"}),
])
def test_every_store_combination_answers_from_those_stores_only(api, stores, expected):
    found = refs(api.get("/api/v1/search", params={"q": "tej", "mode": "text", "stores": stores}))
    assert found, "the text index should match the seeded milk"
    assert {ref.split(":")[0] for ref in found} == expected


def test_browse_orders_by_price_across_both_stores(api):
    listed = rows(api.get("/api/v1/browse", params={"sort_by": "price", "sort_dir": "asc", "limit": 4}))
    prices = [row["best_price"] for row in listed]
    assert prices == sorted(prices)
    assert prices[0] == 199.0                    # the Tesco-only mineral water


def test_a_group_carries_every_store_and_its_history(api):
    group = api.get("/api/v1/groups/g:5998200557002").json()
    assert {offer["store"] for offer in group["offers"]} == {"tesco", "auchan"}
    assert group["offers"][0]["effective_price"] == 419.0     # Tesco promotion undercuts Auchan

    history = api.get("/api/v1/groups/g:5998200557002/history").json()
    assert [series["store"] for series in history["series"]] == ["tesco", "auchan"]
    assert history["series"][0]["history"][-1]["promo"] == 419.0


def test_a_product_only_one_store_sells_stands_on_its_own(api):
    row, = [r for r in rows(api.get("/api/v1/search", params={"q": "tejföl", "mode": "text"}))]
    assert row["store_count"] == 1 and row["offers"][0]["store"] == "auchan"


# -- the switches -------------------------------------------------------------------

def stores_answering(api, **params):
    return {ref.split(":")[0] for ref in refs(api.get("/api/v1/search", params={"q": "tej", "mode": "text", **params}))}


def test_disabling_a_store_hides_it_everywhere(api, catalogue):
    registry.set_flags("auchan", enabled=False)
    try:
        assert [store["id"] for store in api.get("/api/v1/stores").json()["stores"]] == ["tesco"]
        assert stores_answering(api) == {"tesco"}
        assert api.get("/api/v1/search", params={"q": "tej", "stores": "auchan"}).status_code == 404
        assert api.get("/api/v1/offers/auchan:200").status_code == 404
    finally:
        registry.set_flags("auchan", enabled=True)


def test_disabling_tesco_also_closes_the_legacy_routes(api, catalogue):
    registry.set_flags("tesco", enabled=False)
    try:
        assert api.get("/api/v1/search", params={"q": "tej", "stores": "tesco"}).status_code == 404
        assert stores_answering(api) == {"auchan"}
        assert api.get("/api/v1/products/search", params={"q": "tej"}).status_code == 404
    finally:
        registry.set_flags("tesco", enabled=True)


# -- the learned category mapping ---------------------------------------------------

def test_the_mapping_is_learned_from_the_products_both_stores_sell(catalogue):
    report = categories.rebuild()

    assert report["categories"] == 2                      # Tejtermékek and Üdítők
    auchan = report["stores"]["auchan"]
    assert auchan["paths"] == 2                           # ("...","Tej") and ("Ital","Üdítő")
    assert auchan["mapped_paths"] == 1                    # the single linked drink is not enough
    assert auchan["mapped_products"] == 4                 # every product on the dairy path

    mapping = categories.mapping()
    dairy = mapping.category_for("tesco", ["Alapvető élelmiszerek", "Tejtermékek"])
    assert mapping.category_for("auchan", ["Élelmiszer", "Tej, tojás", "Tej"]) == dairy
    assert mapping.category_for("auchan", ["Ital", "Üdítő"]) is None


def test_categories_are_listed_with_each_store_s_count(api, catalogue):
    categories.rebuild()
    listed = api.get("/api/v1/categories").json()["categories"]
    dairy, = [row for row in listed if row["name"] == "Tejtermékek"]
    assert dairy["counts"] == {"tesco": 4, "auchan": 4}

    drinks, = [row for row in listed if row["name"] == "Üdítők"]
    assert drinks["counts"] == {"tesco": 2, "auchan": 0}   # nothing of Auchan's mapped there


def test_a_category_filters_both_stores_by_their_own_vocabulary(api, catalogue):
    categories.rebuild()
    dairy = categories.mapping().category_for("tesco", ["Alapvető élelmiszerek", "Tejtermékek"])

    listed = rows(api.get("/api/v1/browse", params={"category": dairy, "limit": 50}))
    found = sorted(offer["ref"] for row in listed for offer in row["offers"])
    assert found == ["auchan:200", "auchan:201", "auchan:202", "auchan:203",
                     "tesco:100", "tesco:101", "tesco:102", "tesco:103"]

    searched = rows(api.get("/api/v1/search", params={"q": "kóla", "mode": "text", "category": dairy}))
    assert searched == []


def test_an_unmapped_path_is_left_out_rather_than_guessed(api, catalogue):
    categories.rebuild()
    drinks = categories.mapping().category_for("tesco", ["Italok", "Üdítők"])

    listed = rows(api.get("/api/v1/browse", params={"category": drinks, "limit": 50}))
    found = sorted(offer["ref"] for row in listed for offer in row["offers"])
    # auchan:204 is a linked drink, so it joins its group's row, but Auchan's own
    # drinks path is unmapped and never selects it on its own.
    assert "tesco:104" in found and "tesco:105" in found
    assert categories.query_for("auchan", drinks) == {"category_path": {"$in": []}}


def test_an_unknown_category_is_refused(api, catalogue):
    categories.rebuild()
    assert api.get("/api/v1/browse", params={"category": "nincs/ilyen"}).status_code == 400


# -- statistics ---------------------------------------------------------------------

def test_the_comparison_only_counts_products_both_stores_sell(api, catalogue):
    body = api.get("/api/v1/insights/compare").json()
    assert body["linked_products"] == 4                    # three dairy plus the cola
    assert body["cheapest_by_regular_price"]["tesco"] == 2     # the 2,8% milk and the cola
    assert body["cheapest_by_regular_price"]["auchan"] == 1    # the 1,5% milk
    assert body["ties"]["regular"] == 1                        # the kefir, same price in both
    # Tesco's promotion on the 2,8% milk only shows in the best-price counts.
    assert body["cheapest_by_best_price"]["tesco"] == 2


def test_per_store_insights_cover_each_catalogue(api, catalogue):
    body = api.get("/api/v1/insights").json()
    assert body["stores"] == ["tesco", "auchan"]
    assert body["by_store"]["tesco"]["product_counts"]["total"] == 6
    assert body["by_store"]["auchan"]["product_counts"]["total"] == 5
