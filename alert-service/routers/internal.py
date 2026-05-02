"""Internal scraper-to-alerts trigger. Authenticated by a shared X-Internal-Token."""

import hmac
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, status

from models import TriggerPayload, TriggerResponse
from services import alert_repo, evaluator, notifier, user_repo
import settings


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

    drop_map: dict[str, dict] = {
        d.productId: {
            "newPrice": d.newPrice,
            "oldPrice": d.oldPrice,
            "productName": d.productName,
        }
        for d in payload.drops
    }

    candidate_alerts = await alert_repo.find_active_for_products(list(drop_map.keys()))
    triggered = evaluator.evaluate(candidate_alerts, drop_map)
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
        by_user_email[email] = items

    emails_sent = await notifier.send_digests(by_user_email)

    return TriggerResponse(
        processed=len(payload.drops),
        triggered=len(triggered),
        emailsSent=emails_sent,
        skipped=skipped,
    )
