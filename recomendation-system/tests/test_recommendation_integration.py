"""Pipeline tests for the recommendation engine with Qdrant and MongoDB mocked."""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend-api'))

from recommendation_engine import (  # noqa: E402
    _point_id,
    get_cold_start_recommendations,
    get_recommendations,
    hydrate_products,
    rank_top_categories,
    resolve_product_categories,
    search_category_bucket,
)


def _product(tpnc, normal, discount=None):
    return {
        "_id": tpnc,
        "tpnc": tpnc,
        "name": f"Product {tpnc}",
        "price_history": [{
            "date": "2026-09-01",
            "normal": {"price": normal},
            "discount": {"price": discount} if discount else None,
            "clubcard": None,
        }],
    }


class TestColdStart:

    def test_no_user_returns_cold_start(self):
        coll = MagicMock()
        coll.aggregate.return_value = [{"tpnc": "1"}, {"tpnc": "2"}]
        result = get_recommendations(coll, user_id=None, limit=10)
        assert result["type"] == "cold_start"
        assert result["count"] == 2
        assert result["personalized_count"] == 0

    def test_empty_user_id_returns_cold_start(self):
        coll = MagicMock()
        coll.aggregate.return_value = []
        assert get_recommendations(coll, user_id="", limit=10)["type"] == "cold_start"

    def test_pipeline_limits_and_excludes(self):
        coll = MagicMock()
        coll.aggregate.return_value = []
        get_cold_start_recommendations(coll, limit=7, exclude_ids=["a", "b"])
        pipeline = coll.aggregate.call_args.args[0]
        match = next(stage["$match"] for stage in pipeline if "$match" in stage)
        assert match["tpnc"] == {"$nin": ["a", "b"]}
        assert {"$limit": 7} in pipeline

    def test_database_error_returns_empty(self):
        coll = MagicMock()
        coll.aggregate.side_effect = RuntimeError("mongo down")
        assert get_cold_start_recommendations(coll, limit=5) == []


class TestRankTopCategories:

    def test_orders_by_product_count_then_latest_alert(self):
        alerts = [
            {"productId": "a", "createdAt": 1},
            {"productId": "b", "createdAt": 2},
            {"productId": "c", "createdAt": 9},
            {"productId": "d", "createdAt": 5},
        ]
        categories = {"a": "Italok", "b": "Italok", "c": "Pékáru", "d": "Tej"}
        ranked = rank_top_categories(alerts, categories, top_n=5)
        assert [cat for cat, _ in ranked] == ["Italok", "Pékáru", "Tej"]
        assert ranked[0][1] == ["a", "b"]

    def test_products_without_category_are_ignored(self):
        ranked = rank_top_categories([{"productId": "x", "createdAt": 1}], {}, top_n=5)
        assert ranked == []

    def test_top_n_limit(self):
        alerts = [{"productId": str(i), "createdAt": i} for i in range(6)]
        categories = {str(i): f"cat{i}" for i in range(6)}
        assert len(rank_top_categories(alerts, categories, top_n=3)) == 3


class TestQdrantAccess:

    @patch("recommendation_engine._get_qdrant")
    def test_resolve_categories_maps_payloads(self, get_qdrant):
        client = MagicMock()
        client.retrieve.return_value = [
            SimpleNamespace(payload={"product_id": "1", "category": "Italok"}),
            SimpleNamespace(payload={"product_id": "2", "category": ""}),
        ]
        get_qdrant.return_value = client
        assert resolve_product_categories(["1", "2"]) == {"1": "Italok"}

    @patch("recommendation_engine._get_qdrant")
    def test_resolve_categories_survives_qdrant_errors(self, get_qdrant):
        client = MagicMock()
        client.retrieve.side_effect = RuntimeError("timeout")
        get_qdrant.return_value = client
        assert resolve_product_categories(["1"]) == {}

    @patch("recommendation_engine._get_qdrant")
    def test_bucket_search_filters_category_and_excludes_ids(self, get_qdrant):
        client = MagicMock()
        client.retrieve.return_value = [SimpleNamespace(vector=[1.0, 0.0]), SimpleNamespace(vector=[0.0, 1.0])]
        client.query_points.return_value = SimpleNamespace(points=[
            SimpleNamespace(payload={"product_id": "keep"}, score=0.8),
            SimpleNamespace(payload={"product_id": "tracked"}, score=0.7),
        ])
        get_qdrant.return_value = client

        result = search_category_bucket("Italok", ["tracked"], slot_size=10, exclude_ids={"tracked"})

        kwargs = client.query_points.call_args.kwargs
        assert kwargs["query"] == [0.5, 0.5]
        assert kwargs["limit"] == 25  # 2.5x oversearch
        conditions = {c.key: c.match.value for c in kwargs["query_filter"].must}
        assert conditions == {"store": "tesco", "category": "Italok"}
        assert result == [{"product_id": "keep", "score": 0.8}]

    @patch("recommendation_engine._get_qdrant")
    def test_bucket_search_without_vectors_is_empty(self, get_qdrant):
        client = MagicMock()
        client.retrieve.return_value = [SimpleNamespace(vector=None)]
        get_qdrant.return_value = client
        assert search_category_bucket("Italok", ["x"], slot_size=10, exclude_ids=set()) == []
        client.query_points.assert_not_called()


class TestHydrateProducts:

    def test_extracts_latest_prices_without_history(self):
        coll = MagicMock()
        coll.find.return_value = [_product("123", 599, discount=499)]
        result = hydrate_products(coll, ["123"])
        assert result[0]["tpnc"] == "123"
        assert result[0]["last_scraped_price"] == 599
        assert result[0]["discount_price"] == 499
        assert "price_history" not in result[0]

    def test_empty_ids_do_not_query(self):
        coll = MagicMock()
        assert hydrate_products(coll, []) == []
        coll.find.assert_not_called()

    def test_minimal_document(self):
        coll = MagicMock()
        coll.find.return_value = [{"_id": "456", "name": "Minimal"}]
        result = hydrate_products(coll, ["456"])
        assert result[0]["tpnc"] == "456"
        assert result[0]["name"] == "Minimal"


class TestPointId:

    def test_deterministic_and_distinct(self):
        assert _point_id("123") == _point_id("123")
        assert _point_id("123") != _point_id("456")

    def test_matches_the_vectorizer_point_for_the_tesco_ref(self):
        from stores import semantic

        assert _point_id("123") == semantic.point_id("tesco:123")


class TestPersonalizedFlow:

    @patch("recommendation_engine.search_category_bucket")
    @patch("recommendation_engine.resolve_product_categories")
    @patch("recommendation_engine.get_user_alert_details")
    def test_personalized_results_are_deduplicated_and_filled(self, alerts, categories, bucket):
        alerts.return_value = [
            {"productId": "tracked1", "createdAt": 1},
            {"productId": "tracked2", "createdAt": 2},
        ]
        categories.return_value = {"tracked1": "Italok", "tracked2": "Pékáru"}
        # The same candidate from both categories must only be shown once.
        bucket.return_value = [{"product_id": "rec1", "score": 0.9}, {"product_id": "rec2", "score": 0.5}]

        coll = MagicMock()
        coll.find.return_value = [_product("rec1", 500, discount=400), _product("rec2", 300)]
        coll.aggregate.return_value = [{"tpnc": "filler"}]

        result = get_recommendations(coll, user_id="user-1", limit=4)

        tpncs = [r["tpnc"] for r in result["recommendations"]]
        assert result["type"] == "personalized"
        assert result["personalized_count"] == 2
        assert tpncs[:2] == ["rec1", "rec2"]
        assert len(tpncs) == len(set(tpncs))
        assert tpncs[-1] == "filler"
        cold_start_match = next(
            stage["$match"] for stage in coll.aggregate.call_args.args[0] if "$match" in stage
        )
        assert set(cold_start_match["tpnc"]["$nin"]) >= {"tracked1", "tracked2", "rec1", "rec2"}

    @patch("recommendation_engine.resolve_product_categories")
    @patch("recommendation_engine.get_user_alert_details")
    def test_no_vectors_falls_back_to_cold_start(self, alerts, categories):
        alerts.return_value = [{"productId": "tracked1", "createdAt": 1}]
        categories.return_value = {}
        coll = MagicMock()
        coll.aggregate.return_value = [{"tpnc": "deal"}]
        assert get_recommendations(coll, user_id="user-1", limit=10)["type"] == "cold_start"

    @patch("recommendation_engine.get_user_alert_details")
    def test_user_without_alerts_gets_cold_start(self, alerts):
        alerts.return_value = []
        coll = MagicMock()
        coll.aggregate.return_value = []
        assert get_recommendations(coll, user_id="user-1", limit=10)["type"] == "cold_start"

    @patch("recommendation_engine.resolve_product_categories")
    @patch("recommendation_engine.get_user_alert_details")
    def test_unexpected_error_degrades_to_cold_start(self, alerts, categories):
        alerts.return_value = [{"productId": "tracked1", "createdAt": 1}]
        categories.side_effect = RuntimeError("qdrant refused")
        coll = MagicMock()
        coll.aggregate.return_value = [{"tpnc": "fallback"}]
        result = get_recommendations(coll, user_id="user-1", limit=10)
        assert result["type"] == "cold_start"
        assert result["recommendations"] == [{"tpnc": "fallback"}]
