"""Per-service MongoDB credentials, with the root account as a visible fallback.

Every service used to connect as the MongoDB root user, so any one of them
could read or drop everything. Each service now has its own account with
rights on the databases it actually uses (``mongo/init-users.js`` creates
them). The credentials arrive as ``MONGO_USER`` and ``MONGO_PASSWORD`` and are
spliced into the configured ``MONGO_URI``.

If a service has no credentials of its own it keeps working with whatever is
in ``MONGO_URI`` and logs ``mongo.root_credentials`` once, so a half-finished
rollout is visible in Grafana instead of silently staying on root.
"""

import logging
import os
from urllib.parse import quote, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

_warned = False


def service_uri(base_uri: str, user: str = None, password: str = None, service: str = None) -> str:
    """``base_uri`` with the service's own credentials, or unchanged with a warning."""
    global _warned
    user = os.environ.get("MONGO_USER", "") if user is None else user
    password = os.environ.get("MONGO_PASSWORD", "") if password is None else password
    service = service or os.environ.get("SERVICE_NAME", "unknown")

    if not user or not password:
        if not _warned:
            _warned = True
            logger.warning(
                "%s connects to MongoDB with the credentials in MONGO_URI; set MONGO_USER "
                "and MONGO_PASSWORD to use its own least-privilege account.", service,
                extra={"Action": "mongo.root_credentials", "Category": "startup", "Service": service},
            )
        return base_uri

    parts = urlsplit(base_uri)
    host = parts.netloc.rsplit("@", 1)[-1]  # drop any credentials already in the URI
    netloc = f"{quote(user, safe='')}:{quote(password, safe='')}@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
