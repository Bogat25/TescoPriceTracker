"""Store-neutral catalogue endpoints.

``stores`` selects stores by ID (comma separated); empty means every enabled
store. A disabled store behaves as if it did not exist for users.
"""

import logging
import re

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from stores import queries
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


def _resolve_stores(stores: str) -> list:
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
):
    store_ids = _resolve_stores(stores)
    try:
        return queries.search(store_ids, q.strip(), skip, limit)
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
    store_ids = _resolve_stores(stores)
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
