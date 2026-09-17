"""Helpers shared by store adapters that keep ``browse_sort`` fields."""

import re

from pymongo import ASCENDING, DESCENDING


SORT_FIELDS = ("name", "price", "discount")
SEARCH_MAX = 200


def browse_sort_spec(sort_by: str, sort_dir: str) -> list:
    direction = ASCENDING if sort_dir == "asc" else DESCENDING
    if sort_by == "price":
        return [("browse_sort.has_price", DESCENDING), ("browse_sort.effective_price", direction), ("name", ASCENDING)]
    if sort_by == "discount":
        return [("browse_sort.has_discount", DESCENDING), ("browse_sort.discount_ratio", direction), ("name", ASCENDING)]
    return [("name", direction)]


def text_search(collection, query: str, limit: int, projection: dict, id_fields=("_id",)) -> list:
    """Mongo text search, falling back to a case-insensitive substring match.

    The fallback catches partial words and IDs the text index does not. The
    user's input is escaped so it can never be run as a regular expression.
    """
    limit = max(1, min(limit, SEARCH_MAX))
    scored = dict(projection, score={"$meta": "textScore"})
    docs = list(
        collection.find({"$text": {"$search": query}}, scored)
        .sort([("score", {"$meta": "textScore"})])
        .limit(limit)
    )
    if docs:
        return docs
    pattern = {"$regex": re.escape(query), "$options": "i"}
    clauses = [{"name": pattern}] + [{field: pattern} for field in id_fields]
    return list(collection.find({"$or": clauses}, projection).limit(limit))
