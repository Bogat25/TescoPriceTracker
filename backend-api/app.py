import os
from datetime import datetime
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mongo import database_manager as db
from mongo import stats_manager
import uvicorn

app = FastAPI(title="Tesco Price Tracker API", version="2.0", default_response_class=JSONResponse)

allowed_origins = os.getenv("ALLOWED_ORIGINS", "").split(",")
if not allowed_origins or allowed_origins == [""]:
    allowed_origins = ["*"] # fallback if not specified

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    db.init_db()

@app.get("/health")
@app.get("/api/v1/health")
def health_check():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Cache helper
# ---------------------------------------------------------------------------

def _get_stat(key: str, compute_fn, *args):
    """Read from stats_cache; compute on-demand and store if missing."""
    data = db.get_cached_stat(key)
    if data is None:
        data = compute_fn(*args)
        db.set_cached_stat(key, data)
    return data


# ---------------------------------------------------------------------------
# v1 Product endpoints
# ---------------------------------------------------------------------------

@app.get("/api/v1/products")
def list_product_ids(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Return a paginated list of all product TPNCs."""
    return db.get_all_product_ids(skip=skip, limit=limit)


@app.get("/api/v1/products/browse")
def browse_products(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    sort_by: str = Query(default="name", regex="^(name|price|discount)$"),
    sort_dir: str = Query(default="asc", regex="^(asc|desc)$"),
):
    """Return paginated product summaries for the catalogue view (no price history)."""
    return db.browse_products(skip=skip, limit=limit, sort_by=sort_by, sort_dir=sort_dir)


@app.get("/api/v1/products/search")
def search_products(
    q: str = Query(default="", min_length=1),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=10000),
):
    """Full-text / regex search. Returns up to 100 results (paged) with current price."""
    return db.search_products(q, skip=skip, limit=limit)


_SLIM_FIELDS = {"tpnc", "name", "default_image_url", "last_scraped_price",
                "pack_size_value", "pack_size_unit", "unit_of_measure", "brand_name"}


@app.get("/api/v1/products/search/slim")
def search_products_slim(
    q: str = Query(default="", min_length=1),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=10000),
):
    """Like /search but returns only the fields needed to render search-result cards."""
    full = db.search_products(q, skip=skip, limit=limit)
    slim_results = [{k: v for k, v in r.items() if k in _SLIM_FIELDS} for r in full["results"]]
    return {"results": slim_results, "total": full["total"], "skip": full["skip"], "limit": full["limit"]}


@app.get("/api/v1/products/catalogue/search")
def catalogue_search_products(
    q: str = Query(default="", min_length=1),
    super_department: str = Query(default=""),
    department: str = Query(default=""),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=64, ge=1, le=200),
):
    """Category-aware search for the Product Catalogue page.

    Respects the active super_department / department filter pills so results
    stay within the currently selected category.
    """
    return db.search_products_with_category(
        q,
        super_department=super_department or None,
        department=department or None,
        skip=skip,
        limit=limit,
    )


@app.get("/api/v1/products/{tpnc}/trend")
def get_product_trend(tpnc: str):
    """Price trend for a single product — cheap, computed on-demand.

    Returns {tpnc, name, history: [{date, normal, discount, clubcard}]}
    """
    prod = db.get_product(tpnc)
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    history = list(reversed(prod.get("price_history", [])))
    return {
        "tpnc":    tpnc,
        "name":    prod.get("name"),
        "history": history,
    }


@app.get("/api/v1/products/{tpnc}/history")
def get_product_history(tpnc: str):
    """Return price history as {tpnc, points:[{timestamp, price}]} for charting."""
    if not db.product_exists(tpnc):
        raise HTTPException(status_code=404, detail="Product not found")
    raw = list(reversed(db.get_price_history(tpnc)))  # oldest → newest
    points = []
    for entry in raw:
        normal = entry.get("normal")
        if normal and normal.get("price") is not None:
            points.append({"timestamp": entry.get("date", ""), "price": normal["price"]})
    return {"tpnc": tpnc, "points": points}


@app.get("/api/v1/products/{tpnc}/stats")
def get_product_stats(tpnc: str):
    """Return price stats. Flat min/max/avg/current (normal channel primary) plus per-category breakdown."""
    stats = db.get_product_stats(tpnc)
    if not stats:
        raise HTTPException(status_code=404, detail="Product not found")
    primary = stats.get("normal") or stats.get("discount") or stats.get("clubcard") or {}
    return {
        "tpnc": stats["tpnc"],
        "min": primary.get("min_price"),
        "max": primary.get("max_price"),
        "avg": primary.get("avg_price"),
        "current": primary.get("current_price"),
        "pointCount": stats.get("total_days"),
        "name": stats.get("name"),
        "first_date": stats.get("first_date"),
        "last_date": stats.get("last_date"),
        "normal": stats.get("normal"),
        "discount": stats.get("discount"),
        "clubcard": stats.get("clubcard"),
    }


def _daily_to_channel_history(history_list: list) -> dict:
    """Transform [{date, normal:{price,...}, ...}] → {normal:[...], discount:[...], clubcard:[...]}."""
    channels: dict = {"normal": [], "discount": [], "clubcard": []}
    for entry in history_list:
        date_str = entry.get("date", "")
        for channel in channels:
            ch_data = entry.get(channel)
            if ch_data and ch_data.get("price") is not None:
                channels[channel].append({
                    "price": ch_data["price"],
                    "unit_price": ch_data.get("unit_price"),
                    "unit_measure": ch_data.get("unit_measure"),
                    "start_date": date_str,
                    "end_date": date_str,
                    "promo_id": ch_data.get("promo_id"),
                    "promo_desc": ch_data.get("promo_desc"),
                })
    return channels


@app.get("/api/v1/products/{tpnc}")
def get_product(tpnc: str):
    """Return lightweight product document for the browser extension."""
    prod = db.get_product(tpnc)
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    
    raw_history = prod.get("price_history", []) or []
    if isinstance(raw_history, list):
        history = _daily_to_channel_history(raw_history)
    else:
        history = {"normal": [], "discount": [], "clubcard": []}
        
    # Inject the numeric current price (extracted from price_history) so the
    # frontend's parsePrice() can parse it. The stored last_scraped_price field
    # is a scrape-timestamp string, not a price number.
    price_info = db._extract_price_details(prod)
    return {
        "tpnc": prod.get("tpnc"),
        "name": prod.get("name"),
        "unit_of_measure": prod.get("unit_of_measure"),
        "default_image_url": prod.get("default_image_url"),
        "pack_size_value": prod.get("pack_size_value"),
        "pack_size_unit": prod.get("pack_size_unit"),
        "last_scraped_price": price_info.get("last_scraped_price"),
        "discount_price": price_info.get("discount_price"),
        "clubcard_price": price_info.get("clubcard_price"),
        "unit_price": price_info.get("unit_price"),
        "unit_measure": price_info.get("unit_measure"),
        "price_history": history
    }

@app.get("/api/v1/products/{tpnc}/detailed")
def get_product_detailed(tpnc: str):
    """Return full rich product document for the web frontend."""
    prod = db.get_product(tpnc)
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    prod.pop("_id", None)
    # Inject numeric current price before popping price_history
    price_info = db._extract_price_details(prod)
    prod.update(price_info)
    raw_history = prod.pop("price_history", []) or []
    if isinstance(raw_history, list):
        prod["price_history"] = _daily_to_channel_history(raw_history)
    else:
        prod["price_history"] = {"normal": [], "discount": [], "clubcard": []}
    return prod


# ---------------------------------------------------------------------------
# v1 Platform-wide statistics (served from stats_cache)
# ---------------------------------------------------------------------------

@app.get("/api/v1/stats/price-index")
def stats_price_index():
    """Daily platform price index normalized to 100 at the earliest tracked date."""
    return _get_stat("price_index", stats_manager.compute_price_index)


@app.get("/api/v1/stats/product-volume")
def stats_product_volume():
    """Total, active today, and historical-only product counts."""
    return _get_stat("product_counts", stats_manager.compute_product_counts)


@app.get("/api/v1/stats/price-tiers")
def stats_price_tiers():
    """Count of products in each price tier based on latest normal price."""
    return _get_stat("price_tiers", stats_manager.compute_price_tiers)


@app.get("/api/v1/stats/category-diff")
def stats_category_diff():
    """Avg normal / discount / clubcard prices and % differences."""
    return _get_stat("category_diff", stats_manager.compute_category_diff)


@app.get("/api/v1/stats/top-discounts")
def stats_top_discounts(date: str = Query(default=None)):
    """All discounted products on a given date, grouped by % off (desc).

    Defaults to today. Pass ?date=YYYY-MM-DD for a historical date.
    Historical dates are computed on-demand (not pre-cached).
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    cache_key = f"top_discounts_{date}"
    return _get_stat(cache_key, stats_manager.compute_top_discounts, date)


@app.get("/api/v1/stats/best-shopping-day")
def stats_best_shopping_day():
    """The single date historically with the highest total discount savings."""
    return _get_stat("best_shopping_day", stats_manager.compute_best_shopping_day)


@app.get("/api/v1/stats/discount-by-weekday")
def stats_discount_by_weekday():
    """Average discount % and event count per weekday (Mon–Sun)."""
    return _get_stat("discount_by_weekday", stats_manager.compute_discount_by_weekday)


@app.get("/api/v1/stats/volatility")
def stats_volatility():
    """Price volatility index per price tier (std-dev of last 30 days)."""
    return _get_stat("volatility_index", stats_manager.compute_volatility_index)


@app.get("/api/v1/stats/global-avg")
def stats_global_avg():
    """Mean of all products' latest normal price."""
    return _get_stat("global_avg", stats_manager.compute_global_avg)


@app.get("/api/v1/stats/inflation/30d")
def stats_inflation_30d():
    """% change in platform avg price between today and 30 days ago."""
    return _get_stat("inflation_30d", stats_manager.compute_inflation_30d)


@app.get("/api/v1/stats/price-drops/today")
def stats_price_drops_today():
    """Products whose normal price dropped today vs yesterday, sorted by drop %."""
    return _get_stat("price_drops_today", stats_manager.compute_price_drops_today)


# ---------------------------------------------------------------------------
# Legacy shim (browser extension compatibility)
# ---------------------------------------------------------------------------

@app.get("/{tpnc}.json")
def get_legacy_product_json(tpnc: str):
    """Compatibility shim for the existing browser extension."""
    prod = db.get_product(tpnc)
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    prod.pop("_id", None)
    return prod


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.getenv("API_PUBLIC_PORT", "50202")),
    )
