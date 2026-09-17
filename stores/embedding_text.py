"""The text each store's product is embedded from.

Only descriptive fields go in: name, brand, categories, descriptions and a
short ingredient list. Prices, IDs, URLs and legal boilerplate stay out, so a
vector changes only when what the product *is* changes. Labels are Hungarian
because the product texts are.
"""

from typing import Optional

MAX_CHARS = 2000  # ~500 tokens; the model reads at most 512

_EXCLUDED_LEGAL_PREFIXES = (
    "While every care has been taken",
    "If you have any queries",
    "Although product information",
    "This information is supplied for personal use",
)

TESCO_FIELDS = (
    "name", "brand_name", "sub_brand", "super_department_name", "department_name", "aisle_name",
    "shelf_name", "short_description", "marketing", "product_marketing", "features",
    "nutritional_claims", "ingredients",
)
AUCHAN_FIELDS = ("name", "brand", "category_path", "description", "ingredients")


def _join_list(value) -> str:
    if isinstance(value, list):
        return " ".join(str(v) for v in value if v)
    return value if isinstance(value, str) else ""


def _filter_legal(texts: list) -> list:
    return [t for t in texts if isinstance(t, str) and not any(t.startswith(p) for p in _EXCLUDED_LEGAL_PREFIXES)]


def _finish(parts: list) -> Optional[str]:
    parts = [part.rstrip(" .") for part in parts if part and part.rstrip(" .")]
    if not parts or (len(parts) == 1 and len(parts[0]) < 5):
        return None
    return ". ".join(parts)[:MAX_CHARS]


def tesco_text(product: dict) -> Optional[str]:
    parts: list = []
    name = product.get("name")
    if name:
        parts.append(name.strip())

    brand = product.get("brand_name", "")
    if brand:
        sub_brand = product.get("sub_brand", "")
        parts.append(f"Márka: {brand}" + (f" ({sub_brand})" if sub_brand else ""))

    categories = []
    for field in ("super_department_name", "department_name", "aisle_name", "shelf_name"):
        value = product.get(field)
        if value and value not in categories:
            categories.append(value)
    if categories:
        parts.append(f"Kategória: {', '.join(categories)}")

    short_desc = product.get("short_description")
    if isinstance(short_desc, str) and short_desc.strip():
        parts.append(short_desc.strip())

    marketing = _join_list(product.get("marketing") or product.get("product_marketing"))
    if marketing.strip():
        parts.append(f"Marketing: {marketing.strip()}")

    features = product.get("features")
    if features:
        filtered = _filter_legal(features if isinstance(features, list) else [features])
        if filtered:
            parts.append(f"Jellemzők: {', '.join(filtered)}")

    claims = product.get("nutritional_claims")
    if claims:
        filtered = _filter_legal(claims if isinstance(claims, list) else [claims])
        if filtered:
            parts.append(f"Összetétel: {', '.join(filtered)}")

    ingredients = product.get("ingredients")
    if isinstance(ingredients, list) and ingredients:
        parts.append(f"Összetevők: {', '.join(str(i) for i in ingredients[:5])}")

    return _finish(parts)


def auchan_text(product: dict) -> Optional[str]:
    parts: list = []
    name = product.get("name")
    if name:
        parts.append(name.strip())
    if product.get("brand"):
        parts.append(f"Márka: {product['brand']}")
    categories = [c for c in product.get("category_path") or [] if c]
    if categories:
        parts.append(f"Kategória: {', '.join(categories)}")
    description = product.get("description")
    if isinstance(description, str) and description.strip():
        parts.append(description.strip()[:800])
    ingredients = product.get("ingredients")
    if isinstance(ingredients, str) and ingredients.strip():
        parts.append(f"Összetevők: {ingredients.strip()[:300]}")
    return _finish(parts)
