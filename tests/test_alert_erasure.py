"""Account erasure: RefDataSync tells the alert service which accounts were deleted."""

import asyncio
import sys
import types
from pathlib import Path

import pytest
from fastapi import HTTPException

ALERT_SERVICE = Path(__file__).resolve().parents[1] / "alert-service"
sys.path.insert(0, str(ALERT_SERVICE))

if "resend" not in sys.modules:
    _resend = types.ModuleType("resend")
    _resend.Emails = type("Emails", (), {"send": staticmethod(lambda _params: None)})
    _resend.api_key = ""
    sys.modules["resend"] = _resend

import services  # noqa: E402

for _name in ("alert_repo", "evaluator", "user_repo"):
    if f"services.{_name}" not in sys.modules:
        _module = types.ModuleType(f"services.{_name}")
        setattr(services, _name, _module)
        sys.modules[f"services.{_name}"] = _module

from models import EraseUsersPayload  # noqa: E402
from routers import internal  # noqa: E402


def _stub(monkeypatch, erased):
    async def erase_alerts(ids):
        erased["alerts"] = sorted(ids)
        return {"alerts": 3, "preferences": 1}

    async def erase_users(ids):
        erased["users"] = sorted(ids)
        return 1

    monkeypatch.setattr(internal.settings, "INTERNAL_TRIGGER_TOKEN", "secret")
    monkeypatch.setattr(internal.alert_repo, "erase_users", erase_alerts, raising=False)
    monkeypatch.setattr(internal.user_repo, "erase", erase_users, raising=False)


def test_erases_alerts_preferences_and_cached_email(monkeypatch):
    erased = {}
    _stub(monkeypatch, erased)
    payload = EraseUsersPayload(userIds=["gone-1", "", "gone-2"])

    response = asyncio.run(internal.erase_users(payload, x_internal_token="secret"))

    assert (response.users, response.alerts, response.preferences) == (1, 3, 1)
    assert erased == {"alerts": ["gone-1", "gone-2"], "users": ["gone-1", "gone-2"]}


@pytest.mark.parametrize("token, status", [(None, 401), ("wrong", 401)])
def test_requires_the_internal_token(monkeypatch, token, status):
    erased = {}
    _stub(monkeypatch, erased)

    with pytest.raises(HTTPException) as error:
        asyncio.run(internal.erase_users(EraseUsersPayload(userIds=["x"]), x_internal_token=token))

    assert error.value.status_code == status
    assert erased == {}


def test_fails_closed_without_a_configured_token(monkeypatch):
    erased = {}
    _stub(monkeypatch, erased)
    monkeypatch.setattr(internal.settings, "INTERNAL_TRIGGER_TOKEN", "")

    with pytest.raises(HTTPException) as error:
        asyncio.run(internal.erase_users(EraseUsersPayload(userIds=["x"]), x_internal_token=""))

    assert error.value.status_code == 503
    assert erased == {}
