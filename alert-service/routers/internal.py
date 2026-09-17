"""Internal scraper-to-alerts trigger. Authenticated by a shared X-Internal-Token."""

import hmac
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, status

from models import TriggerPayload, TriggerResponse
from services import alert_repo, evaluator, notifier, user_repo
from stores.offers import parse_group_id
import settings
import store_state
import targets


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


def _check_token(provided: Optional[str]) -> None:
    expected = settings.INTERNAL_TRIGGER_TOKEN
    if not expected:
        # Fail closed: an unset token must never grant access.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "internal trigger disabled")
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid internal token")


@router.post("/trigger", response_model=TriggerResponse)
async def trigger(
    payload: TriggerPayload,
    x_internal_token: Optional[str] = Header(default=None, alias="X-Internal-Token"),
) -> TriggerResponse:
    _check_token(x_internal_token)

    if not payload.drops:
        return TriggerResponse(processed=0, triggered=0, emailsSent=0, skipped=0)

    if payload.runKey and await alert_repo.is_trigger_run_completed(payload.runKey):
        # The scraper resends a trigger when it could not record delivery;
        # these digests already went out.
        logger.info(
            "Trigger %s already completed; not sending its digests again.",
            payload.runKey,
            extra={"Action": "alerts.trigger_duplicate", "Category": "job"},
        )
        return TriggerResponse(
            processed=0, triggered=0, emailsSent=0, skipped=0, duplicate=True
        )

    drops: list[dict] = []
    for d in payload.drops:
        try:
            ref, _ = targets.normalize(d.productId)
        except targets.InvalidTarget:
            logger.warning("Ignoring a price drop with an invalid product reference: %s", d.productId)
            continue
        store = targets.store_of(ref)
        if store is None:
            continue  # a drop always belongs to one store listing
        drops.append({
            "ref": ref,
            "store": store,
            "groupId": d.groupId if d.groupId and parse_group_id(d.groupId) else None,
            "newPrice": d.newPrice,
            "oldPrice": d.oldPrice,
            "productName": d.productName,
        })

    watched = [drop["ref"] for drop in drops] + [drop["groupId"] for drop in drops if drop["groupId"]]
    candidate_alerts = await alert_repo.find_active_for_products(watched)
    enabled_stores = await store_state.enabled_store_ids()
    triggered = evaluator.evaluate(candidate_alerts, drops, enabled_stores)
    names = await store_state.store_names()
    for item in triggered:
        item["storeName"] = names.get(item.get("store"), item.get("store"))
    by_user = evaluator.group_by_user(triggered)

    user_emails = await user_repo.emails_for(by_user.keys())
    # Fetch email preferences in parallel for all triggered users
    import asyncio as _asyncio
    prefs_list = await _asyncio.gather(
        *(alert_repo.get_email_preference(uid) for uid in by_user.keys())
    )
    user_email_prefs: dict[str, bool] = dict(zip(by_user.keys(), prefs_list))

    skipped = 0
    by_user_email: dict[str, list[dict]] = {}
    for uid, items in by_user.items():
        if not user_email_prefs.get(uid, True):
            logger.info("userId=%s has opted out of email notifications — skipping", uid)
            skipped += len(items)
            continue
        email = user_emails.get(uid)
        if not email:
            logger.warning("no cached email for userId=%s — skipping %d items", uid, len(items))
            skipped += len(items)
            continue
        # Multiple Keycloak subjects can legitimately share one mailbox. Merge
        # their alerts into one digest instead of letting the last user win.
        by_user_email.setdefault(email, []).extend(items)

    for items in by_user_email.values():
        items.sort(
            key=lambda item: (
                item.get("productName") or "",
                item.get("productId") or "",
            )
        )

    emails_sent = await notifier.send_digests(by_user_email)

    response = TriggerResponse(
        processed=len(payload.drops),
        triggered=len(triggered),
        emailsSent=emails_sent,
        skipped=skipped,
    )
    if payload.runKey:
        await alert_repo.mark_trigger_run_completed(
            payload.runKey, response.model_dump(exclude={"duplicate"})
        )
    logger.info(
        "Alert trigger processed %s drops: %s triggered, %s digests sent, %s skipped.",
        response.processed,
        response.triggered,
        response.emailsSent,
        response.skipped,
        extra={
            "Action": "alerts.trigger_processed",
            "Category": "job",
            "Triggered": response.triggered,
            "EmailsSent": response.emailsSent,
            "Skipped": response.skipped,
        },
    )
    return response
