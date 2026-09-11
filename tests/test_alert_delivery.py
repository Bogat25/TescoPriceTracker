import asyncio
import sys
import types
from pathlib import Path


ALERT_SERVICE = Path(__file__).resolve().parents[1] / "alert-service"
sys.path.insert(0, str(ALERT_SERVICE))

if "resend" not in sys.modules:
    _resend = types.ModuleType("resend")
    _resend.Emails = type("Emails", (), {"send": staticmethod(lambda _params: None)})
    _resend.api_key = ""
    sys.modules["resend"] = _resend

import services  # noqa: E402
from services import notifier  # noqa: E402

# The trigger logic is unit-tested without opening Motor/MongoDB. Install tiny
# service-module placeholders before importing the router, then monkeypatch the
# async operations in each test.
for _name in ("alert_repo", "evaluator", "user_repo"):
    _module = types.ModuleType(f"services.{_name}")
    setattr(services, _name, _module)
    sys.modules[f"services.{_name}"] = _module

from models import PriceDrop, TriggerPayload  # noqa: E402
from routers import internal  # noqa: E402


def test_users_sharing_an_email_receive_one_merged_digest(monkeypatch):
    captured = {}

    async def find_active(_product_ids):
        return [{"placeholder": True}]

    async def emails_for(_user_ids):
        return {"user-a": "family@example.com", "user-b": "family@example.com"}

    async def enabled(_user_id):
        return True

    async def send_digests(digests):
        captured.update(digests)
        return len(digests)

    monkeypatch.setattr(internal.settings, "INTERNAL_TRIGGER_TOKEN", "secret")
    monkeypatch.setattr(internal.alert_repo, "find_active_for_products", find_active, raising=False)
    monkeypatch.setattr(internal.alert_repo, "get_email_preference", enabled, raising=False)
    monkeypatch.setattr(internal.user_repo, "emails_for", emails_for, raising=False)
    monkeypatch.setattr(internal.evaluator, "evaluate", lambda *_args: [{"triggered": True}], raising=False)
    monkeypatch.setattr(internal.evaluator, "group_by_user", lambda _items: {
        "user-a": [{"productId": "1", "productName": "Apple"}],
        "user-b": [{"productId": "2", "productName": "Bread"}],
    }, raising=False)
    monkeypatch.setattr(internal.notifier, "send_digests", send_digests)

    payload = TriggerPayload(drops=[PriceDrop(productId="1", oldPrice=10, newPrice=9)])
    response = asyncio.run(internal.trigger(payload, x_internal_token="secret"))

    assert response.emailsSent == 1
    assert [item["productId"] for item in captured["family@example.com"]] == ["1", "2"]


def test_missing_resend_credentials_fail_closed_without_sdk_call(monkeypatch):
    called = False

    def send(_params):
        nonlocal called
        called = True

    monkeypatch.setattr(notifier.settings, "RESEND_API_KEY", "")
    monkeypatch.setattr(notifier.resend.Emails, "send", send)

    result = asyncio.run(notifier._send_one(
        "person@example.com",
        [{"productId": "1", "productName": "Apple"}],
    ))

    assert result is False
    assert called is False


def test_completed_run_key_does_not_send_digests_twice(monkeypatch):
    completed_runs = {}
    sent = []

    async def find_active(_product_ids):
        return [{"placeholder": True}]

    async def emails_for(_user_ids):
        return {"user-a": "person@example.com"}

    async def enabled(_user_id):
        return True

    async def is_completed(run_key):
        return run_key in completed_runs

    async def mark_completed(run_key, summary):
        completed_runs[run_key] = summary

    async def send_digests(digests):
        sent.append(digests)
        return len(digests)

    monkeypatch.setattr(internal.settings, "INTERNAL_TRIGGER_TOKEN", "secret")
    monkeypatch.setattr(internal.alert_repo, "find_active_for_products", find_active, raising=False)
    monkeypatch.setattr(internal.alert_repo, "get_email_preference", enabled, raising=False)
    monkeypatch.setattr(internal.alert_repo, "is_trigger_run_completed", is_completed, raising=False)
    monkeypatch.setattr(internal.alert_repo, "mark_trigger_run_completed", mark_completed, raising=False)
    monkeypatch.setattr(internal.user_repo, "emails_for", emails_for, raising=False)
    monkeypatch.setattr(internal.evaluator, "evaluate", lambda *_args: [{"triggered": True}], raising=False)
    monkeypatch.setattr(internal.evaluator, "group_by_user", lambda _items: {
        "user-a": [{"productId": "1", "productName": "Apple"}],
    }, raising=False)
    monkeypatch.setattr(internal.notifier, "send_digests", send_digests)

    payload = TriggerPayload(
        drops=[PriceDrop(productId="1", oldPrice=10, newPrice=9)],
        runKey="daily:2026-09-11",
    )
    first = asyncio.run(internal.trigger(payload, x_internal_token="secret"))
    second = asyncio.run(internal.trigger(payload, x_internal_token="secret"))

    assert first.duplicate is False and first.emailsSent == 1
    assert second.duplicate is True and second.emailsSent == 0
    assert len(sent) == 1
    assert completed_runs["daily:2026-09-11"]["emailsSent"] == 1
