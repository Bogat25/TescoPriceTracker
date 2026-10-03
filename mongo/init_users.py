"""Create one MongoDB account per service, so no application connects as root.

Runs once per deploy (the ``mongo-users`` container) with the root account.
It is idempotent: an existing account has its roles and password reset to what
this file says, so rotating a password in Infisical and reconciling is enough.
An account whose password is not configured is skipped, which keeps a
half-finished rollout working on the previous credentials.

The root password is applied here too. MongoDB reads
``MONGO_INITDB_ROOT_PASSWORD`` only when the data volume is created, so a new
root password in Infisical would otherwise change nothing but this job's login.
When the configured password is refused, the job logs in with the last one
that worked, kept on the credential-state volume, and changes root's password
to the configured one.

Rights follow what each service actually does:

``svc_api``      reads the catalogue, writes cached statistics and the store
                 registry, reads alerts for recommendations
``svc_scraper``  writes the catalogue (both schedulers and the vectorizer)
``svc_alerts``   owns the alert database, reads the catalogue for price drops

    python -m mongo.init_users
"""

import logging
import os
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit

from pymongo import MongoClient
from pymongo.errors import OperationFailure, PyMongoError

import mongo_auth

# The application image keeps a self-contained logging bootstrap in each
# service directory.  This one-shot module runs from /app, so make one of
# those copies importable before loading it.
sys.path.append(str(Path(__file__).resolve().parent.parent / "backend-api"))
from logging_setup import setup_logging

logger = logging.getLogger(__name__)

APP_DB = os.environ.get("MONGO_DB_NAME", "tesco_tracker")
ALERTS_DB = os.environ.get("MONGO_ALERTS_DB_NAME", "tesco_alerts")
STATE_DIR = Path(os.environ.get("CREDENTIAL_STATE_DIR", "/var/lib/credential-state"))
ROOT_STATE_FILE = "mongo-root-password"
AUTHENTICATION_FAILED = 18


class RootPasswordUnknown(Exception):
    """Neither the configured nor the last recorded root password logs in."""


def accounts(app_db: str = None, alerts_db: str = None) -> list:
    app_db = app_db or APP_DB
    alerts_db = alerts_db or ALERTS_DB
    return [
        {
            "user": os.environ.get("MONGO_API_USERNAME", "svc_api"),
            "password": os.environ.get("MONGO_API_PASSWORD", ""),
            "roles": [{"role": "readWrite", "db": app_db}, {"role": "read", "db": alerts_db}],
        },
        {
            "user": os.environ.get("MONGO_SCRAPER_USERNAME", "svc_scraper"),
            "password": os.environ.get("MONGO_SCRAPER_PASSWORD", ""),
            "roles": [{"role": "readWrite", "db": app_db}],
        },
        {
            "user": os.environ.get("MONGO_ALERTS_USERNAME", "svc_alerts"),
            "password": os.environ.get("MONGO_ALERTS_PASSWORD", ""),
            "roles": [{"role": "readWrite", "db": alerts_db}, {"role": "read", "db": app_db}],
        },
    ]


def existing_users(admin) -> set:
    return {user["user"] for user in admin.command("usersInfo")["users"]}


def apply(admin, wanted: list) -> dict:
    counts = {"created": 0, "updated": 0, "skipped": 0}
    present = existing_users(admin)
    for account in wanted:
        if not account["password"]:
            counts["skipped"] += 1
            logger.warning(
                "No password configured for %s; leaving its credentials as they are.", account["user"],
                extra={"Action": "mongo.account_skipped", "Category": "startup", "Account": account["user"]},
            )
            continue
        command = "updateUser" if account["user"] in present else "createUser"
        admin.command(command, account["user"], pwd=account["password"], roles=account["roles"])
        counts["created" if command == "createUser" else "updated"] += 1
    return counts


def recorded_root_password(state_dir: Path) -> str:
    try:
        return (state_dir / ROOT_STATE_FILE).read_text()
    except OSError:
        return ""


def record_root_password(state_dir: Path, password: str) -> None:
    """Keep the root password in use, so the next change can log in with it."""
    if recorded_root_password(state_dir) == password:
        return
    path = state_dir / ROOT_STATE_FILE
    temporary = path.with_name(path.name + ".tmp")
    try:
        state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary.unlink(missing_ok=True)
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
            handle.write(password)
        os.replace(temporary, path)
    except OSError as exc:
        logger.warning(
            "Could not record the MongoDB root password in %s (%s); the next change has to be made by hand.",
            state_dir, exc.__class__.__name__,
            extra={"Action": "mongo.root_password_unrecorded", "Category": "startup"},
        )
        return
    logger.info("Recorded the MongoDB root password in use, for the next change.",
                extra={"Action": "mongo.root_password_recorded", "Category": "startup"})


def connect_as_root(uri: str, state_dir: Path = None, client_factory=MongoClient):
    """A client logged in as root with the configured password, applying it if it is new."""
    state_dir = state_dir or STATE_DIR
    parts = urlsplit(uri)
    user, password = unquote(parts.username or ""), unquote(parts.password or "")
    client = client_factory(uri, serverSelectionTimeoutMS=30000)
    if not password:
        return client  # no authentication configured, nothing to apply

    try:
        client.admin.command("ping")
    except OperationFailure as exc:
        if exc.code != AUTHENTICATION_FAILED:
            raise
        client.close()
        previous = recorded_root_password(state_dir)
        if not previous or previous == password:
            raise RootPasswordUnknown() from None
        old = client_factory(mongo_auth.service_uri(uri, user, previous), serverSelectionTimeoutMS=30000)
        try:
            old.admin.command("updateUser", user, pwd=password)
        except OperationFailure as old_exc:
            if old_exc.code != AUTHENTICATION_FAILED:
                raise
            raise RootPasswordUnknown() from None
        finally:
            old.close()
        client = client_factory(uri, serverSelectionTimeoutMS=30000)
        client.admin.command("ping")
        logger.info("Changed the MongoDB root password to the configured one.",
                    extra={"Action": "mongo.root_password_rotated", "Category": "startup"})

    record_root_password(state_dir, password)
    return client


def main() -> int:
    setup_logging()
    uri = os.environ.get("MONGO_URI")
    if not uri:
        logger.error("MONGO_URI is not set; cannot create the service accounts.",
                     extra={"Action": "mongo.accounts_failed", "Category": "startup"})
        return 1
    try:
        client = connect_as_root(uri)
        counts = apply(client["admin"], accounts())
    except RootPasswordUnknown:
        # Never block the deploy: the services keep their own accounts as they
        # are, and the next deploy retries once the password is sorted out.
        logger.error(
            "Neither the configured nor the last recorded MongoDB root password logs in; "
            "the service accounts were left as they are. See docs/deployment.md, "
            "'Rotating the infrastructure credentials'.",
            extra={"Action": "mongo.root_password_unknown", "Category": "startup"},
        )
        return 0
    except PyMongoError as exc:
        # Never block the deploy: the services fall back to the credentials in
        # MONGO_URI and log mongo.root_credentials, which is visible in Grafana.
        logger.error("Could not create the MongoDB service accounts: %s", exc,
                     extra={"Action": "mongo.accounts_failed", "Category": "startup"})
        return 0
    logger.info(
        "MongoDB service accounts: %s created, %s updated, %s skipped.",
        counts["created"], counts["updated"], counts["skipped"],
        extra={"Action": "mongo.accounts_ready", "Category": "startup", **{
            f"{key.capitalize()}Count": value for key, value in counts.items()}},
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
