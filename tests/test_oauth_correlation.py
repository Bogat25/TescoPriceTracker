import importlib.util
import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from starlette.testclient import TestClient


@pytest.fixture
def gateway(monkeypatch):
    for key, value in {
        "KC_PUBLIC_BASE_URL": "https://identity.invalid/realms/test",
        "KC_INTERNAL_BASE_URL": "https://identity.invalid/realms/test",
        "KC_CLIENT_ID": "synthetic-client",
        "KC_CLIENT_SECRET": "",
        "GATEWAY_REDIRECT_URI": "https://site.invalid/auth/callback",
        "POST_LOGIN_REDIRECT_DEFAULT": "https://site.invalid/",
        "POST_LOGOUT_REDIRECT_DEFAULT": "https://site.invalid/",
        "RETURN_URL_ALLOWED_HOSTS": "site.invalid",
        "COOKIE_DOMAIN": "",
        "SESSION_SECRET": "synthetic-test-fixture-only",
        "COOKIE_SECURE": "true",
    }.items():
        monkeypatch.setenv(key, value)
    path = Path(__file__).parents[1] / "auth-gateway"
    monkeypatch.syspath_prepend(str(path))
    spec = importlib.util.spec_from_file_location("correlation_gateway", path / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Idp:
        calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            Idp.calls += 1
            return httpx.Response(200, json={"access_token": "synthetic", "expires_in": 300})

    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: Idp())
    return module, Idp


def start(client):
    response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 302
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]
    return parse_qs(urlsplit(response.headers["location"]).query)["state"][0]


def test_callback_is_bound_to_browser_and_consumed_once(gateway):
    app, idp = gateway
    with (
        TestClient(app.app, base_url="https://site.invalid") as first,
        TestClient(app.app, base_url="https://site.invalid") as second,
    ):
        state = start(first)
        assert second.get("/auth/callback", params={"state": state, "code": "synthetic"}).status_code == 400
        assert idp.calls == 0
        response = first.get("/auth/callback", params={"state": state, "code": "synthetic"}, follow_redirects=False)
        assert response.status_code == 302 and app.SESSION_COOKIE_NAME in response.cookies
        assert first.get("/auth/callback", params={"state": state, "code": "synthetic"}).status_code == 400
        assert idp.calls == 1


def test_concurrent_tabs_and_expiry(gateway):
    app, idp = gateway
    with TestClient(app.app, base_url="https://site.invalid") as client:
        first, second = start(client), start(client)
        payload = json.dumps(app._unseal(first)).encode()
        first = app._fernet.encrypt_at_time(payload, int(time.time()) - app._LOGIN_TTL - 1).decode()
        assert client.get("/auth/callback", params={"state": first, "code": "synthetic"}).status_code == 400
        assert (
            client.get(
                "/auth/callback", params={"state": second, "code": "synthetic"}, follow_redirects=False
            ).status_code
            == 302
        )
        assert idp.calls == 1


def test_anonymous_logins_need_no_server_state(gateway):
    app, _ = gateway
    with TestClient(app.app, base_url="https://site.invalid") as client:
        for _ in range(1100):
            assert client.get("/auth/login", follow_redirects=False).status_code == 302
        client.cookies.clear()
        assert client.get("/auth/callback", params={"state": "forged", "code": "synthetic"}).status_code == 400


@pytest.mark.parametrize(
    "url",
    ["//external.invalid", "/\\external.invalid", "https://external.invalid", "ftp://site.invalid", "/ok\r\nother"],
)
def test_unsafe_return_urls_are_rejected(gateway, url):
    assert gateway[0]._safe_return_url(url, "/default") == "/default"


def test_gateway_access_log_omits_query_capabilities(gateway):
    import logging

    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("192.0.2.1:1", "GET", "/auth/extension-token?code=synthetic-capability", "1.1", 200), None,
    )
    for log_filter in logging.getLogger("uvicorn.access").filters:
        log_filter.filter(record)
    assert "synthetic-capability" not in record.getMessage()
    assert "/auth/extension-token" in record.getMessage()


def test_frontend_does_not_access_log_authentication_queries():
    root = Path(__file__).parents[1] / "frontend"
    for name in ("nginx.conf", "nginx.conf.template"):
        auth_location = (root / name).read_text().split("location /auth/ {", 1)[1].split("}", 1)[0]
        assert "access_log off;" in auth_location
