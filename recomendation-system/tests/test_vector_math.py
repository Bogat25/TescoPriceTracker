"""Unit tests for the recommendation engine's vector maths and scoring."""

import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend-api'))

from recommendation_engine import (  # noqa: E402
    _compute_discount_fraction,
    allocate_slots,
    compute_mean_vector,
    score_and_rank_bucket,
)


class TestComputeMeanVector:

    def test_single_vector(self):
        assert compute_mean_vector([[1.0, 2.0, 3.0]]) == [1.0, 2.0, 3.0]

    def test_two_identical_vectors(self):
        vec = [0.5, -0.3, 0.8]
        assert compute_mean_vector([vec, vec]) == pytest.approx(vec)

    def test_two_different_vectors(self):
        assert compute_mean_vector([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]) == pytest.approx([0.5, 0.5, 0.0])

    def test_multiple_vectors(self):
        vectors = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
        assert compute_mean_vector(vectors) == pytest.approx([4.0, 5.0, 6.0])

    def test_negative_values_cancel(self):
        assert compute_mean_vector([[-1.0, 0.5, -0.5], [1.0, -0.5, 0.5]]) == pytest.approx([0.0, 0.0, 0.0])

    def test_model_dimension(self):
        rng = random.Random(42)
        v1 = [rng.uniform(-1, 1) for _ in range(384)]
        v2 = [rng.uniform(-1, 1) for _ in range(384)]
        result = compute_mean_vector([v1, v2])
        assert len(result) == 384
        assert result == pytest.approx([(a + b) / 2 for a, b in zip(v1, v2)], abs=1e-10)

    def test_empty_list_raises(self):
        with pytest.raises(ValueError, match="empty"):
            compute_mean_vector([])

    def test_zero_dimension_raises(self):
        with pytest.raises(ValueError, match="non-zero"):
            compute_mean_vector([[]])

    def test_dimension_mismatch_raises(self):
        with pytest.raises(ValueError, match="mismatch"):
            compute_mean_vector([[1.0, 2.0], [1.0, 2.0, 3.0]])


class TestAllocateSlots:

    @pytest.mark.parametrize("n, total, expected", [
        (3, 100, [34, 33, 33]),
        (5, 100, [20, 20, 20, 20, 20]),
        (1, 100, [100]),
        (4, 10, [3, 3, 2, 2]),
    ])
    def test_even_distribution_with_remainder_first(self, n, total, expected):
        assert allocate_slots(n, total) == expected

    def test_slots_always_sum_to_total(self):
        for n in range(1, 8):
            assert sum(allocate_slots(n, 97)) == 97

    def test_no_categories(self):
        assert allocate_slots(0, 100) == []


class TestDiscountFraction:

    def test_no_deal_is_zero(self):
        assert _compute_discount_fraction({"last_scraped_price": 1000}) == 0.0

    def test_discount_price(self):
        assert _compute_discount_fraction({"last_scraped_price": 1000, "discount_price": 800}) == pytest.approx(0.2)

    def test_best_of_discount_and_clubcard(self):
        product = {"last_scraped_price": 1000, "discount_price": 800, "clubcard_price": 600}
        assert _compute_discount_fraction(product) == pytest.approx(0.4)

    def test_deal_not_below_normal_is_zero(self):
        assert _compute_discount_fraction({"last_scraped_price": 500, "discount_price": 500}) == 0.0

    @pytest.mark.parametrize("normal", [0, None, "1000"])
    def test_unusable_normal_price_is_zero(self, normal):
        assert _compute_discount_fraction({"last_scraped_price": normal, "discount_price": 100}) == 0.0


class TestScoreAndRankBucket:

    def test_combines_similarity_and_discount_equally(self):
        hydrated = {
            "similar": {"tpnc": "similar", "last_scraped_price": 1000},
            "discounted": {"tpnc": "discounted", "last_scraped_price": 1000, "discount_price": 200},
        }
        candidates = [
            {"product_id": "similar", "score": 0.9},     # 0.45 + 0.0
            {"product_id": "discounted", "score": 0.3},  # 0.15 + 0.4
        ]
        ranked = score_and_rank_bucket(candidates, hydrated, slot_size=2)
        assert [p["tpnc"] for _, p in ranked] == ["discounted", "similar"]
        assert ranked[0][0] == pytest.approx(0.55)

    def test_trims_to_slot_size(self):
        hydrated = {str(i): {"tpnc": str(i), "last_scraped_price": 100} for i in range(5)}
        candidates = [{"product_id": str(i), "score": i / 10} for i in range(5)]
        assert len(score_and_rank_bucket(candidates, hydrated, slot_size=2)) == 2

    def test_skips_candidates_that_could_not_be_hydrated(self):
        ranked = score_and_rank_bucket([{"product_id": "missing", "score": 1.0}], {}, slot_size=5)
        assert ranked == []
