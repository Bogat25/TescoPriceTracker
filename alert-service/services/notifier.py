"""Resend email delivery for digest emails."""

import asyncio
import logging
import os
from typing import Optional

import resend
from jinja2 import Environment, FileSystemLoader, select_autoescape

import settings


logger = logging.getLogger(__name__)


_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
_jinja = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(["html"]),
)


_configured = False


def _configure() -> None:
    global _configured
    if not _configured:
        if not settings.RESEND_API_KEY:
            logger.warning("RESEND_API_KEY is not set — emails will fail to send")
        resend.api_key = settings.RESEND_API_KEY
        _configured = True


def _render(items: list[dict]) -> str:
    template = _jinja.get_template("email.html")
    return template.render(items=items, count=len(items))


def _subject(items: list[dict]) -> str:
    if len(items) == 1:
        name = items[0].get("productName") or items[0]["productId"]
        return f"Price drop: {name}"
    return f"{len(items)} price drops on your watchlist"


async def _send_one(email: str, items: list[dict]) -> bool:
    _configure()

    params: dict = {
        "from": settings.RESEND_FROM,
        "to": [email],
        "subject": _subject(items),
        "html": _render(items),
    }
    if settings.RESEND_REPLY_TO:
        params["reply_to"] = [settings.RESEND_REPLY_TO]

    try:
        # The Resend Python SDK is synchronous; offload to a thread so we don't
        # block the event loop while waiting on its HTTP call.
        await asyncio.to_thread(resend.Emails.send, params)
        return True
    except Exception:
        logger.exception("Resend send failed for %s", email)
        return False


async def send_digests(
    by_user_email: dict[str, list[dict]],
    concurrency: Optional[int] = None,
) -> int:
    """Send one digest email per user. Returns the count of successful sends."""
    if not by_user_email:
        return 0

    sem = asyncio.Semaphore(concurrency or settings.RESEND_CONCURRENCY)

    async def _bounded(email: str, items: list[dict]) -> bool:
        async with sem:
            return await _send_one(email, items)

    results = await asyncio.gather(
        *(_bounded(email, items) for email, items in by_user_email.items())
    )
    return sum(1 for ok in results if ok)
