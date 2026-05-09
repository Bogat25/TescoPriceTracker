"""
Structured logging bootstrap for the TescoPriceTracker Python services.

Each service in this repo (alert-service, auth-gateway, backend-api,
recomendation-system, scheduler, scraper) ships its own copy of this file
so the service is self-contained at build time. The copies are kept
byte-identical; ``tests/test_logging_parity.py`` enforces that.

What it does
------------
1. Configures ``structlog`` to emit one JSON Lines event per log call to
   stdout. The wire format is the well-known **Serilog-Compact** shape:
   ``@t`` (timestamp), ``@l`` (level), ``@m`` (rendered message), plus
   ``Service``, ``Category``, ``Action``, ``RequestId``, ``CorrelationId``
   and any extra kwargs in a ``Context`` object.
2. Routes the standard library's ``logging`` module through the same
   formatter, so any third-party library that does
   ``logger = logging.getLogger(__name__); logger.info(...)`` produces
   the same JSON shape with no per-call-site changes.
3. Redirects ``uvicorn``, ``uvicorn.access``, ``uvicorn.error`` so HTTP
   access lines are also JSON.
4. Exposes context binders:
       * ``bind_correlation_id(value)`` — bind for the current async task / thread.
       * ``clear_context()``           — wipe at job-end / request-end.
5. Provides ``correlation_middleware()`` — a FastAPI middleware factory
   that reads ``X-Correlation-ID`` from incoming requests (or generates
   one), binds it for the request, and clears it after.

The output is plain JSON Lines on stdout, so it is consumable by any log
shipper or aggregator that understands Docker container logs (Vector,
Fluent Bit, Promtail/Loki, ELK, Datadog Agent, etc.) — or just by
``docker logs`` for ad-hoc inspection.

Field reference
---------------
   @t            ISO-8601 UTC timestamp (auto-added)
   @l            Information / Warning / Error / Fatal / Debug
   @m            Rendered message
   @mt           Message template (same as @m for now)
   Service       Logical service name (from SERVICE_NAME env, fallback "unknown")
   Action        Optional verb e.g. "scrape.start"
   Category      Optional bucket e.g. "job", "http"
   RequestId     Optional per-request UUID
   CorrelationId Optional cross-service trace ID (set by middleware/per-job)
   Context       Object holding any extra kwargs supplied at the call site

Usage
-----
At the entrypoint (replaces ``logging.basicConfig``):
    from logging_setup import setup_logging
    setup_logging()              # reads SERVICE_NAME from env

In FastAPI services, after ``app = FastAPI(...)``:
    from logging_setup import correlation_middleware
    app.middleware("http")(correlation_middleware())

In background scripts, around each job run:
    from logging_setup import bind_correlation_id, clear_context
    bind_correlation_id()        # generate a fresh one for this run
    try:
        run_job()
    finally:
        clear_context()
"""
from __future__ import annotations

import logging
import os
import sys
import uuid
from typing import Awaitable, Callable, Optional

import structlog


# Stable env var name. Each service's compose entry sets this so logs can
# be grouped by `Service` even when multiple services share one image.
_SERVICE_NAME_ENV = "SERVICE_NAME"
_DEFAULT_SERVICE_NAME = "unknown"

# Standard request-correlation header. The FastAPI middleware reads it on
# inbound requests and binds the value as `CorrelationId`; outbound HTTP
# calls can echo it via `correlation_headers()` so a single trace ID can
# follow a request across service boundaries.
_CORRELATION_HEADER = "X-Correlation-ID"

# Map structlog's lowercase level names to the Serilog-Compact level
# vocabulary used on the wire (Information / Warning / Error / Fatal /
# Debug). This keeps the JSON output compatible with tooling that
# understands the Serilog-Compact format out of the box.
_LEVEL_TO_SERILOG = {
    "critical": "Fatal",
    "fatal":    "Fatal",
    "error":    "Error",
    "warning":  "Warning",
    "warn":     "Warning",
    "info":     "Information",
    "debug":    "Debug",
    "notset":   "Information",
}


def _service_name() -> str:
    return os.environ.get(_SERVICE_NAME_ENV) or _DEFAULT_SERVICE_NAME


def _rename_to_serilog_compact(_logger, _method, event_dict):
    """
    Map structlog's default keys onto the Serilog-Compact wire format.
       timestamp -> @t
       level     -> @l (also remapped to Serilog level naming)
       event     -> @m and @mt
    Any kwargs the call site passed are bucketed into a `Context` object
    so the top-level JSON keeps a stable, predictable shape regardless
    of what callers pass in.
    """
    event_dict["@t"] = event_dict.pop("timestamp", None)
    raw_level = str(event_dict.pop("level", "info")).lower()
    event_dict["@l"] = _LEVEL_TO_SERILOG.get(raw_level, "Information")
    msg = event_dict.pop("event", "")
    event_dict["@m"] = msg
    event_dict["@mt"] = msg

    reserved = {"@t", "@l", "@m", "@mt", "Service", "Category", "Action",
                "RequestId", "CorrelationId", "Context", "exception", "exc_info"}
    extras = {k: event_dict.pop(k) for k in list(event_dict.keys()) if k not in reserved}
    if extras:
        ctx = event_dict.get("Context")
        if isinstance(ctx, dict):
            ctx.update(extras)
        else:
            event_dict["Context"] = extras
    return event_dict


def _add_service(_logger, _method, event_dict):
    event_dict.setdefault("Service", _service_name())
    return event_dict


def setup_logging(level: Optional[str] = None) -> None:
    """
    Configure structlog + stdlib logging + uvicorn loggers to emit JSON.

    Idempotent: safe to call more than once (later calls reset handlers).
    """
    log_level_name = (level or os.environ.get("LOG_LEVEL") or "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    # Pre-chain runs on every event regardless of how it was emitted.
    pre_chain = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_service,
    ]

    # The final formatter the stdlib handler uses to render any record
    # (including those coming from non-structlog libraries like uvicorn).
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=pre_chain,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _rename_to_serilog_compact,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # uvicorn ships its own loggers configured with separate handlers.
    # Strip those and let them propagate to root.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
        lg.setLevel(log_level)

    structlog.configure(
        processors=[
            *pre_chain,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: Optional[str] = None):
    """Convenience accessor; preserves caller-provided logger names."""
    return structlog.get_logger(name) if name else structlog.get_logger()


# ── Context binders ──────────────────────────────────────────────────────────

def bind_correlation_id(value: Optional[str] = None) -> str:
    """
    Bind a correlation ID for the current async task / thread. Returns the
    value that was bound so callers can echo it in response headers.
    """
    cid = value or uuid.uuid4().hex
    structlog.contextvars.bind_contextvars(CorrelationId=cid)
    return cid


def bind_request_id(value: Optional[str] = None) -> str:
    rid = value or uuid.uuid4().hex
    structlog.contextvars.bind_contextvars(RequestId=rid)
    return rid


def clear_context() -> None:
    """Drop all contextvars. Call at job-end / request-end."""
    structlog.contextvars.clear_contextvars()


def correlation_headers() -> dict[str, str]:
    """
    Return a header dict suitable for spreading into outgoing HTTP calls so
    the trace ID survives the next hop:

        async with httpx.AsyncClient() as c:
            r = await c.get(url, headers={**correlation_headers(), ...})

    Returns an empty dict if no correlation ID has been bound yet (e.g.
    during startup or in unit tests). Never raises.
    """
    bound = structlog.contextvars.get_contextvars()
    cid = bound.get("CorrelationId")
    if not cid:
        return {}
    return {_CORRELATION_HEADER: str(cid)}


# ── FastAPI middleware ───────────────────────────────────────────────────────

def correlation_middleware():
    """
    Returns an ASGI middleware function suitable for `app.middleware("http")`.

    Reads X-Correlation-ID from the incoming request (generates one if
    absent), binds it as `CorrelationId` on the structlog context for the
    duration of the request, and echoes it in the response so downstream
    services can pick it up.
    """
    async def middleware(request, call_next: Callable[..., Awaitable]):
        incoming = request.headers.get(_CORRELATION_HEADER)
        cid = bind_correlation_id(incoming)
        rid = bind_request_id()
        try:
            response = await call_next(request)
            response.headers[_CORRELATION_HEADER] = cid
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            clear_context()

    return middleware
