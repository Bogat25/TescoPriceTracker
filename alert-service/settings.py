"""Env-loaded configuration for the alert service."""

import os


MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
MONGO_ALERTS_DB_NAME = os.environ.get("MONGO_ALERTS_DB_NAME", "tesco_alerts")

KC_INTERNAL_BASE_URL = os.environ.get(
    "KC_INTERNAL_BASE_URL", "http://keycloak:8080/realms/tesco-tracker"
).rstrip("/")
KC_ISSUER = os.environ.get("KC_ISSUER", KC_INTERNAL_BASE_URL).rstrip("/")
KC_CLIENT_ID = os.environ.get("KC_CLIENT_ID", "tesco-frontend")

KC_ADMIN_BASE_URL = os.environ.get(
    "KC_ADMIN_BASE_URL", "http://keycloak:8080"
).rstrip("/")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "tesco-tracker")
KC_ADMIN_CLIENT_ID = os.environ.get("KC_ADMIN_CLIENT_ID", "tesco-alert-admin")
KC_ADMIN_CLIENT_SECRET = os.environ.get("KC_ADMIN_CLIENT_SECRET", "")

INTERNAL_TRIGGER_TOKEN = os.environ.get("INTERNAL_TRIGGER_TOKEN", "")

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM = os.environ.get("RESEND_FROM", "alerts@example.com")
RESEND_REPLY_TO = os.environ.get("RESEND_REPLY_TO", "") or None

JWKS_TTL_SECONDS = int(os.environ.get("JWKS_TTL_SECONDS", "3600"))
RESEND_CONCURRENCY = int(os.environ.get("RESEND_CONCURRENCY", "5"))
TRIGGER_CHUNK_SIZE = int(os.environ.get("TRIGGER_CHUNK_SIZE", "500"))

KEYCLOAK_SYNC_CRON = os.environ.get("KEYCLOAK_SYNC_CRON", "0 3 * * *")
KEYCLOAK_SYNC_PAGE_SIZE = int(os.environ.get("KEYCLOAK_SYNC_PAGE_SIZE", "100"))

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
