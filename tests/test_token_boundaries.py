import importlib.util
import time
import types
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException


@pytest.fixture(params=["backend-api", "alert-service"])
def validator(request, monkeypatch):
    root = Path(__file__).parents[1]
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = types.SimpleNamespace(
        KC_ISSUER="https://issuer.invalid/realms/test",
        KC_CLIENT_ID="gateway-client",
        KC_AUDIENCE="gavaller-api",
        KC_JWKS_URL="https://issuer.invalid/certs",
        JWKS_TTL_SECONDS=3600,
    )
    monkeypatch.setenv("KC_ISSUER", settings.KC_ISSUER)
    monkeypatch.setenv("KC_CLIENT_ID", settings.KC_CLIENT_ID)
    monkeypatch.setenv("KC_AUDIENCE", settings.KC_AUDIENCE)
    monkeypatch.setitem(__import__("sys").modules, "settings", settings)
    spec = importlib.util.spec_from_file_location(
        "boundary_" + request.param.replace("-", "_"), root / request.param / "auth.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if request.param == "backend-api":
        monkeypatch.setattr(
            module,
            "_jwk_client",
            lambda: types.SimpleNamespace(
                get_signing_key_from_jwt=lambda _: types.SimpleNamespace(key=key.public_key())
            ),
        )
    else:
        monkeypatch.setattr(module._jwks, "get_signing_key", lambda _: key.public_key())
    claims = {
        "iss": settings.KC_ISSUER,
        "sub": "synthetic-user",
        "azp": "gateway-client",
        "aud": "gavaller-api",
        "typ": "Bearer",
        "exp": int(time.time()) + 60,
        "iat": int(time.time()),
    }
    return module, key, claims


def test_intended_access_token_is_accepted(validator):
    module, key, claims = validator
    assert module._validate_bearer(jwt.encode(claims, key, algorithm="RS256"))["sub"] == "synthetic-user"


@pytest.mark.parametrize(
    "change",
    [
        {"aud": "unrelated-api"},
        {"typ": "ID"},
        {"azp": "unrelated-client"},
        {"exp": 1},
        {"azp": None},
        {"aud": None},
        {"typ": None},
    ],
)
def test_other_resources_id_tokens_and_missing_claims_are_rejected(validator, change):
    module, key, claims = validator
    claims.update(change)
    claims = {k: v for k, v in claims.items() if v is not None}
    with pytest.raises(HTTPException) as error:
        module._validate_bearer(jwt.encode(claims, key, algorithm="RS256"))
    assert error.value.status_code == 401
