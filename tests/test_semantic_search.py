"""Hybrid search: rank fusion, per-store semantic retrieval, fallback, similar products."""

import logging

import pytest

from stores import offers, queries, semantic


def offer(store, product_id, name, gtin=None):
    return offers.build_offer(store_id=store, store_product_id=product_id, name=name, gtin=gtin,
                              price_set=offers.prices(regular=100))


class Adapter:
    def __init__(self, catalogue, text_hits):
        self.catalogue = {o["store_product_id"]: o for o in catalogue}
        self.text_hits = text_hits
        self.text_calls = 0

    def search(self, query, limit, category_query=None):
        self.text_calls += 1
        hits = [self.catalogue[i] for i in self.text_hits][:limit]
        return {"results": hits, "total": len(hits)}

    def find_by_ids(self, ids):
        return [self.catalogue[i] for i in ids if i in self.catalogue]

    def find_by_gtins(self, gtins):
        return [o for o in self.catalogue.values() if o["gtin"] in gtins]


TESCO = [offer("tesco", "1", "Zabpehely"), offer("tesco", "2", "Müzli"), offer("tesco", "3", "Kukoricapehely", gtin="5990000000011")]
AUCHAN = [offer("auchan", "a1", "Zabkása"), offer("auchan", "a3", "Kukoricapehely", gtin="5990000000011")]


@pytest.fixture
def stores(monkeypatch):
    tesco = Adapter(TESCO, text_hits=["1"])
    auchan = Adapter(AUCHAN, text_hits=[])
    monkeypatch.setattr(queries, "ADAPTERS", {"tesco": tesco, "auchan": auchan})
    semantic_hits = {"tesco": [("tesco:2", 0.9), ("tesco:1", 0.85)], "auchan": [("auchan:a1", 0.88)]}
    calls = []

    def nearest(vector, store_ids, limit, min_score=None, **exclude):
        calls.append((tuple(store_ids), exclude))
        return [hit for store in store_ids for hit in semantic_hits.get(store, [])][:limit]

    monkeypatch.setattr(semantic, "embed_query", lambda query: [1.0, 0.0])
    monkeypatch.setattr(semantic, "nearest", nearest)
    return {"tesco": tesco, "auchan": auchan, "nearest_calls": calls}


def refs(page):
    return [[o["ref"] for o in row["offers"]] for row in page["results"]]


def test_rrf_rewards_offers_found_by_both_retrievers():
    a, b, c = offer("tesco", "a", "A"), offer("tesco", "b", "B"), offer("tesco", "c", "C")
    # b is second in both lists: 2/(60+2) beats a's single 1/(60+1).
    assert [o["ref"] for o in queries.fuse([[a, b], [c, b]])] == ["tesco:b", "tesco:a", "tesco:c"]


def test_hybrid_fuses_text_and_meaning_per_store(stores):
    page = queries.search(["tesco", "auchan"], "reggeli gabona", 0, 10, "hybrid")

    assert page["mode"] == "hybrid"
    # Tesco: "1" is in both lists and wins; Auchan only has its semantic hit.
    assert refs(page) == [["tesco:1"], ["auchan:a1"], ["tesco:2"]]
    assert stores["nearest_calls"] == [(("tesco",), {}), (("auchan",), {})]


def test_a_small_page_still_gets_a_full_candidate_pool(stores, monkeypatch):
    windows = []
    monkeypatch.setattr(queries, "_semantic_offers",
                        lambda store_id, vector, window, min_score: windows.append(window) or [])
    queries.search(["tesco"], "zab", 0, 5, "hybrid")
    assert windows == [queries.CANDIDATES_MIN]


def test_semantic_mode_skips_the_text_index(stores):
    page = queries.search(["tesco"], "reggeli gabona", 0, 10, "semantic")
    assert refs(page) == [["tesco:2"], ["tesco:1"]]
    assert stores["tesco"].text_calls == 0


def test_falls_back_to_text_when_vectors_are_unavailable(stores, monkeypatch, caplog):
    def down(_query):
        raise semantic.SemanticUnavailable("connection refused")

    monkeypatch.setattr(semantic, "embed_query", down)
    caplog.set_level(logging.WARNING)
    page = queries.search(["tesco", "auchan"], "zab", 0, 10, "hybrid")

    assert page["mode"] == "text"
    assert refs(page) == [["tesco:1"]]
    assert [r for r in caplog.records if getattr(r, "Action", None) == "search.semantic_unavailable"]


def test_barcodes_use_text_search_only(stores):
    page = queries.search(["tesco"], "5990000000011", 0, 10, "hybrid")
    assert page["mode"] == "text" and stores["nearest_calls"] == []


def test_unknown_mode_is_rejected(stores):
    with pytest.raises(ValueError):
        queries.search(["tesco"], "zab", 0, 10, "fuzzy")


def test_similar_leaves_out_the_same_product_in_other_stores(stores, monkeypatch):
    monkeypatch.setattr(semantic, "vectors_for", lambda refs: {ref: [1.0, 0.0] for ref in refs})
    result = queries.similar(["tesco", "auchan"], 5, group_id="g:5990000000011")

    assert stores["nearest_calls"][-1] == (("tesco", "auchan"), {"exclude_group": "g:5990000000011", "exclude_ref": None})
    assert refs(result) == [["tesco:2"], ["tesco:1"], ["auchan:a1"]]


def test_similar_is_none_before_the_product_has_a_vector(stores, monkeypatch):
    monkeypatch.setattr(semantic, "vectors_for", lambda refs: {})
    assert queries.similar(["tesco"], 5, ref="tesco:2") is None


def test_point_ids_are_stable_per_ref():
    assert semantic.point_id("tesco:1") == semantic.point_id("tesco:1")
    assert semantic.point_id("tesco:1") != semantic.point_id("auchan:1")
