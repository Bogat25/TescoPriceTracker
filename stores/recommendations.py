"""Store-aware recommendation rows.

Personal picks come from the Tesco vector engine (other stores are not
embedded yet); each pick is shown with the selected stores' offers for the
same barcode. Remaining slots are filled with the biggest current discounts
across the selected stores.
"""

from typing import Callable, Optional

from stores import queries, tesco


def _row_key(row: dict) -> str:
    return row["group_id"] or row["offers"][0]["ref"]


def personal_rows(engine_result: dict, store_ids: list) -> list:
    if not engine_result or engine_result.get("type") != "personalized":
        return []
    picks = engine_result.get("recommendations", [])[: engine_result.get("personalized_count", 0)]
    groups = queries._group_in_order(tesco.find_by_ids([str(pick.get("tpnc")) for pick in picks]))
    queries._fill_missing_stores(groups, store_ids)
    rows = []
    for offers in groups:
        selected = [offer for offer in offers if offer["store"] in store_ids]
        if selected:
            rows.append(queries.make_row(selected, store_ids))
    return rows


def rows(store_ids: list, limit: int, personal_picks: Optional[Callable[[], dict]] = None) -> dict:
    """``personal_picks`` returns the engine result, or is None for cold start."""
    results = []
    if personal_picks is not None and store_ids:
        results = personal_rows(personal_picks(), store_ids)[:limit]
    personalized = len(results)
    seen = {_row_key(row) for row in results}

    if len(results) < limit and store_ids:
        window = min(limit * 2, queries.MAX_WINDOW)
        for row in queries.browse(store_ids, 0, window, "discount", "desc")["results"]:
            if _row_key(row) in seen:
                continue
            seen.add(_row_key(row))
            results.append(row)
            if len(results) >= limit:
                break

    return {
        "type": "personalized" if personalized else "cold_start",
        "personalized_count": personalized,
        "results": results,
        "stores": store_ids,
    }
