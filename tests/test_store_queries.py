"""Merging search and browse results across stores without favouring any store."""

import pytest

from stores import offers, queries


def offer(store, product_id, name, regular=None, promo=None):
    return offers.build_offer(
        store_id=store, store_product_id=product_id, name=name,
        price_set=offers.prices(regular=regular, promo=promo),
    )


class FakeAdapter:
    def __init__(self, store, results, total=None):
        self.store = store
        self.results = results
        self.total = len(results) if total is None else total
        self.calls = []

    def search(self, query, limit):
        self.calls.append(("search", query, limit))
        return {"results": self.results[:limit], "total": self.total}

    def browse(self, limit, sort_by, sort_dir):
        self.calls.append(("browse", limit, sort_by, sort_dir))
        return {"results": self.results[:limit], "total": self.total}

    def get_offer(self, product_id):
        return next((o for o in self.results if o["store_product_id"] == product_id), None)

    def get_history(self, product_id):
        return [] if self.get_offer(product_id) else None


@pytest.fixture
def adapters(monkeypatch):
    tesco = FakeAdapter("tesco", [offer("tesco", "t1", "Tej"), offer("tesco", "t2", "Tejföl")], total=40)
    auchan = FakeAdapter("auchan", [offer("auchan", "a1", "Tej 2,8%"), offer("auchan", "a2", "Túró")], total=7)
    monkeypatch.setattr(queries, "ADAPTERS", {"tesco": tesco, "auchan": auchan})
    return tesco, auchan


def test_search_interleaves_stores_by_rank(adapters):
    page = queries.search(["tesco", "auchan"], "tej", skip=0, limit=10)
    assert [o["ref"] for o in page["results"]] == ["tesco:t1", "auchan:a1", "tesco:t2", "auchan:a2"]
    assert page["total"] == 47
    assert page["stores"] == ["tesco", "auchan"]


def test_single_store_only_queries_that_store(adapters):
    tesco, auchan = adapters
    page = queries.search(["auchan"], "tej", skip=1, limit=1)
    assert [o["ref"] for o in page["results"]] == ["auchan:a2"]
    assert tesco.calls == []
    assert auchan.calls == [("search", "tej", 2)]


def test_window_is_bounded(adapters):
    with pytest.raises(queries.WindowTooLarge):
        queries.search(["tesco"], "tej", skip=990, limit=20)


def test_browse_merges_by_price_with_unpriced_last(adapters, monkeypatch):
    tesco = FakeAdapter("tesco", [offer("tesco", "t1", "B", regular=300), offer("tesco", "t2", "Z")])
    auchan = FakeAdapter("auchan", [offer("auchan", "a1", "A", regular=250, promo=100), offer("auchan", "a2", "C", regular=500)])
    monkeypatch.setattr(queries, "ADAPTERS", {"tesco": tesco, "auchan": auchan})

    ascending = queries.browse(["tesco", "auchan"], 0, 10, "price", "asc")
    descending = queries.browse(["tesco", "auchan"], 0, 10, "price", "desc")

    assert [o["ref"] for o in ascending["results"]] == ["auchan:a1", "tesco:t1", "auchan:a2", "tesco:t2"]
    assert [o["ref"] for o in descending["results"]] == ["auchan:a2", "tesco:t1", "auchan:a1", "tesco:t2"]


def test_browse_by_name_is_case_insensitive_in_both_directions(monkeypatch):
    tesco = FakeAdapter("tesco", [offer("tesco", "t1", "banán"), offer("tesco", "t2", "Citrom")])
    auchan = FakeAdapter("auchan", [offer("auchan", "a1", "Alma")])
    monkeypatch.setattr(queries, "ADAPTERS", {"tesco": tesco, "auchan": auchan})
    names = lambda page: [o["name"] for o in page["results"]]  # noqa: E731
    assert names(queries.browse(["tesco", "auchan"], 0, 10, "name", "asc")) == ["Alma", "banán", "Citrom"]
    assert names(queries.browse(["tesco", "auchan"], 0, 10, "name", "desc")) == ["Citrom", "banán", "Alma"]


def test_browse_by_discount_puts_non_discounted_last(monkeypatch):
    tesco = FakeAdapter("tesco", [offer("tesco", "t1", "none", regular=100), offer("tesco", "t2", "half", regular=100, promo=50)])
    auchan = FakeAdapter("auchan", [offer("auchan", "a1", "tenth", regular=100, promo=90)])
    monkeypatch.setattr(queries, "ADAPTERS", {"tesco": tesco, "auchan": auchan})
    page = queries.browse(["tesco", "auchan"], 0, 10, "discount", "desc")
    assert [o["name"] for o in page["results"]] == ["half", "tenth", "none"]


def test_offer_lookup_dispatches_by_reference(adapters):
    assert queries.get_offer("auchan:a2")["name"] == "Túró"
    assert queries.get_offer("tesco:missing") is None
    assert queries.get_history("tesco:t1") == []


def test_offer_prices_are_summarised():
    built = offer("auchan", "1", "x", regular=1000, promo=800)
    assert built["effective_price"] == 800
    assert built["discount_ratio"] == 0.2
