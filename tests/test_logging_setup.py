"""
Unit tests for the canonical Python logging helper (Chunk C).

These tests run without Docker. They import one of the in-tree copies of
``logging_setup.py`` (alert-service's), drive it through structlog, capture
the JSON written to stdout, and assert the wire format matches the contract
that Vector + Postgres expect.

What's verified
---------------
  * Calls to a stdlib ``logging.getLogger(...).info("msg")`` route through
    structlog and emit Serilog-Compact JSON (`@t`, `@l`, `@m`).
  * The Service field is filled from the ``SERVICE_NAME`` env var.
  * Calls to ``structlog.get_logger().info(event=..., foo=..., Action=...)``
    promote known kwargs (``Action``, ``Category``, ``RequestId``,
    ``CorrelationId``) to top-level keys and dump the rest into ``Context``.
  * ``bind_correlation_id`` makes ``CorrelationId`` show up in subsequent
    log lines, and ``clear_context`` removes it.
  * The level mapping converts Python's lowercase names to Serilog casing.
  * uvicorn loggers no longer have their own handlers (they propagate to root).
"""
from __future__ import annotations

import importlib
import io
import json
import logging
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ALERT_SERVICE_DIR = REPO_ROOT / "alert-service"


@pytest.fixture
def logging_setup(monkeypatch):
    """
    Import the alert-service copy of logging_setup.py with a known
    SERVICE_NAME, then call setup_logging() so subsequent log calls go
    through the JSON pipeline. The fixture redirects stdout into a buffer
    so tests can read what was emitted.
    """
    # Make sure the helper is importable. We don't need every service's
    # copy on path because the parity test verifies they're identical.
    if str(ALERT_SERVICE_DIR) not in sys.path:
        sys.path.insert(0, str(ALERT_SERVICE_DIR))

    monkeypatch.setenv("SERVICE_NAME", "test-service")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    if "logging_setup" in sys.modules:
        importlib.reload(sys.modules["logging_setup"])
    import logging_setup as ls
    importlib.reload(ls)

    captured = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured)
    ls.setup_logging()
    yield ls, captured

    # Cleanup: drop the handler the fixture installed; subsequent tests get
    # a fresh root logger.
    for h in list(logging.getLogger().handlers):
        logging.getLogger().removeHandler(h)
    ls.clear_context()


def _last_json(buf: io.StringIO) -> dict:
    """Return the last non-blank line in the buffer parsed as JSON."""
    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    assert lines, "no log lines were written"
    return json.loads(lines[-1])


# ---------------------------------------------------------------------------
# Wire format
# ---------------------------------------------------------------------------

def test_stdlib_logger_emits_serilog_compact_json(logging_setup):
    ls, buf = logging_setup
    logging.getLogger("alert-service").info("hello world")
    payload = _last_json(buf)

    # The non-negotiable Serilog Compact contract.
    assert payload["@m"] == "hello world"
    assert payload["@l"] == "Information"
    assert "@t" in payload
    assert payload["Service"] == "test-service"


def test_structlog_logger_promotes_known_keys_and_buckets_extras(logging_setup):
    ls, buf = logging_setup
    log = ls.get_logger().bind()
    log.info(
        "scrape.complete",
        Action="scrape.complete",
        Category="job",
        products_scraped=1247,
        proxy_used="uk-3",
    )
    payload = _last_json(buf)

    # Known keys land at the top level for Vector to sweep into typed columns.
    assert payload["Action"] == "scrape.complete"
    assert payload["Category"] == "job"
    assert payload["@m"] == "scrape.complete"

    # Unknown keys land in Context (-> Postgres JSONB).
    assert payload["Context"]["products_scraped"] == 1247
    assert payload["Context"]["proxy_used"] == "uk-3"


def test_level_mapping_uses_serilog_names(logging_setup):
    ls, buf = logging_setup

    cases = {
        "info":     "Information",
        "warning":  "Warning",
        "error":    "Error",
        "critical": "Fatal",
        "debug":    "Debug",
    }
    log = ls.get_logger()
    for stdlib_name, serilog_name in cases.items():
        getattr(log, stdlib_name)(f"event for {stdlib_name}")
        assert _last_json(buf)["@l"] == serilog_name, stdlib_name


# ---------------------------------------------------------------------------
# Context binding
# ---------------------------------------------------------------------------

def test_bind_correlation_id_appears_on_subsequent_logs(logging_setup):
    ls, buf = logging_setup
    cid = ls.bind_correlation_id("fixed-cid-value")
    assert cid == "fixed-cid-value"

    logging.getLogger().info("after binding")
    assert _last_json(buf)["CorrelationId"] == "fixed-cid-value"


def test_bind_correlation_id_generates_uuid_when_no_value(logging_setup):
    ls, buf = logging_setup
    cid = ls.bind_correlation_id()
    assert len(cid) == 32 and all(c in "0123456789abcdef" for c in cid)

    logging.getLogger().info("auto cid")
    assert _last_json(buf)["CorrelationId"] == cid


def test_clear_context_removes_correlation_id(logging_setup):
    ls, buf = logging_setup
    ls.bind_correlation_id("temp-cid")
    ls.clear_context()
    logging.getLogger().info("after clear")
    assert "CorrelationId" not in _last_json(buf)


# ---------------------------------------------------------------------------
# Outgoing-header propagation
# ---------------------------------------------------------------------------

def test_correlation_headers_returns_bound_value(logging_setup):
    ls, _ = logging_setup
    ls.bind_correlation_id("abc-123")
    headers = ls.correlation_headers()
    assert headers == {"X-Correlation-ID": "abc-123"}


def test_correlation_headers_includes_anon_when_bound(logging_setup):
    ls, _ = logging_setup
    ls.bind_correlation_id("abc-123")
    ls.bind_anon_id("anon-xyz")
    headers = ls.correlation_headers()
    assert headers == {
        "X-Correlation-ID": "abc-123",
        "X-Anon-Id": "anon-xyz",
    }


def test_correlation_headers_empty_when_unbound(logging_setup):
    ls, _ = logging_setup
    ls.clear_context()
    assert ls.correlation_headers() == {}


def test_correlation_headers_can_be_spread_into_request(logging_setup):
    """
    Real usage pattern: callers spread `correlation_headers()` into an
    existing dict. The merge must not stomp on caller-provided keys.
    """
    ls, _ = logging_setup
    ls.bind_correlation_id("trace-9")
    user_headers = {"X-Internal-Token": "secret", "Accept": "application/json"}
    merged = {**user_headers, **ls.correlation_headers()}
    assert merged["X-Internal-Token"] == "secret"
    assert merged["Accept"] == "application/json"
    assert merged["X-Correlation-ID"] == "trace-9"


@pytest.mark.anyio
async def test_correlation_middleware_binds_and_echoes_anon_id(logging_setup):
    ls, _ = logging_setup
    mw = ls.correlation_middleware()

    class _Req:
        def __init__(self):
            self.headers = {
                "X-Correlation-ID": "cid-1",
                "X-Anon-Id": "anon-1",
            }

    class _Resp:
        def __init__(self):
            self.headers = {}

    async def _next(_request):
        hdrs = ls.correlation_headers()
        assert hdrs["X-Correlation-ID"] == "cid-1"
        assert hdrs["X-Anon-Id"] == "anon-1"
        return _Resp()

    response = await mw(_Req(), _next)
    assert response.headers["X-Correlation-ID"] == "cid-1"
    assert response.headers["X-Anon-Id"] == "anon-1"


# ---------------------------------------------------------------------------
# uvicorn redirection
# ---------------------------------------------------------------------------

def test_uvicorn_loggers_have_no_local_handlers(logging_setup):
    """
    setup_logging() must strip uvicorn's default handlers so its access /
    error lines flow through the same JSON formatter as everything else.
    """
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        assert not lg.handlers, f"{name} still owns handlers: {lg.handlers}"
        assert lg.propagate is True


def test_uvicorn_access_log_is_emitted_as_json(logging_setup):
    ls, buf = logging_setup
    # Simulate uvicorn writing an access line.
    logging.getLogger("uvicorn.access").info("127.0.0.1:0 - GET / 200 OK")
    payload = _last_json(buf)
    assert payload["@l"] == "Information"
    assert "GET" in payload["@m"]
    assert payload["Service"] == "test-service"
