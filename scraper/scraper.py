import requests
import re
import time
import random
import os
import logging
import argparse
import concurrent.futures
import threading
from enum import Enum
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from lxml import etree  # type: ignore[import-untyped]
from config import API_URL, HEADERS, SITEMAP_INDEX_URL, DEFAULT_THREADS
from mongo.queries import FULL_PRODUCT_QUERY, PRICE_ONLY_QUERY
from mongo import database_manager as db
from mongo import stats_manager

# NOTE: structured logging is configured at the entrypoint that imports
# this module (scheduler.py calls setup_logging()). Don't call basicConfig
# here or it'll add a second handler that emits plain-text lines.
logger = logging.getLogger(__name__)


class ProductResult(str, Enum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


# Longest we will honour a Retry-After for. Beyond this the product is left for
# the next run rather than stalling the whole pass on one rate-limited item.
RETRY_AFTER_CAP_SECONDS = 120


class GraphQLContractError(RuntimeError):
    """The deployed query does not conform to Tesco's current schema."""


class UpstreamConfigurationError(RuntimeError):
    """Authentication or request configuration prevents all upstream calls."""


class RetryableUpstreamError(requests.RequestException):
    """Upstream is rate limiting or failing; carries its Retry-After when sent."""

    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


def _parse_retry_after(value):
    """Seconds from a Retry-After header, which may be a delay or an HTTP date.

    Capped because Tesco occasionally returns a very long penalty: waiting it out
    would stall the whole run, and the product is retried on the next pass anyway.
    """
    if not value:
        return None
    try:
        return min(float(value), RETRY_AFTER_CAP_SECONDS)
    except (TypeError, ValueError):
        pass
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if retry_at is None:
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
    return min(max(delay, 0.0), RETRY_AFTER_CAP_SECONDS) if delay > 0 else None


def _manufacturer_text(value):
    """Normalize Tesco's ManufacturerAddressType to the legacy display string."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        addresses = value.get("addresses")
        if isinstance(addresses, list):
            return ", ".join(str(part).strip() for part in addresses if part)
    return None


def _allergens_text(value):
    """Flatten the current allergen object list for the product detail view."""
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return None
    rendered = []
    for item in value:
        if isinstance(item, str):
            rendered.append(item)
            continue
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        values = item.get("values")
        if isinstance(values, list):
            values = ", ".join(str(entry) for entry in values if entry)
        text = ": ".join(str(part) for part in (name, values) if part)
        if text:
            rendered.append(text)
    return "; ".join(rendered) or None


# ---------------------------------------------------------------------------
# Skip-check: reads from MongoDB, no local file fallback.
# ---------------------------------------------------------------------------

def needs_scraping(tpnc):
    """Return True if *tpnc* has not been scraped today (calendar-day check)."""
    prod = db.get_product(tpnc)
    if not prod:
        return True
    last_scraped = prod.get('last_scraped_price')
    if not last_scraped:
        return True
    try:
        last_date = datetime.fromisoformat(last_scraped).date()
        return last_date < datetime.now().date()
    except (ValueError, AttributeError):
        return True


def is_today_scrape_done():
    """Advisory check used by the scheduler loop only."""
    state = db.load_run_state()
    if not state:
        return False
    return (state.get('date') == datetime.now().date().isoformat()
            and state.get('completed', False))


# ---------------------------------------------------------------------------
# Sitemap fetching
# ---------------------------------------------------------------------------

def fetch_sitemap_index(url):
    try:
        response = requests.get(url, headers={'User-Agent': HEADERS['User-Agent']}, timeout=30)
        response.raise_for_status()
        root = etree.fromstring(response.content)
        namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        locs = root.xpath('//ns:loc', namespaces=namespaces)
        return [loc.text for loc in locs]
    except (requests.RequestException, etree.XMLSyntaxError, OSError) as e:
        logger.error(f"Error fetching sitemap index: {e}")
        return []


def fetch_product_urls_from_sitemap(url):
    try:
        response = requests.get(url, headers={'User-Agent': HEADERS['User-Agent']}, timeout=30)
        response.raise_for_status()
        root = etree.fromstring(response.content)
        namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        locs = root.xpath('//ns:loc', namespaces=namespaces)
        product_ids = []
        for loc in locs:
            match = re.search(r'/products/(\d+)', loc.text)
            if match:
                product_ids.append(match.group(1))
        return product_ids
    except (requests.RequestException, etree.XMLSyntaxError, OSError) as e:
        logger.error(f"Error fetching sitemap {url}: {e}")
        return []


# ---------------------------------------------------------------------------
# Tesco GraphQL API call with exponential backoff
# ---------------------------------------------------------------------------

def get_product_api(tpnc, query_type="full"):
    if query_type == "full":
        query = FULL_PRODUCT_QUERY
        operation_name = "GetProduct"
    else:
        query = PRICE_ONLY_QUERY
        operation_name = "GetProductPrice"

    payload = [{
        "operationName": operation_name,
        "variables": {"tpnc": str(tpnc)},
        "extensions": {"mfeName": "mfe-pdp"},
        "query": query,
    }]

    max_retries = 5
    base_delay = 2

    for attempt in range(max_retries):
        try:
            response = requests.post(API_URL, headers=HEADERS, json=payload, timeout=30)
            if response.status_code in (401, 403):
                raise UpstreamConfigurationError(
                    f"Tesco API rejected configured credentials (HTTP {response.status_code})"
                )
            if response.status_code == 400:
                try:
                    error_body = response.json()
                except ValueError:
                    error_body = response.text[:500]
                raise GraphQLContractError(
                    f"Tesco GraphQL rejected {operation_name}: {error_body}"
                )
            if response.status_code == 429 or response.status_code >= 500:
                # Keep the server's own backoff instruction. Discarding it was why
                # a 429 burned all five attempts inside the penalty window.
                raise RetryableUpstreamError(
                    f"Retryable upstream HTTP {response.status_code}",
                    retry_after=_parse_retry_after(response.headers.get("Retry-After")),
                )
            response.raise_for_status()
            response_json = response.json()
            if isinstance(response_json, list) and len(response_json) > 0:
                result = response_json[0]
                errors = result.get("errors") if isinstance(result, dict) else None
                if errors:
                    raise GraphQLContractError(
                        f"Tesco GraphQL returned errors for {operation_name}: {errors}"
                    )
                return result
            # Not the retry path: the call succeeded but returned nothing usable.
            # Logged here so it stays visible now that the caller no longer
            # reports every None as a malformed response.
            logger.error(
                f"Empty response body for {tpnc} ({operation_name}). Response: {response_json}"
            )
            return None
        except (requests.RequestException, ValueError) as e:
            if attempt < max_retries - 1:
                sleep_time = base_delay * (2 ** attempt) + random.uniform(0, 1)
                # A rate limit is only cleared by waiting as long as the server
                # asked, so never back off for less than Retry-After.
                retry_after = getattr(e, "retry_after", None)
                if retry_after is not None:
                    sleep_time = max(sleep_time, retry_after)
                logger.warning(f"API request failed for {tpnc} (Attempt {attempt+1}/{max_retries}). "
                               f"Retrying in {sleep_time:.2f}s. Error: {e}")
                time.sleep(sleep_time)
            else:
                logger.error(f"API request failed for {tpnc} after {max_retries} attempts: {e}")
                if "Max retries exceeded" in str(e):
                    time.sleep(3)
                return None


# ---------------------------------------------------------------------------
# Process a single product
# ---------------------------------------------------------------------------

def process_product(tpnc, force=False, progress_prefix=""):
    """Fetch data for *tpnc* and store prices in all applicable categories.

    Returns a ProductResult so unavailable products and actual failures are not
    conflated with successful skips.
    """
    exists = db.product_exists(tpnc)

    if exists and not force and not needs_scraping(tpnc):
        logger.debug(f"{progress_prefix}Skipping {tpnc}: already up-to-date.")
        return ProductResult.SKIPPED

    # A forced run refreshes metadata as well as prices. Previously --force
    # still selected the price-only query for existing products, so schema and
    # metadata recovery could never repair them.
    query_type = "full" if force or not exists else "price"
    data = get_product_api(tpnc, query_type)
    if data is None:
        # get_product_api already logged the cause (rate limit, timeout, ...).
        # Calling this "malformed" duplicated every failure with a second, wrong
        # line that made upstream throttling look like a data problem.
        return ProductResult.FAILED
    if 'data' not in data:
        logger.error(f"{progress_prefix}Malformed response for {tpnc}. Response: {data}")
        return ProductResult.FAILED
    if not data['data'].get('product'):
        logger.info(f"{progress_prefix}Product {tpnc} is unavailable upstream.")
        return ProductResult.UNAVAILABLE

    product_data = data['data']['product']
    price_info = product_data.get('price')
    if not price_info:
        logger.info(f"{progress_prefix}No price info for {tpnc}, possibly unavailable.")
        return ProductResult.UNAVAILABLE

    price_actual = price_info.get('actual')
    unit_price = price_info.get('unitPrice')
    unit_measure = price_info.get('unitOfMeasure')
    promotions = product_data.get('promotions') or []

    # ---- Build price updates list (normal always included) ----
    price_updates = [("normal", {
        "price": price_actual,
        "unit_price": unit_price,
        "unit_measure": unit_measure,
    })]

    for promo in promotions:
        promo_id = promo.get('id')
        promo_desc = promo.get('description')
        promo_start = promo.get('startDate')
        promo_end = promo.get('endDate')
        attributes = promo.get('attributes') or []
        promo_price = None
        if promo.get('price'):
            promo_price = promo['price'].get('afterDiscount')

        if "CLUBCARD_PRICING" in attributes:
            cc_price = promo_price
            if promo_desc:
                clean_desc = promo_desc.replace('\xa0', '').replace(' ', '')
                match = re.search(r'(\d+)Ft', clean_desc, re.IGNORECASE)
                if match:
                    parsed_price = float(match.group(1))
                    if cc_price is None or cc_price == price_actual:
                        cc_price = parsed_price
            price_updates.append(("clubcard", {
                "price": cc_price,
                "unit_price": unit_price,
                "unit_measure": unit_measure,
                "promo_id": promo_id,
                "promo_desc": promo_desc,
                "promo_start": promo_start,
                "promo_end": promo_end,
            }))
        else:
            if promo_price and promo_price != price_actual:
                price_updates.append(("discount", {
                    "price": promo_price,
                    "unit_price": unit_price,
                    "unit_measure": unit_measure,
                    "promo_id": promo_id,
                    "promo_desc": promo_desc,
                    "promo_start": promo_start,
                    "promo_end": promo_end,
                }))

    # ---- Build metadata dict on first fetch ----
    metadata = None
    if query_type == "full":
        name = product_data.get('title')
        default_image_url = product_data.get('defaultImageUrl')
        details = product_data.get('details') or {}
        pack_size_val = None
        pack_size_unit = None
        pack_size = details.get('packSize')
        if isinstance(pack_size, list) and len(pack_size) > 0:
            pack_size_val = pack_size[0].get('value')
            pack_size_unit = pack_size[0].get('units')
        elif isinstance(pack_size, dict):
            pack_size_val = pack_size.get('value')
            pack_size_unit = pack_size.get('units')

        # Category / taxonomy
        primary_taxonomy = product_data.get('primaryTaxonomyNode') or {}

        # Reviews
        reviews_data = product_data.get('reviews') or {}
        reviews_stats = reviews_data.get('stats') or {}

        metadata = {
            "name": name,
            "unit_of_measure": unit_measure,
            "default_image_url": default_image_url,
            "pack_size_value": pack_size_val,
            "pack_size_unit": pack_size_unit,
            # Identifiers
            "tpnb": product_data.get('tpnb'),
            "gtin": product_data.get('gtin'),
            "barcode": product_data.get('barcode'),
            # Classification
            "brand_name": product_data.get('brandName'),
            "sub_brand": product_data.get('subBrand'),
            "product_type": product_data.get('productType'),
            "is_new": product_data.get('isNew'),
            "is_for_sale": product_data.get('isForSale'),
            "status": product_data.get('status'),
            "sell_type": product_data.get('sellType'),
            # Categories
            "super_department_name": product_data.get('superDepartmentName'),
            "super_department_id": product_data.get('superDepartmentId'),
            "department_name": product_data.get('departmentName'),
            "department_id": product_data.get('departmentId'),
            "aisle_name": product_data.get('aisleName'),
            "aisle_id": product_data.get('aisleId'),
            "shelf_name": product_data.get('shelfName'),
            "shelf_id": product_data.get('shelfId'),
            "taxonomy_id": primary_taxonomy.get('id'),
            "taxonomy_name": primary_taxonomy.get('name'),
            # Manufacturer / source
            "manufacturer": _manufacturer_text(product_data.get('manufacturer')),
            "manufacturer_address": product_data.get('manufacturerAddress'),
            "distributor_address": product_data.get('distributorAddress'),
            "importer_address": product_data.get('importerAddress'),
            "return_to": product_data.get('returnTo'),
            # Description / marketing
            "short_description": product_data.get('shortDescription'),
            "marketing": details.get('marketing'),
            "product_marketing": details.get('productMarketing'),
            "brand_marketing": details.get('brandMarketing'),
            "manufacturer_marketing": details.get('manufacturerMarketing'),
            # Nutrition & dietary
            "ingredients": details.get('ingredients'),
            "allergens": _allergens_text(details.get('allergens')),
            "nutrition": details.get('nutrition'),
            "gda": details.get('gda'),
            "dietary_info": details.get('dietaryInfo'),
            "intolerance_info": details.get('intoleranceInfo'),
            "health_claims": details.get('healthClaims'),
            "nutritional_claims": details.get('nutritionalClaims'),
            "hfss": details.get('hfss'),
            "additives": details.get('additives'),
            # Storage & preparation
            "storage": details.get('storage'),
            "preparation_and_usage": details.get('preparationAndUsage'),
            "preparation_guidelines": details.get('preparationGuidelines'),
            "freezing_instructions": details.get('freezingInstructions'),
            "shelf_life_info": details.get('shelfLifeInfo'),
            "storage_classification": product_data.get('storageClassification'),
            "shelf_life": product_data.get('shelfLife'),
            # Misc details
            "origin_information": details.get('originInformation'),
            "recycling_info": details.get('recyclingInfo'),
            "net_contents": details.get('netContents'),
            "drained_weight": details.get('drainedWeight'),
            "safety_warning": details.get('safetyWarning'),
            "warnings": details.get('warnings'),
            "lower_age_limit": details.get('lowerAgeLimit'),
            "upper_age_limit": details.get('upperAgeLimit'),
            "healthmark": details.get('healthmark'),
            "number_of_uses": details.get('numberOfUses'),
            "alcohol": details.get('alcohol'),
            "dosage": details.get('dosage'),
            "directions": details.get('directions'),
            "features": details.get('features'),
            "box_contents": details.get('boxContents'),
            "legal_notice": details.get('legalNotice'),
            "other_information": details.get('otherInformation'),
            # Product constraints
            "deposit_amount": product_data.get('depositAmount'),
            "max_quantity_allowed": product_data.get('maxQuantityAllowed'),
            "max_weight": product_data.get('maxWeight'),
            "min_weight": product_data.get('minWeight'),
            # Images & icons
            "display_images": product_data.get('displayImages'),
            "icons": product_data.get('icons'),
            # Reviews
            "overall_rating": reviews_stats.get('overallRating'),
            "overall_rating_range": reviews_stats.get('overallRatingRange'),
            "number_of_reviews": reviews_stats.get('noOfReviews'),
            "ratings_distribution": reviews_stats.get('ratingsDistribution'),
        }

        # Strip empty placeholders to save space
        def _is_empty(v):
            if v is None:
                return True
            if v == {} or v == [] or v == [{}]:
                return True
            if isinstance(v, list) and all(item == {} for item in v):
                return True
            return False

        metadata = {k: v for k, v in metadata.items() if not _is_empty(v)}

    # ---- Single load/save for all categories + optional metadata ----
    results = db.insert_daily_prices(tpnc, price_updates, metadata=metadata)

    if metadata:
        try:
            from mongo.products_catalog_manager import upsert_product_catalog
            catalog_meta = dict(metadata)
            catalog_meta["tpnc"] = str(tpnc)
            upsert_product_catalog(catalog_meta)
        except Exception:
            logger.warning("Catalog upsert failed for %s (non-fatal)", tpnc, exc_info=True)

    # ---- Logging ----
    change_status = "Changed" if any(results.values()) else "Unchanged"
    log_prices = [f"Normal: {price_actual}"]
    for category, fields in price_updates:
        if category == "discount":
            log_prices.append(f"Discount: {fields['price']}")
        elif category == "clubcard":
            log_prices.append(f"Clubcard: {fields['price']}")

    logger.info(f"{progress_prefix}Processed {tpnc} ({change_status}). {', '.join(log_prices)}")
    return ProductResult.SUCCESS


# ---------------------------------------------------------------------------
# Main scraper entry point
# ---------------------------------------------------------------------------

def run_scraper(specific_items=None, force=False, threads=DEFAULT_THREADS):
    """Run the scraper.

    - specific_items provided: always scrapes those items (no skip check).
    - No specific_items: skips products already scraped today (calendar-day).
    - force=True: scrapes everything regardless.
    """
    db.init_db()

    # ---- Build product ID list ----
    if specific_items:
        all_items = list(specific_items)
        logger.info(f"Processing {len(all_items)} specific items with {threads} threads...")
    else:
        sitemaps = fetch_sitemap_index(SITEMAP_INDEX_URL)
        logger.info(f"Found {len(sitemaps)} sitemaps.")
        all_product_ids = []
        for sitemap_url in sitemaps:
            time.sleep(0.5)
            logger.info(f"Fetching products from sitemap: {sitemap_url}")
            ids = fetch_product_urls_from_sitemap(sitemap_url)
            logger.info(f"Found {len(ids)} products in {sitemap_url}")
            all_product_ids.extend(ids)
        # Deduplicate
        all_items = list(dict.fromkeys(all_product_ids))
        logger.info(f"Total unique products discovered: {len(all_items)}")

    # ---- Sort by ascending numeric ID (lowest first) ----
    all_items.sort(key=lambda x: int(x))

    # ---- Filter: check each product in parallel ----
    # specific_items runs always; full runs skip products already done today.
    if force or specific_items:
        items_to_process = list(all_items)
    else:
        logger.info("Checking which products need scraping (parallel DB reads)...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as check_pool:
            check_results = list(check_pool.map(
                lambda tpnc: (tpnc, needs_scraping(tpnc)), all_items
            ))
        items_to_process = [tpnc for tpnc, needed in check_results if needed]

    logger.info(f"{len(items_to_process)} items to process (out of {len(all_items)} total).")

    if not items_to_process:
        logger.info("All products are up-to-date. Nothing to do.")
        db.save_run_state({
            'date': datetime.now().date().isoformat(),
            'total_items': len(all_items),
            'processed_count': len(all_items),
            'status_counts': {
                ProductResult.SUCCESS.value: 0,
                ProductResult.SKIPPED.value: len(all_items),
                ProductResult.UNAVAILABLE.value: 0,
                ProductResult.FAILED.value: 0,
            },
            'failed_items': {},
            'completed': True,
            'finished_at': datetime.now().isoformat(),
        })
        return db.load_run_state()

    # ---- Initialize advisory run-state ----
    state = {
        'date': datetime.now().date().isoformat(),
        'run_id': datetime.now().isoformat(),
        'started_at': datetime.now().isoformat(),
        'total_items': len(all_items),
        'processed_count': len(all_items) - len(items_to_process),
        'status_counts': {
            ProductResult.SUCCESS.value: 0,
            ProductResult.SKIPPED.value: len(all_items) - len(items_to_process),
            ProductResult.UNAVAILABLE.value: 0,
            ProductResult.FAILED.value: 0,
        },
        'failed_items': {},
        # Kept for compatibility with existing run-state consumers.
        'errors': {},
        'completed': False,
        'heartbeat_at': datetime.now().isoformat(),
    }
    db.save_run_state(state)

    # Validate the full-product contract once before starting thousands of
    # requests. A schema drift is a job-level failure, not a per-product miss.
    full_query_probe = next(
        (tpnc for tpnc in items_to_process if force or not db.product_exists(tpnc)),
        None,
    )
    if full_query_probe:
        try:
            get_product_api(full_query_probe, "full")
        except (GraphQLContractError, UpstreamConfigurationError) as exc:
            state['failed_items'][str(full_query_probe)] = type(exc).__name__
            state['errors'][str(full_query_probe)] = 1
            state['status_counts'][ProductResult.FAILED.value] = 1
            state['failed_count'] = 1
            state['failure_reason'] = str(exc)[:2000]
            state['finished_at'] = datetime.now().isoformat()
            state['heartbeat_at'] = state['finished_at']
            db.save_run_state(state)
            logger.error("Scrape aborted during GraphQL contract preflight: %s", exc)
            raise

    # ---- Process items with thread pool ----
    lock = threading.Lock()
    fatal_error = threading.Event()
    fatal_exception = []
    total = len(all_items)
    # Pre-build index to avoid O(n²) .index() calls inside the loop
    item_index = {tpnc: i + 1 for i, tpnc in enumerate(all_items)}

    def _task_wrapper(idx, tpnc):
        result = ProductResult.FAILED
        failure_name = None
        if fatal_error.is_set():
            failure_name = "aborted_after_fatal_error"
        else:
            try:
                result = process_product(tpnc, force=force,
                                         progress_prefix=f"[{idx}/{total}] ")
            except (GraphQLContractError, UpstreamConfigurationError) as exc:
                logger.exception("Fatal upstream error processing %s", tpnc)
                failure_name = type(exc).__name__
                fatal_exception.append(exc)
                fatal_error.set()
            except Exception as exc:
                logger.exception(f"Unhandled error processing {tpnc}: {exc}")
                failure_name = type(exc).__name__

        try:
            with lock:
                state['status_counts'][result.value] = \
                    state['status_counts'].get(result.value, 0) + 1
                if result is not ProductResult.FAILED:
                    state['processed_count'] = state.get('processed_count', 0) + 1
                else:
                    state['failed_items'][str(tpnc)] = failure_name or "request_failed"
                    state['errors'][str(tpnc)] = state['errors'].get(str(tpnc), 0) + 1
                state['failed_count'] = state['status_counts'].get(ProductResult.FAILED.value, 0)
                state['heartbeat_at'] = datetime.now().isoformat()
                # Keep mutation and persistence ordered. Saving outside the lock
                # allowed an older snapshot to overwrite newer progress.
                db.save_run_state(state)
        except Exception:
            logger.exception("Failed to persist run state for %s", tpnc)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=threads)
    futures = []
    try:
        for tpnc in items_to_process:
            idx = item_index[tpnc]
            futures.append(executor.submit(_task_wrapper, idx, tpnc))

        _, not_done = concurrent.futures.wait(futures, timeout=1.0)
        while not_done:
            _, not_done = concurrent.futures.wait(futures, timeout=1.0)

    except KeyboardInterrupt:
        logger.warning("Scraping interrupted — progress saved.")
        return
    finally:
        executor.shutdown(wait=True)

    if fatal_exception:
        state['failure_reason'] = str(fatal_exception[0])[:2000]

    # ---- Finalize run-state ----
    processed = state.get('processed_count', 0)
    failed = state.get('failed_count', 0)
    if processed >= len(all_items) and failed == 0:
        state['completed'] = True
        state['finished_at'] = datetime.now().isoformat()
        db.save_run_state(state)
        logger.info(f"Daily scrape completed: {processed}/{len(all_items)} items.")
        logger.info("Rebuilding stats cache...")
        stats_manager.rebuild_all_cache()
        _notify_alert_service()
    else:
        state['finished_at'] = datetime.now().isoformat()
        db.save_run_state(state)
        logger.error(
            "Daily scrape incomplete: %s/%s classified, %s failed — will resume on next run.",
            processed, len(all_items), failed,
        )

    return state


def _notify_alert_service():
    """Notify the alert-service of today's price drops.

    Failures are logged but never raised — the scraper run must succeed even if
    the downstream alert service is unreachable.
    """
    url = os.environ.get("ALERT_SERVICE_TRIGGER_URL", "http://alert-service:8080/internal/trigger")
    token = os.environ.get("INTERNAL_TRIGGER_TOKEN", "")
    if not token:
        logger.info("INTERNAL_TRIGGER_TOKEN not set — skipping alert-service notification")
        return

    try:
        drops = db.get_today_price_drops()
    except Exception:
        logger.exception("failed to compute today's price drops")
        return

    if not drops:
        logger.info("No price drops to notify the alert-service about.")
        return

    # Forward our scrape-job correlation ID so alert-service's log lines
    # for this trigger share the same trace ID as ours.
    from logging_setup import correlation_headers
    headers = {"X-Internal-Token": token, **correlation_headers()}

    try:
        r = requests.post(
            url,
            json={"drops": drops},
            headers=headers,
            timeout=30,
        )
        if r.status_code == 200:
            logger.info("Alert-service trigger ok: %s", r.json())
        else:
            logger.warning("Alert-service trigger non-200: %s %s", r.status_code, r.text[:500])
    except requests.RequestException:
        logger.exception("Alert-service trigger failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Tesco Price Scraper')
    parser.add_argument('--items', nargs='+', help='List of TPNCs to scrape')
    parser.add_argument('--force', action='store_true', help='Force rescrape')
    parser.add_argument('--threads', type=int, default=DEFAULT_THREADS,
                        help=f'Concurrent threads (default: {DEFAULT_THREADS})')
    args = parser.parse_args()
    run_scraper(specific_items=args.items, force=args.force, threads=args.threads)
