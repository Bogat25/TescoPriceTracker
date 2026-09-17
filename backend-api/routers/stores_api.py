"""Store-neutral catalogue endpoints.

``stores`` selects stores by ID (comma separated); empty means every enabled
store. A disabled store behaves as if it did not exist for users.
"""

import logging
import re

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from stores import insights, queries, semantic
from stores.browse import SORT_FIELDS
from stores.ids import InvalidReference, parse_ref
from stores.registry import DisabledStore, UnknownStore, registry


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")

# Endpoints that predate the store layer and only serve Tesco data.
_TESCO_ONLY_PATHS = re.compile(r"^/(api/v1/(products|stats|recommendations)(/|$)|(?!openapi\.json$)[^/]+\.json$)")


def tesco_switch_middleware():
    """Answer the Tesco-only legacy endpoints with 404 while Tesco is disabled."""

    async def middleware(request: Request, call_next):
        if _TESCO_ONLY_PATHS.match(request.url.path):
            enabled = await run_in_threadpool(registry.is_enabled, "tesco")
            if not enabled:
                return JSONResponse({"detail": "store not available: tesco"}, status_code=404)
        return await call_next(request)

    return middleware


def resolve_stores(stores: str) -> list:
    try:
        return registry.resolve(stores)
    except UnknownStore as exc:
        raise HTTPException(400, f"unknown store: {exc.args[0]}") from exc
    except DisabledStore as exc:
        raise HTTPException(404, f"store not available: {exc.args[0]}") from exc


def _enabled_ref(ref: str) -> str:
    try:
        store_id, _ = parse_ref(ref)
    except InvalidReference as exc:
        raise HTTPException(400, "invalid offer reference") from exc
    if store_id not in queries.ADAPTERS or not registry.is_enabled(store_id):
        raise HTTPException(404, "offer not found")
    return ref


@router.get("/stores")
def list_stores():
    return {"stores": [store.public() for store in registry.enabled()]}


@router.get("/search")
def search(
    q: str = Query(min_length=1, max_length=200),
    stores: str = Query(default=""),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    mode: str = Query(default="hybrid", pattern="^(" + "|".join(queries.SEARCH_MODES) + ")$"),
    min_score: float | None = Query(default=None, ge=0.0, le=1.0),
):
    """``mode``: ``hybrid`` (text and meaning, fused), ``semantic`` or ``text``.
    The response's ``mode`` says what answered: text when vectors are unavailable."""
    store_ids = resolve_stores(stores)
    try:
        return queries.search(store_ids, q.strip(), skip, limit, mode, min_score)
    except queries.WindowTooLarge as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/browse")
def browse(
    stores: str = Query(default=""),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    sort_by: str = Query(default="name", pattern="^(" + "|".join(SORT_FIELDS) + ")$"),
    sort_dir: str = Query(default="asc", pattern="^(asc|desc)$"),
):
    store_ids = resolve_stores(stores)
    try:
        return queries.browse(store_ids, skip, limit, sort_by, sort_dir)
    except queries.WindowTooLarge as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/offers/{ref}")
def get_offer(ref: str):
    offer = queries.get_offer(_enabled_ref(ref))
    if offer is None:
        raise HTTPException(404, "offer not found")
    return offer


@router.get("/offers/{ref}/history")
def get_offer_history(ref: str):
    history = queries.get_history(_enabled_ref(ref))
    if history is None:
        raise HTTPException(404, "offer not found")
    return {"ref": ref, "history": history}


@router.get("/groups/{group_id}")
def get_group(group_id: str, stores: str = Query(default="")):
    row = queries.get_group(group_id, resolve_stores(stores))
    if row is None:
        raise HTTPException(404, "product not found")
    return row


@router.get("/groups/{group_id}/history")
def get_group_history(group_id: str, stores: str = Query(default="")):
    history = queries.get_group_history(group_id, resolve_stores(stores))
    if history is None:
        raise HTTPException(404, "product not found")
    return history


# -- similar products ---------------------------------------------------------------

def _similar(result):
    if result is None:
        return {"results": [], "stores": []}
    return result


@router.get("/offers/{ref}/similar")
def get_offer_similar(ref: str, stores: str = Query(default=""), limit: int = Query(default=12, ge=1, le=48)):
    store_ids = resolve_stores(stores)
    try:
        return _similar(queries.similar(store_ids, limit, ref=_enabled_ref(ref)))
    except semantic.SemanticUnavailable as exc:
        raise HTTPException(503, "similar products are temporarily unavailable") from exc


@router.get("/groups/{group_id}/similar")
def get_group_similar(group_id: str, stores: str = Query(default=""), limit: int = Query(default=12, ge=1, le=48)):
    store_ids = resolve_stores(stores)
    try:
        return _similar(queries.similar(store_ids, limit, group_id=group_id))
    except semantic.SemanticUnavailable as exc:
        raise HTTPException(503, "similar products are temporarily unavailable") from exc


# -- statistics -------------------------------------------------------------------------

@router.get("/insights")
def get_insights(stores: str = Query(default="")):
    """Per-store statistics (index, counts, tiers, channels, weekdays, volatility, inflation)."""
    by_store = {}
    for store_id in resolve_stores(stores):
        data = dict(insights.store_insights(store_id))
        data.pop("top_discounts", None)
        data.pop("price_drops", None)
        by_store[store_id] = data
    return {"stores": list(by_store), "by_store": by_store}


def _merged_list(stores: str, field: str, sort_field: str, limit: int) -> dict:
    items = []
    store_ids = resolve_stores(stores)
    for store_id in store_ids:
        items.extend(dict(item, store=store_id) for item in insights.store_insights(store_id)[field])
    items.sort(key=lambda item: item[sort_field], reverse=True)
    return {"stores": store_ids, "results": items[:limit]}


@router.get("/insights/top-discounts")
def get_top_discounts(stores: str = Query(default=""), limit: int = Query(default=100, ge=1, le=500)):
    """Today's promotions across the selected stores, biggest discount first."""
    return _merged_list(stores, "top_discounts", "pct_off", limit)


@router.get("/insights/price-drops")
def get_price_drops(stores: str = Query(default=""), limit: int = Query(default=100, ge=1, le=500)):
    """Regular prices lower today than yesterday, biggest drop first."""
    return _merged_list(stores, "price_drops", "drop_pct", limit)


@router.get("/insights/compare")
def get_comparison(stores: str = Query(default="")):
    """Stores compared on the products they all sell (linked by barcode)."""
    store_ids = resolve_stores(stores)
    if len(store_ids) < 2:
        raise HTTPException(400, "comparison needs at least two enabled stores")
    return insights.comparison(store_ids)

