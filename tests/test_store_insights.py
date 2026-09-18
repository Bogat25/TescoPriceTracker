"""Store-neutral statistics and the cross-store comparison."""

from datetime import date, datetime, timedelta

import pytest

from stores import insights, queries


TODAY = date(2026, 9, 17)


class HistoryAdapter:
    def __init__(self, store, products):
        self.store = store
        self.products = products  # (id, name, category, gtin, rows)

    def iter_histories(self, gtin_norms=None):
        for product_id, name, category, gtin, rows in self.products:
            yield f"{self.store}:{product_id}", name, category, gtin, rows


def install(monkeypatch, **adapters):
    monkeypatch.setattr(queries, "ADAPTERS", adapters)


def test_store_insights_single_pass(monkeypatch):
    install(monkeypatch, tesco=HistoryAdapter("tesco", [
        ("1", "Tej", "Tejtermék", "5998200557699", [
            ("2026-08-18", 400.0, None, None),
            ("2026-09-16", 420.0, None, None),
            ("2026-09-17", 400.0, 300.0, 350.0),
        ]),
        ("2", "Kávé", "Italok", None, [
            ("2026-09-16", 2000.0, None, None),
            ("2026-09-17", 2100.0, None, None),
        ]),
        ("3", "Old product", "Italok", None, [("2026-09-01", 50.0, None, None)]),
        ("4", "No history", "Italok", None, []),
    ]))

    data = insights.compute_store_insights("tesco", TODAY)

    assert data["product_counts"] == {"total": 4, "active_today": 2, "historical_only": 2}
    assert data["price_index"][0] == {"date": "2026-08-18", "index": 100.0}
    assert {"tier": "0–1 000", "count": 2} in data["price_tiers"]
    assert {"tier": "1 000–5 000", "count": 1} in data["price_tiers"]
    assert data["price_channels"]["avg_regular"] == pytest.approx((400 + 2100 + 50) / 3, abs=0.01)
    assert data["price_channels"]["products_with_promo"] == 1
    assert data["price_channels"]["products_with_loyalty"] == 1
    assert data["top_discounts"] == [{"ref": "tesco:1", "name": "Tej", "regular": 400.0,
                                      "promo": 300.0, "promo_price": 300.0, "loyalty_price": 350.0,
                                      "pct_off": 25.0}]
    assert data["price_drops"][0]["ref"] == "tesco:1" and data["price_drops"][0]["drop_amount"] == 20.0
    assert data["best_shopping_day"] == {"date": "2026-09-17", "total_savings": 100.0}
    thursday = next(day for day in data["discount_by_weekday"] if day["weekday"] == "Thursday")
    assert thursday == {"weekday": "Thursday", "avg_pct_off": 25.0, "total_events": 1}
    assert data["inflation_30d"]["avg_30d_ago"] == 400.0
    assert data["inflation_30d"]["avg_today"] == 1250.0
    # Only product 1 has a price on both days (400 -> 400): no change, although
    # the plain averages over different product sets differ by 212.5 %.
    assert data["inflation_30d"]["pct_change"] == 0.0
    assert data["inflation_30d"]["paired_products"] == 1
    # Channels compare each product's promo/card price with its own regular price.
    assert data["price_channels"]["promo_vs_regular_pct"] == -25.0
    assert data["price_channels"]["loyalty_vs_regular_pct"] == -12.5


def test_empty_store_does_not_fail(monkeypatch):
    install(monkeypatch, auchan=HistoryAdapter("auchan", []))
    data = insights.compute_store_insights("auchan", TODAY)
    assert data["price_index"] == [] and data["global_avg"] == {"avg_price": None, "product_count": 0}
    assert data["inflation_30d"]["pct_change"] is None


def test_comparison_on_linked_products_only(monkeypatch):
    install(
        monkeypatch,
        tesco=HistoryAdapter("tesco", [
            ("t1", "Tej", "Tejtermék", "111111111", [("2026-09-16", 400.0, None, None), ("2026-09-17", 400.0, None, 300.0)]),
            ("t2", "Kávé", "Italok", "222222222", [("2026-09-17", 1000.0, None, None)]),
            ("t3", "Tesco only", "Italok", "333333333", [("2026-09-17", 10.0, None, None)]),
            ("t4", "Weighed", "Hús", "2802590000000", [("2026-09-17", 10.0, None, None)]),
            ("t5", "Delisted", "Italok", "444444444", [("2026-09-01", 10.0, None, None)]),
            ("t6", "Kávé duplicate", "Italok", "222222222", [("2026-09-17", 1100.0, None, None)]),
        ]),
        auchan=HistoryAdapter("auchan", [
            ("a1", "Tej", "Friss", "111111111", [("2026-09-17", 380.0, None, None)]),
            ("a2", "Kávé", "Italok", "222222222", [("2026-09-17", 1000.0, None, None)]),
            ("a4", "Weighed", "Hús", "2802590000000", [("2026-09-17", 5.0, None, None)]),
            ("a5", "Delisted", "Italok", "444444444", [("2026-09-17", 10.0, None, None)]),
        ]),
    )

    result = insights.compute_comparison(["tesco", "auchan"], TODAY)

    assert result["linked_products"] == 2
    assert result["cheapest_by_regular_price"] == {"tesco": 0, "auchan": 1}
    assert result["cheapest_by_best_price"] == {"tesco": 1, "auchan": 0}
    assert result["ties"] == {"regular": 1, "best": 1}
    assert result["price_index_vs_cheapest"]["auchan"] == 100.0
    assert result["price_index_vs_cheapest"]["tesco"] == pytest.approx((400 / 380 * 100 + 100) / 2, abs=0.01)
    assert {c["category"] for c in result["categories"]} == {"Tejtermék", "Italok"}   # first store's categories
    assert result["basket"] == [{"date": "2026-09-17", "items": 2, "totals": {"tesco": 1400.0, "auchan": 1380.0}}]


class CacheCollection:
    def __init__(self):
        self.docs = {}

    def find_one(self, query):
        return self.docs.get(query["_id"])

    def replace_one(self, query, doc, upsert=False):
        self.docs[query["_id"]] = doc

    def delete_many(self, query):
        prefix = query["_id"]["$regex"].lstrip("^")
        for key in [k for k in self.docs if k.startswith(prefix)]:
            del self.docs[key]


@pytest.fixture
def cache(monkeypatch):
    collection = CacheCollection()
    monkeypatch.setattr(insights, "_cache", lambda: collection)
    return collection


def test_store_insights_are_cached_per_day(monkeypatch, cache):
    calls = []
    monkeypatch.setattr(insights, "compute_store_insights", lambda store, day: calls.append(store) or {"store": store})
    assert insights.store_insights("tesco", TODAY) == {"store": "tesco"}
    assert insights.store_insights("tesco", TODAY) == {"store": "tesco"}
    assert calls == ["tesco"]
    assert "insights:store:tesco:2026-09-17" in cache.docs


def test_comparison_cache_expires(monkeypatch, cache):
    calls = []
    monkeypatch.setattr(insights, "compute_comparison", lambda stores, day: calls.append(1) or {"n": len(calls)})
    assert insights.comparison(["tesco", "auchan"], TODAY) == {"n": 1}
    assert insights.comparison(["tesco", "auchan"], TODAY) == {"n": 1}
    key = "insights:compare:tesco,auchan:2026-09-17"
    cache.docs[key]["computed_at"] = (datetime.now() - timedelta(hours=2)).isoformat()
    assert insights.comparison(["tesco", "auchan"], TODAY) == {"n": 2}


@pytest.mark.real_insight_rebuild
def test_rebuild_refreshes_store_and_drops_comparisons(monkeypatch, cache):
    monkeypatch.setattr(insights, "compute_store_insights", lambda store, day: {"store": store, "day": day.isoformat()})
    cache.docs["insights:compare:tesco,auchan:2026-09-17"] = {"data": {}, "computed_at": datetime.now().isoformat()}

    assert insights.rebuild_store("auchan", clock=lambda: TODAY) is True
    assert cache.docs["insights:store:auchan:2026-09-17"]["data"] == {"store": "auchan", "day": "2026-09-17"}
    assert not any(key.startswith("insights:compare:") for key in cache.docs)

    monkeypatch.setattr(insights, "compute_store_insights", lambda store, day: 1 / 0)
    assert insights.rebuild_store("auchan", clock=lambda: TODAY) is False


def test_a_loyalty_only_saving_counts_as_a_discount(monkeypatch):
    """Tesco's savings are usually Clubcard prices, not promotions."""
    install(monkeypatch, tesco=HistoryAdapter("tesco", [
        ("1", "Sajt", "Tejtermék", None, [
            ("2026-09-16", 1000.0, None, None),
            ("2026-09-17", 1000.0, None, 750.0),      # Clubcard only, no promotion
        ]),
    ]))

    data = insights.compute_store_insights("tesco", TODAY)

    discount, = data["top_discounts"]
    assert discount["pct_off"] == 25.0
    assert discount["promo"] == 750.0 and discount["promo_price"] is None
    assert data["best_shopping_day"] == {"date": "2026-09-17", "total_savings": 250.0}
    thursday = next(day for day in data["discount_by_weekday"] if day["weekday"] == "Thursday")
    assert thursday["avg_pct_off"] == 25.0


def test_the_cheaper_channel_decides_the_discount(monkeypatch):
    install(monkeypatch, tesco=HistoryAdapter("tesco", [
        ("1", "Kefir", "Tejtermék", None, [("2026-09-17", 1000.0, 900.0, 600.0)]),
    ]))

    discount, = insights.compute_store_insights("tesco", TODAY)["top_discounts"]
    assert discount["promo"] == 600.0 and discount["pct_off"] == 40.0
