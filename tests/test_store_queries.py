"""Product rows across stores: merging, barcode grouping and group lookups."""

import pytest

from stores import offers, queries


def offer(store, product_id, name, regular=None, promo=None, gtin=None, image="img"):
    return offers.build_offer(
        store_id=store, store_product_id=product_id, name=name, gtin=gtin, image_url=image,
        price_set=offers.prices(regular=regular, promo=promo),
    )


class FakeAdapter:
    def __init__(self, store, results, total=None, catalogue=()):
        self.store = store
        self.results = results
        self.catalogue = list(results) + list(catalogue)
        self.total = len(results) if total is None else total
        self.calls = []

    def search(self, query, limit):
        self.calls.append(("search", query, limit))
        return {"results": self.results[:limit], "total": self.total}

    def browse(self, limit, sort_by, sort_dir):
        self.calls.append(("browse", limit, sort_by, sort_dir))
        return {"results": self.results[:limit], "total": self.total}

    def find_by_gtins(self, gtins):
        self.calls.append(("find_by_gtins", list(gtins)))
        return [o for o in self.catalogue if o["gtin"] in gtins]

    def get_offer(self, product_id):
        return next((o for o in self.catalogue if o["store_product_id"] == product_id), None)

    def get_history(self, product_id):
        return [{"date": "2026-09-17", "regular": 1.0}] if self.get_offer(product_id) else None


def install(monkeypatch, tesco, auchan):
    monkeypatch.setattr(queries, "ADAPTERS", {"tesco": tesco, "auchan": auchan})


def refs(row):
    return [o["ref"] for o in row["offers"]]


def test_search_interleaves_stores_by_rank(monkeypatch):
    tesco = FakeAdapter("tesco", [offer("tesco", "t1", "Tej"), offer("tesco", "t2", "Tejföl")], total=40)
    auchan = FakeAdapter("auchan", [offer("auchan", "a1", "Tej 2,8%"), offer("auchan", "a2", "Túró")], total=7)
    install(monkeypatch, tesco, auchan)

    page = queries.search(["tesco", "auchan"], "tej", skip=0, limit=10)

    assert [refs(row) for row in page["results"]] == [["tesco:t1"], ["auchan:a1"], ["tesco:t2"], ["auchan:a2"]]
    assert page["total"] == 47 and page["total_counts_offers"] is True
    assert page["stores"] == ["tesco", "auchan"]


def test_same_barcode_becomes_one_row_cheapest_first(monkeypatch):
    tesco = FakeAdapter("tesco", [offer("tesco", "t1", "Coca-Cola 300 ml", 295, gtin="00000054026193")])
    auchan = FakeAdapter("auchan", [offer("auchan", "a1", "Coca-Cola 0,3 l", 299, promo=279, gtin="54026193")])
    install(monkeypatch, tesco, auchan)

    row = queries.search(["tesco", "auchan"], "cola", 0, 10)["results"][0]

    assert row["group_id"] == "g:54026193"
    assert refs(row) == ["auchan:a1", "tesco:t1"]
    assert row["best_price"] == 279 and row["cheapest_stores"] == ["auchan"]
    assert row["name"] == "Coca-Cola 300 ml"  # display name follows registry order, not price
    assert row["store_count"] == 2


def test_missing_store_offers_are_filled_in_by_barcode(monkeypatch):
    tesco = FakeAdapter("tesco", [offer("tesco", "t1", "Túró Rudi", 199, gtin="5998200452345")])
    auchan = FakeAdapter("auchan", [], catalogue=[offer("auchan", "a9", "Túró Rudi", 189, gtin="5998200452345")])
    install(monkeypatch, tesco, auchan)

    row = queries.search(["tesco", "auchan"], "rudi", 0, 10)["results"][0]

    assert refs(row) == ["auchan:a9", "tesco:t1"]
    assert auchan.calls[-1] == ("find_by_gtins", ["5998200452345"])


def test_single_store_query_never_touches_other_stores(monkeypatch):
    tesco = FakeAdapter("tesco", [offer("tesco", "t1", "Tej", gtin="5998200557699")])
    auchan = FakeAdapter("auchan", [offer("auchan", "a1", "Tej"), offer("auchan", "a2", "Túró")])
    install(monkeypatch, tesco, auchan)

    page = queries.search(["auchan"], "tej", skip=1, limit=1)

    assert [refs(row) for row in page["results"]] == [["auchan:a2"]]
    assert tesco.calls == []
    assert auchan.calls == [("search", "tej", 2)]


def test_in_store_codes_and_missing_barcodes_are_never_grouped(monkeypatch):
    tesco = FakeAdapter("tesco", [offer("tesco", "t1", "Csirke", 999, gtin="2802590000000"), offer("tesco", "t2", "Zöldség")])
    auchan = FakeAdapter("auchan", [offer("auchan", "a1", "Csirke", 899, gtin="2802590000000"), offer("auchan", "a2", "Zöldség")])
    install(monkeypatch, tesco, auchan)

    page = queries.search(["tesco", "auchan"], "x", 0, 10)

    assert len(page["results"]) == 4
    assert all(row["group_id"] is None and row["store_count"] == 1 for row in page["results"])
    assert all(call[0] != "find_by_gtins" for call in tesco.calls + auchan.calls)


def test_window_is_bounded(monkeypatch):
    install(monkeypatch, FakeAdapter("tesco", []), FakeAdapter("auchan", []))
    with pytest.raises(queries.WindowTooLarge):
        queries.search(["tesco"], "tej", skip=990, limit=20)


def test_browse_merges_by_price_with_unpriced_last(monkeypatch):
    tesco = FakeAdapter("tesco", [offer("tesco", "t1", "B", regular=300), offer("tesco", "t2", "Z")])
    auchan = FakeAdapter("auchan", [offer("auchan", "a1", "A", regular=250, promo=100), offer("auchan", "a2", "C", regular=500)])
    install(monkeypatch, tesco, auchan)

    ascending = queries.browse(["tesco", "auchan"], 0, 10, "price", "asc")
    descending = queries.browse(["tesco", "auchan"], 0, 10, "price", "desc")

    assert [refs(r)[0] for r in ascending["results"]] == ["auchan:a1", "tesco:t1", "auchan:a2", "tesco:t2"]
    assert [refs(r)[0] for r in descending["results"]] == ["auchan:a2", "tesco:t1", "auchan:a1", "tesco:t2"]


def test_browse_groups_linked_products_and_orders_by_best_price(monkeypatch):
    tesco = FakeAdapter("tesco", [offer("tesco", "t1", "Tej", 400, gtin="5998200557699"), offer("tesco", "t2", "Kakaó", 350)])
    auchan = FakeAdapter("auchan", [offer("auchan", "a1", "Tej", 300, gtin="5998200557699")])
    install(monkeypatch, tesco, auchan)

    rows = queries.browse(["tesco", "auchan"], 0, 10, "price", "asc")["results"]

    assert [row["best_price"] for row in rows] == [300, 350]
    assert refs(rows[0]) == ["auchan:a1", "tesco:t1"]


def test_browse_by_name_is_case_insensitive_in_both_directions(monkeypatch):
    tesco = FakeAdapter("tesco", [offer("tesco", "t1", "banán"), offer("tesco", "t2", "Citrom")])
    auchan = FakeAdapter("auchan", [offer("auchan", "a1", "Alma")])
    install(monkeypatch, tesco, auchan)
    names = lambda page: [row["name"] for row in page["results"]]  # noqa: E731
    assert names(queries.browse(["tesco", "auchan"], 0, 10, "name", "asc")) == ["Alma", "banán", "Citrom"]
    assert names(queries.browse(["tesco", "auchan"], 0, 10, "name", "desc")) == ["Citrom", "banán", "Alma"]


def test_browse_by_discount_puts_non_discounted_last(monkeypatch):
    tesco = FakeAdapter("tesco", [offer("tesco", "t1", "none", regular=100), offer("tesco", "t2", "half", regular=100, promo=50)])
    auchan = FakeAdapter("auchan", [offer("auchan", "a1", "tenth", regular=100, promo=90)])
    install(monkeypatch, tesco, auchan)
    page = queries.browse(["tesco", "auchan"], 0, 10, "discount", "desc")
    assert [row["name"] for row in page["results"]] == ["half", "tenth", "none"]


def test_group_lookup_and_history(monkeypatch):
    tesco = FakeAdapter("tesco", [], catalogue=[offer("tesco", "t1", "Tej", 400, gtin="5998200557699")])
    auchan = FakeAdapter("auchan", [], catalogue=[offer("auchan", "a1", "Tej", 380, gtin="5998200557699")])
    install(monkeypatch, tesco, auchan)

    group = queries.get_group("g:5998200557699", ["tesco", "auchan"])
    assert refs(group) == ["auchan:a1", "tesco:t1"]
    assert refs(queries.get_group("g:5998200557699", ["tesco"])) == ["tesco:t1"]
    assert queries.get_group("g:0005998200557699", ["tesco"]) is None   # not normalised
    assert queries.get_group("g:2802590000000", ["tesco"]) is None      # in-store code
    assert queries.get_group("5998200557699", ["tesco"]) is None
    assert queries.get_group("g:4000000000000", ["tesco", "auchan"]) is None

    history = queries.get_group_history("g:5998200557699", ["tesco", "auchan"])
    assert [series["store"] for series in history["series"]] == ["tesco", "auchan"]


def test_offer_lookup_dispatches_by_reference(monkeypatch):
    install(monkeypatch, FakeAdapter("tesco", [offer("tesco", "t1", "Tej")]), FakeAdapter("auchan", [offer("auchan", "a2", "Túró")]))
    assert queries.get_offer("auchan:a2")["name"] == "Túró"
    assert queries.get_offer("tesco:missing") is None
    assert queries.get_history("tesco:t1")


def test_offer_carries_group_and_price_summary():
    built = offer("auchan", "1", "x", regular=1000, promo=800, gtin="05998200485596")
    assert built["group_id"] == "g:5998200485596"
    assert built["effective_price"] == 800
    assert built["discount_ratio"] == 0.2
    assert offer("tesco", "2", "y", gtin="2802590000000")["group_id"] is None
