import os
import hmac
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from mongo.products_catalog_manager import iter_changed_since, get_catalog_collection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/internal/catalog")

_TOKEN = os.environ.get("INTERNAL_TRIGGER_TOKEN", "")


def _check_token(request: Request):
    provided = request.headers.get("X-Internal-Token", "")
    if not _TOKEN or not provided:
        raise HTTPException(status_code=401, detail="Missing internal token")
    if not hmac.compare_digest(provided, _TOKEN):
        raise HTTPException(status_code=403, detail="Invalid internal token")


@router.get("/products")
def list_catalog_products(
    request: Request,
    since: str = Query(default="1970-01-01T00:00:00Z"),
    limit: int = Query(default=1000, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
):
    _check_token(request)

    try:
        since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ISO 8601 date for 'since'")

    products = list(iter_changed_since(since_dt, limit=limit + 1, offset=offset))

    has_more = len(products) > limit
    if has_more:
        products = products[:limit]

    return {
        "products": products,
        "next_offset": offset + limit if has_more else None,
        "server_time": datetime.utcnow().isoformat() + "Z",
    }
