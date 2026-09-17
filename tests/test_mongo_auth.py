"""Per-service MongoDB credentials: the URI they build, and the compose wiring."""

import logging
from pathlib import Path

import pytest
import yaml

import mongo_auth


ROOT = Path(__file__).resolve().parent.parent
ROOT_URI = "mongodb://admin:secretpassword@mongo:27017/"


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(mongo_auth, "_warned", False)
    monkeypatch.delenv("MONGO_USER", raising=False)
    monkeypatch.delenv("MONGO_PASSWORD", raising=False)


def test_service_credentials_replace_the_ones_in_the_uri():
    uri = mongo_auth.service_uri(ROOT_URI, "svc_api", "pw")
    assert uri == "mongodb://svc_api:pw@mongo:27017/"


def test_credentials_are_percent_encoded():
    uri = mongo_auth.service_uri(ROOT_URI, "svc_api", "p@ss:w/rd")
    assert uri == "mongodb://svc_api:p%40ss%3Aw%2Frd@mongo:27017/"


def test_query_options_survive():
    base = "mongodb://admin:pw@mongo:27017/?replicaSet=rs0"
    assert mongo_auth.service_uri(base, "svc", "x") == "mongodb://svc:x@mongo:27017/?replicaSet=rs0"


def test_without_credentials_the_uri_is_unchanged_and_warned(caplog):
    caplog.set_level(logging.WARNING)
    assert mongo_auth.service_uri(ROOT_URI, "", "", service="api") == ROOT_URI
    records = [r for r in caplog.records if getattr(r, "Action", None) == "mongo.root_credentials"]
    assert len(records) == 1
    # Once per process, not once per connection.
    mongo_auth.service_uri(ROOT_URI, "", "", service="api")
    assert len([r for r in caplog.records if getattr(r, "Action", None) == "mongo.root_credentials"]) == 1


def test_environment_supplies_the_credentials(monkeypatch):
    monkeypatch.setenv("MONGO_USER", "svc_scraper")
    monkeypatch.setenv("MONGO_PASSWORD", "pw")
    assert mongo_auth.service_uri(ROOT_URI) == "mongodb://svc_scraper:pw@mongo:27017/"


def _compose():
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_every_application_service_has_its_own_account():
    services = _compose()["services"]
    using_mongo = {name for name, spec in services.items()
                   if "MONGO_URI" in (spec.get("environment") or {})}
    # The admin tool keeps root; it is off unless COMPOSE_PROFILES says otherwise.
    assert using_mongo - {"mongo-express"} != set()
    for name in using_mongo - {"mongo-express"}:
        environment = services[name]["environment"]
        assert "MONGO_USER" in environment and "MONGO_PASSWORD" in environment, name
        assert services[name]["depends_on"]["mongo-users"]["condition"] == "service_completed_successfully", name
    assert "profiles" in services["mongo-express"]


def test_the_account_creator_runs_once_with_the_script():
    services = _compose()["services"]
    creator = services["mongo-users"]
    assert creator["restart"] == "no"
    assert creator["depends_on"]["mongo"]["condition"] == "service_healthy"
    assert creator["configs"][0]["target"] == "/scripts/init-users.js"
    assert _compose()["configs"]["mongo_init_users"]["file"] == "./mongo/init-users.js"
    script = (ROOT / "mongo" / "init-users.js").read_text(encoding="utf-8")
    # Skipping an account without a password is what makes a partial rollout safe.
    assert "no password configured" in script
    assert "updateUser" in script and "createUser" in script
