"""Daily Auchan crawl: every grocery category, page by page, resumable.

Run state is saved after every page, so an interrupted or rate-limited pass
continues from the next unsaved page. Log actions match the Tesco scheduler
(``scrape.completed``, ``scrape.incomplete``, ``scrape.fatal``) so the same
alerting pattern applies per service.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from stores.auchan import mapper, repository
from stores.auchan.client import AuchanClient, AuchanContractError, AuchanUnavailable


logger = logging.getLogger(__name__)

# Fresh, frozen, pantry, drinks, special diets, beauty/baby, pets, household.
DEFAULT_CATEGORY_IDS = (14479, 14602, 14656, 14740, 14830, 13307, 14863, 12617)
DETAILS_PER_RUN = int(os.getenv("AUCHAN_DETAILS_PER_RUN", "300"))


def configured_category_ids() -> tuple:
    raw = os.getenv("AUCHAN_CATEGORY_IDS", "").strip()
    if not raw:
        return DEFAULT_CATEGORY_IDS
    return tuple(int(part) for part in raw.split(",") if part.strip())


def is_run_finished(state: Optional[dict]) -> bool:
    """Complete and published: prices saved, statistics rebuilt, alerts sent."""
    return bool(state and state.get("completed") and state.get("alerts_notified_at"))


def publish(state: dict, today, now: Callable[[], datetime]) -> dict:
    """Rebuild statistics and send price-drop alerts once per day, resumably.

    Prices are already saved when this runs, so a failure here only leaves the
    publication for the next pass (the scheduler retries an unfinished day).
    """
    from stores import alerts_feed, categories, insights  # imported here: all read every store adapter

    if not state.get("stats_rebuilt_at"):
        insights.rebuild_store(mapper.STORE_ID)
        categories.rebuild_safely()
        state["stats_rebuilt_at"] = now().isoformat()
        repository.save_run(state)
    if not state.get("alerts_notified_at"):
        if not alerts_feed.notify(mapper.STORE_ID, today):
            state["retryable"] = True
            state["failure_reason"] = "price-drop alerts were not delivered"
            repository.save_run(state)
            logger.error(
                "Auchan price-drop alerts were not delivered; the next pass retries them.",
                extra={"Action": "scrape.finalization_failed", "Category": "job", "Store": mapper.STORE_ID},
            )
            return state
        state["alerts_notified_at"] = now().isoformat()
        state.pop("failure_reason", None)
        repository.save_run(state)
        logger.info(
            "Statistics and price-drop alerts published for Auchan %s.", state["date"],
            extra={"Action": "scrape.published", "Category": "job", "Store": mapper.STORE_ID},
        )
    return state


def _new_state(date: str, category_ids, now: datetime) -> dict:
    return {
        "date": date,
        "store": mapper.STORE_ID,
        "run_id": now.isoformat(),
        "started_at": now.isoformat(),
        "heartbeat_at": now.isoformat(),
        "completed": False,
        "retryable": True,
        "saved_count": 0,
        "skipped_count": 0,
        "categories": {
            str(category_id): {"next_page": 1, "page_count": None, "item_count": None, "done": False}
            for category_id in category_ids
        },
    }


def _finish_incomplete(state: dict, exc: Exception, retryable: bool, now: datetime) -> dict:
    state["retryable"] = retryable
    state["failure_reason"] = str(exc)[:2000]
    state["finished_at"] = now.isoformat()
    state["heartbeat_at"] = state["finished_at"]
    retry_after = getattr(exc, "retry_after", None)
    if retry_after:
        state["upstream_blocked_until"] = (datetime.now(timezone.utc) + timedelta(seconds=retry_after)).isoformat()
    repository.save_run(state)
    if retryable:
        logger.error(
            "Auchan scrape incomplete: %s saved, will resume on the next pass: %s",
            state["saved_count"], exc,
            extra={"Action": "scrape.incomplete", "Category": "job", "Store": mapper.STORE_ID,
                   "UpstreamBlockedUntil": state.get("upstream_blocked_until")},
        )
    else:
        logger.error(
            "Auchan scrape stopped by an unexpected API response; a code change is needed: %s", exc,
            extra={"Action": "scrape.fatal", "Category": "job", "Store": mapper.STORE_ID},
        )
    return state


def run_crawl(
    client: Optional[AuchanClient] = None,
    category_ids=None,
    now: Callable[[], datetime] = datetime.now,
) -> dict:
    client = client or AuchanClient()
    category_ids = tuple(category_ids or configured_category_ids())
    today = now().date().isoformat()

    state = repository.load_run(today)
    if is_run_finished(state):
        return state
    if state and state.get("completed"):
        return publish(state, now().date(), now)
    if state is None:
        state = _new_state(today, category_ids, now())
    else:
        for category_id in category_ids:
            state["categories"].setdefault(
                str(category_id), {"next_page": 1, "page_count": None, "item_count": None, "done": False}
            )
    state["retryable"] = True
    state.pop("finished_at", None)
    state.pop("failure_reason", None)
    repository.save_run(state)
    logger.info("Starting Auchan scrape pass.",
                extra={"Action": "scrape.started", "Category": "job", "Store": mapper.STORE_ID})

    try:
        available = {child.get("id") for child in client.category_tree() if isinstance(child, dict)}
        for category_id in category_ids:
            progress = state["categories"][str(category_id)]
            if progress["done"]:
                continue
            if category_id not in available:
                logger.warning(
                    "Configured Auchan category %s no longer exists; skipping it.", category_id,
                    extra={"Action": "auchan.category_missing", "Category": "job", "Store": mapper.STORE_ID},
                )
                progress.update(done=True, missing=True)
                repository.save_run(state)
                continue

            while True:
                page = progress["next_page"]
                body = client.list_products(category_id, page)
                fields_list = []
                for product in body["results"]:
                    try:
                        fields_list.append(mapper.document_fields(product))
                    except mapper.UnexpectedProductShape:
                        state["skipped_count"] += 1
                state["saved_count"] += repository.save_page(fields_list, today, now())
                progress.update(page_count=body["pageCount"], item_count=body["itemCount"])
                progress["next_page"] = page + 1
                progress["done"] = page >= body["pageCount"]
                state["heartbeat_at"] = now().isoformat()
                repository.save_run(state)
                if progress["done"]:
                    break

        if state["saved_count"] == 0:
            raise AuchanContractError("every configured category returned an empty product list")
    except AuchanUnavailable as exc:
        return _finish_incomplete(state, exc, retryable=True, now=now())
    except repository.RepositoryError as exc:
        return _finish_incomplete(state, exc, retryable=True, now=now())
    except AuchanContractError as exc:
        return _finish_incomplete(state, exc, retryable=False, now=now())

    finished = now().isoformat()
    state.update(completed=True, retryable=True, finished_at=finished, heartbeat_at=finished)
    state.pop("upstream_blocked_until", None)
    repository.save_run(state)
    logger.info(
        "Auchan scrape completed: %s products saved, %s skipped.", state["saved_count"], state["skipped_count"],
        extra={"Action": "scrape.completed", "Category": "job", "Store": mapper.STORE_ID,
               "SavedCount": state["saved_count"], "SkippedCount": state["skipped_count"]},
    )
    publish(state, now().date(), now)
    fetch_missing_details(client, DETAILS_PER_RUN)
    return state


def fetch_missing_details(client: AuchanClient, limit: int) -> dict:
    """Fetch description and ingredients for new or renamed products.

    Best effort and bounded per run: prices are already saved, and the rest is
    picked up by the next day's run.
    """
    counts = {"fetched": 0, "failed": 0}
    if limit <= 0:
        return counts
    try:
        pending = repository.products_needing_details(limit)
        for doc in pending:
            if not doc.get("variant_id"):
                repository.mark_details_failed(doc["_id"], "no variant id")
                counts["failed"] += 1
                continue
            try:
                sections = client.product_details(doc["_id"], doc["variant_id"])
            except AuchanContractError as exc:
                repository.mark_details_failed(doc["_id"], str(exc))
                counts["failed"] += 1
                continue
            repository.save_details(doc["_id"], mapper.details_text(sections))
            counts["fetched"] += 1
    except Exception as exc:  # best effort: never fail a completed price crawl
        logger.warning("Auchan product details paused: %s", exc, exc_info=not isinstance(exc, AuchanUnavailable),
                       extra={"Action": "auchan.details_paused", "Category": "job", "Store": mapper.STORE_ID})
    if counts["fetched"] or counts["failed"]:
        logger.info("Auchan product details: %s fetched, %s failed.", counts["fetched"], counts["failed"],
                    extra={"Action": "auchan.details_fetched", "Category": "job", "Store": mapper.STORE_ID})
    return counts
