"""Data preparation utilities for the recommendation system.

Extracts relevant text fields from raw MongoDB product documents and
formats them into a cohesive prompt string suitable for the E5 embedding model.
"""

from typing import Optional

# Fields whose text content we want to exclude from embedding
_EXCLUDED_LEGAL_PREFIXES = (
    "While every care has been taken",
    "If you have any queries",
    "Although product information",
    "This information is supplied for personal use",
)


def _join_list(val) -> str:
    """Safely join a list or return the string as-is."""
    if isinstance(val, list):
        return " ".join(str(v) for v in val if v)
    if isinstance(val, str):
        return val
    return ""


def _filter_legal(texts: list) -> list:
    """Remove generic legal notices from a list of strings."""
    return [
        t for t in texts
        if isinstance(t, str) and not any(t.startswith(p) for p in _EXCLUDED_LEGAL_PREFIXES)
    ]


def build_embedding_text(product: dict) -> Optional[str]:
    """Build the concatenated text string for a product document.

    Follows the blueprint specification:
    - Included: name, brand_name, sub_brand, nested categories, marketing, other_information/features
    - Excluded: dynamic data (prices), IDs, URLs, legal notices

    Returns None if the product has insufficient text to embed.
    """
    parts: list[str] = []

    # Product name
    name = product.get("name")
    if name:
        parts.append(name.strip())

    # Brand
    brand = product.get("brand_name", "")
    sub_brand = product.get("sub_brand", "")
    if brand:
        brand_str = f"Márka: {brand}"
        if sub_brand:
            brand_str += f" ({sub_brand})"
        parts.append(brand_str)

    # Category hierarchy (deepest nesting)
    categories = []
    for field in ("super_department_name", "department_name", "aisle_name", "shelf_name"):
        val = product.get(field)
        if val and val not in categories:
            categories.append(val)
    if categories:
        parts.append(f"Kategória: {', '.join(categories)}")

    # Short description
    short_desc = product.get("short_description")
    if short_desc:
        parts.append(short_desc.strip())

    # Marketing text
    marketing = product.get("marketing") or product.get("product_marketing")
    if marketing:
        marketing_text = _join_list(marketing)
        if marketing_text:
            parts.append(f"Marketing: {marketing_text.strip()}")

    # Features
    features = product.get("features")
    if features:
        filtered = _filter_legal(features if isinstance(features, list) else [features])
        if filtered:
            parts.append(f"Jellemzők: {', '.join(filtered)}")

    # Nutritional claims (useful for food items)
    claims = product.get("nutritional_claims")
    if claims:
        filtered = _filter_legal(claims if isinstance(claims, list) else [claims])
        if filtered:
            parts.append(f"Összetétel: {', '.join(filtered)}")

    # Ingredients (brief — first 5)
    ingredients = product.get("ingredients")
    if isinstance(ingredients, list) and ingredients:
        parts.append(f"Összetevők: {', '.join(ingredients[:5])}")

    # If we have less than a name, skip
    if not parts or (len(parts) == 1 and len(parts[0]) < 5):
        return None

    return ". ".join(parts)
