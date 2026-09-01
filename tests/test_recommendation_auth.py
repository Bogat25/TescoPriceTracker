import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException


AUTH_FILE = Path(__file__).resolve().parents[1] / "backend-api" / "auth.py"
SPEC = importlib.util.spec_from_file_location("backend_recommendation_auth", AUTH_FILE)
auth = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(auth)


def test_personalized_auth_requires_bearer_header():
    with pytest.raises(HTTPException) as exc:
        auth.current_user(None)
    assert exc.value.status_code == 401


def test_authorized_party_is_mandatory(monkeypatch):
    class Client:
        def get_signing_key_from_jwt(self, _token):
            return type("Key", (), {"key": object()})()

    monkeypatch.setattr(auth, "_jwk_client", lambda: Client())
    monkeypatch.setattr(auth.jwt, "decode", lambda *_args, **_kwargs: {
        "sub": "victim", "azp": "different-client",
    })

    with pytest.raises(HTTPException) as exc:
        auth._validate_bearer("token")
    assert exc.value.status_code == 401
