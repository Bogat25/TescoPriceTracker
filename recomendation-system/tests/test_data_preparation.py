"""Unit tests for the data preparation / string construction logic."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from data_preparation import build_embedding_text


class TestBuildEmbeddingText:
    """Test suite for the AI prompt string construction."""

    def test_full_product(self):
        """Complete product should produce a well-formatted string."""
        product = {
            "name": "Tesco Home rozsdamentes acél termosz 1 literes",
            "brand_name": "TESCO",
            "sub_brand": "Home",
            "super_department_name": "Otthon-hobbi",
            "department_name": "Otthon",
            "aisle_name": "Konyha és étkező",
            "shelf_name": "Kulacsok és termoszok",
            "short_description": "Rozsdamentes acél termosz.",
            "marketing": ["Szigetelt", "Szivárgásmentes"],
            "features": ["A meleget 5 órán keresztül tartja", "Anyagösszetétel: rozsdamentes acél"],
        }
        result = build_embedding_text(product)

        assert result is not None
        assert "Tesco Home rozsdamentes acél termosz 1 literes" in result
        assert "Márka: TESCO (Home)" in result
        assert "Kategória: Otthon-hobbi, Otthon, Konyha és étkező, Kulacsok és termoszok" in result
        assert "Rozsdamentes acél termosz" in result
        assert "Marketing: Szigetelt Szivárgásmentes" in result
        assert "Jellemzők:" in result

    def test_minimal_product(self):
        """Product with only a name should still produce output."""
        product = {"name": "Tej 2.8% 1 liter"}
        result = build_embedding_text(product)
        assert result is not None
        assert "Tej 2.8% 1 liter" in result

    def test_empty_product(self):
        """Product with no useful fields returns None."""
        product = {}
        result = build_embedding_text(product)
        assert result is None

    def test_only_id_fields(self):
        """Product with only ID-like fields returns None."""
        product = {"tpnc": "123456", "_id": "123456"}
        result = build_embedding_text(product)
        assert result is None

    def test_excludes_prices(self):
        """Dynamic data (prices) should NOT be in the embedding text."""
        product = {
            "name": "Test Product",
            "last_scraped_price": "2024-01-01T00:00:00",
            "price_history": [{"date": "2024-01-01", "normal": {"price": 999}}],
        }
        result = build_embedding_text(product)
        assert result is not None
        assert "999" not in result
        assert "price" not in result.lower()

    def test_excludes_urls(self):
        """URLs should NOT be in the embedding text."""
        product = {
            "name": "Test Product",
            "default_image_url": "https://example.com/image.jpg",
        }
        result = build_embedding_text(product)
        assert result is not None
        assert "https://" not in result
        assert "image.jpg" not in result

    def test_excludes_legal_notices(self):
        """Standard legal notices should be filtered out."""
        product = {
            "name": "Test Product",
            "features": [
                "Useful feature",
                "While every care has been taken to ensure product information is correct",
                "This information is supplied for personal use only",
            ],
        }
        result = build_embedding_text(product)
        assert result is not None
        assert "Useful feature" in result
        assert "While every care" not in result
        assert "personal use" not in result

    def test_category_deduplication(self):
        """Duplicate category names should not repeat."""
        product = {
            "name": "Test Product",
            "super_department_name": "Italok",
            "department_name": "Italok",  # Same as super
            "aisle_name": "Gyerek italok",
            "shelf_name": "Gyerek italok",  # Same as aisle
        }
        result = build_embedding_text(product)
        assert result is not None
        # "Italok" should appear once, "Gyerek italok" should appear once
        category_part = [p for p in result.split(". ") if "Kategória:" in p][0]
        assert category_part.count("Italok") == 1
        assert category_part.count("Gyerek italok") == 1

    def test_marketing_as_list(self):
        """Marketing field as list should be joined."""
        product = {
            "name": "Test",
            "marketing": ["Feature 1", "Feature 2"],
        }
        result = build_embedding_text(product)
        assert "Feature 1" in result
        assert "Feature 2" in result

    def test_marketing_as_string(self):
        """Marketing field as string should work."""
        product = {
            "name": "Test",
            "marketing": "Single marketing text",
        }
        result = build_embedding_text(product)
        assert "Single marketing text" in result

    def test_ingredients_limited(self):
        """Only first 5 ingredients should be included."""
        product = {
            "name": "Test",
            "ingredients": ["A", "B", "C", "D", "E", "F", "G", "H"],
        }
        result = build_embedding_text(product)
        assert "A" in result
        assert "E" in result
        assert "F" not in result

    def test_product_marketing_fallback(self):
        """product_marketing field should be used if marketing is absent."""
        product = {
            "name": "Test",
            "product_marketing": ["Fallback marketing"],
        }
        result = build_embedding_text(product)
        assert "Fallback marketing" in result

    def test_nutritional_claims(self):
        """Nutritional claims should be included."""
        product = {
            "name": "Test",
            "nutritional_claims": ["Hozzáadott cukrot nem tartalmaz", "C-vitaminban gazdag"],
        }
        result = build_embedding_text(product)
        assert "Hozzáadott cukrot nem tartalmaz" in result
        assert "C-vitaminban gazdag" in result

    def test_short_name_only_returns_none(self):
        """Very short name alone (< 5 chars) returns None."""
        product = {"name": "Ab"}
        result = build_embedding_text(product)
        assert result is None

    def test_real_product_example(self):
        """Test with a real product document structure."""
        product = {
            "tpnc": "120602217",
            "name": "Kubu 100% alma-banán püré C-vitaminnal 100 g",
            "brand_name": "Kubu",
            "super_department_name": "Italok",
            "department_name": "Gyümölcs és zöldséglevek",
            "aisle_name": "Gyerek italok",
            "shelf_name": "Gyerek italok",
            "short_description": "Alma-banán püré C-vitaminnal.",
            "marketing": [
                "Élelmirost forrás.",
                "Nem tartalmaz sem aromát, sem hozzáadott cukrot."
            ],
            "features": [
                "Hozzáadott cukrot nem tartalmaz",
                "Természetes módon előforduló cukrokat tartalmaz",
            ],
            "nutritional_claims": [
                "Hozzáadott cukrot nem tartalmaz",
                "C-vitaminban gazdag, élelmirost forrás"
            ],
            "ingredients": [
                "Almapüré (88%)",
                "Banánpüré (6%)",
                "Almalé sűrítményből (6%)",
                "C-vitamin (L-aszkorbinsav)",
                "Gyümölcstartalom: 100%."
            ],
            "price_history": [{"date": "2024-01-01", "normal": {"price": 399}}],
            "default_image_url": "https://cdn.tesco.com/image.jpg",
        }
        result = build_embedding_text(product)
        assert result is not None
        # Should contain the essential product info
        assert "Kubu" in result
        assert "alma-banán" in result
        assert "Italok" in result
        assert "Gyerek italok" in result
        # Should NOT contain prices or URLs
        assert "399" not in result
        assert "cdn.tesco.com" not in result
