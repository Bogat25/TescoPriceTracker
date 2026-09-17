"""Create one MongoDB account per service, so no application connects as root.

Runs once per deploy (the ``mongo-users`` container) with the root account.
It is idempotent: an existing account has its roles and password reset to what
this file says, so rotating a password in Infisical and reconciling is enough.
An account whose password is not configured is skipped, which keeps a
half-finished rollout working on the previous credentials.

Rights follow what each service actually does:

``svc_api``      reads the catalogue, writes cached statistics and the store
                 registry, reads alerts for recommendations
``svc_scraper``  writes the catalogue (both schedulers and the vectorizer)
``svc_alerts``   owns the alert database, reads the catalogue for price drops

    python -m mongo.init_users
"""

import logging
import os
import sys

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from logging_setup import setup_logging

logger = logging.getLogger(__name__)

APP_DB = os.environ.get("MONGO_DB_NAME", "tesco_tracker")
ALERTS_DB = os.environ.get("MONGO_ALERTS_DB_NAME", "tesco_alerts")


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


def main() -> int:
    setup_logging()
    uri = os.environ.get("MONGO_URI")
    if not uri:
        logger.error("MONGO_URI is not set; cannot create the service accounts.",
                     extra={"Action": "mongo.accounts_failed", "Category": "startup"})
        return 1
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=30000)
        counts = apply(client["admin"], accounts())
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
