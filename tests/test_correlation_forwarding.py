"""
Static + light integration tests for cross-service correlation forwarding.

These guarantee the call sites we patched in Chunk-C-followups actually
pass the bound correlation ID into outgoing HTTP requests. Without this
the trace dies at the service boundary even though every individual
service logs with the right ID locally.

Targets covered
---------------
  * `alert-service/services/keycloak_admin.py::_internal_headers`
  * `scraper/scraper.py::_notify_alert_service`
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ALERT_SERVICE = REPO_ROOT / "alert-service"


def _ensure_helper_on_path():
    if str(ALERT_SERVICE) not in sys.path:
        sys.path.insert(0, str(ALERT_SERVICE))
    if "logging_setup" in sys.modules:
        importlib.reload(sys.modules["logging_setup"])
    return importlib.import_module("logging_setup")


# ---------------------------------------------------------------------------
# alert-service → gateway via _internal_headers
# ---------------------------------------------------------------------------

def test_keycloak_admin_internal_headers_forwards_correlation(monkeypatch):
    """
    `_internal_headers()` must merge the currently bound CorrelationId.
    If this fails, alert-keycloak-sync's calls to the gateway log under
    a different correlation_id than the sync job — Grafana traces split.
    """
    monkeypatch.setenv("SERVICE_NAME", "alert-keycloak-sync")
    ls = _ensure_helper_on_path()
    ls.setup_logging()

    # Stub `settings` so the import inside keycloak_admin doesn't fail
    # (it pulls a runtime config we don't need for this assertion).
    fake_settings = type(sys)("settings")
    fake_settings.GATEWAY_INTERNAL_TOKEN = "test-token"
    sys.modules["settings"] = fake_settings

    if "services.keycloak_admin" in sys.modules:
        del sys.modules["services.keycloak_admin"]
    if str(ALERT_SERVICE) not in sys.path:
        sys.path.insert(0, str(ALERT_SERVICE))
    keycloak_admin = importlib.import_module("services.keycloak_admin")

    ls.bind_correlation_id("trace-fwd-1")
    headers = keycloak_admin._internal_headers()
    assert headers["X-Correlation-ID"] == "trace-fwd-1"
    assert headers["X-Internal-Token"] == "test-token"
    assert headers["Accept"] == "application/json"

    ls.clear_context()
    headers_unbound = keycloak_admin._internal_headers()
    assert "X-Correlation-ID" not in headers_unbound
    # Other headers still present.
    assert headers_unbound["X-Internal-Token"] == "test-token"


def test_keycloak_admin_internal_headers_forwards_anon_id(monkeypatch):
    monkeypatch.setenv("SERVICE_NAME", "alert-keycloak-sync")
    ls = _ensure_helper_on_path()
    ls.setup_logging()

    fake_settings = type(sys)("settings")
    fake_settings.GATEWAY_INTERNAL_TOKEN = "test-token"
    sys.modules["settings"] = fake_settings

    if "services.keycloak_admin" in sys.modules:
        del sys.modules["services.keycloak_admin"]
    if str(ALERT_SERVICE) not in sys.path:
        sys.path.insert(0, str(ALERT_SERVICE))
    keycloak_admin = importlib.import_module("services.keycloak_admin")

    ls.bind_anon_id("anon-forward-1")
    headers = keycloak_admin._internal_headers()
    assert headers["X-Anon-Id"] == "anon-forward-1"

    ls.clear_context()
    headers_unbound = keycloak_admin._internal_headers()
    assert "X-Anon-Id" not in headers_unbound


# ---------------------------------------------------------------------------
# scraper → alert-service trigger
# ---------------------------------------------------------------------------

def test_scraper_notify_includes_correlation_header():
    """
    The scraper's _notify_alert_service builds its outgoing headers as a
    literal `{... **correlation_headers()}` dict. Static-grep here is enough
    — running the function would drag in mongo + a real HTTP call.
    """
    src = (REPO_ROOT / "scraper" / "scraper.py").read_text(encoding="utf-8")
    # Find the _notify_alert_service body and assert the spread is there.
    assert "_notify_alert_service" in src
    notify_body_start = src.index("def _notify_alert_service")
    next_def = src.find("\ndef ", notify_body_start + 1)
    body = src[notify_body_start:next_def]

    assert "correlation_headers()" in body, (
        "scraper._notify_alert_service must merge correlation_headers() into "
        "its outgoing request headers — otherwise the trace dies at the "
        "scheduler→alert-service boundary."
    )
    assert "X-Internal-Token" in body, "auth token still required"
