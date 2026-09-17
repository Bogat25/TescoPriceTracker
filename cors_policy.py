"""Browser origin policy, shared by the public API and the alert service.

Both services are reached from two kinds of client:

* the site itself, on its own hostnames (same origin through nginx, but the
  browser still sends ``Origin`` for XHR after a redirect or from a preview);
* the browser extension's background worker, whose origin is
  ``chrome-extension://<id>`` or ``moz-extension://<uuid>``. Firefox generates
  that UUID per installation, so extension origins cannot be listed one by one
  and are matched by scheme instead.

Anything else is refused, so a random page cannot read a signed-in user's
answers from these APIs. ``ALLOWED_ORIGINS`` overrides the site list per
deployment; ``*`` is accepted but logged as a warning, because it disables the
protection.
"""

import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_ORIGINS = (
    "https://price-tracker.gavaller.com",
    "https://tesco-price-tracker.gavaller.com",
    "https://tesco.gavaller.com",
)
# Browser extensions: the ID (Chrome) or the per-install UUID (Firefox) varies.
EXTENSION_ORIGIN_REGEX = r"^(chrome|moz|safari-web)-extension://[a-zA-Z0-9-]+$"


def allowed_origins(env: str = "ALLOWED_ORIGINS") -> list:
    """Configured origins, or the site's own hostnames when nothing is set."""
    configured = [origin.strip() for origin in os.environ.get(env, "").split(",") if origin.strip()]
    if not configured:
        return list(DEFAULT_ORIGINS)
    if "*" in configured:
        logger.warning(
            "%s allows every browser origin; set it to the site's hostnames instead.", env,
            extra={"Action": "cors.wildcard_configured", "Category": "startup"},
        )
    return configured


def cors_kwargs(methods: list, env: str = "ALLOWED_ORIGINS") -> dict:
    """Arguments for Starlette's ``CORSMiddleware``."""
    origins = allowed_origins(env)
    kwargs = {
        "allow_origins": origins,
        "allow_methods": list(methods),
        "allow_headers": ["Authorization", "Content-Type", "X-Correlation-Id", "X-Request-Id"],
        "allow_credentials": True,
        "max_age": 600,
    }
    if "*" not in origins:
        kwargs["allow_origin_regex"] = EXTENSION_ORIGIN_REGEX
    else:
        # The wildcard and credentials cannot be combined: browsers reject the
        # response. Keep the wildcard meaningful by dropping credentials.
        kwargs["allow_credentials"] = False
    return kwargs
