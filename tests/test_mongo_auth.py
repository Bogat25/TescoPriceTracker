"""Per-service MongoDB credentials: the URI they build, and the compose wiring."""

import logging
from pathlib import Path

import pytest
import yaml

import mongo_auth
from mongo import init_users


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
    # Root stays with the admin tool (off unless COMPOSE_PROFILES says otherwise)
    # and with the job whose whole purpose is managing accounts.
    applications = using_mongo - {"mongo-express", "mongo-users"}
    assert applications
    for name in applications:
        environment = services[name]["environment"]
        assert "MONGO_USER" in environment and "MONGO_PASSWORD" in environment, name
        assert services[name]["depends_on"]["mongo-users"]["condition"] == "service_completed_successfully", name
    assert "profiles" in services["mongo-express"]


def test_the_account_creator_runs_once_from_the_application_image():
    compose = _compose()
    creator = compose["services"]["mongo-users"]
    assert creator["restart"] == "no"
    assert creator["depends_on"]["mongo"]["condition"] == "service_healthy"
    assert creator["command"] == "python -m mongo.init_users"
    # Portainer git stacks do not ship repo files to the host, so the script
    # travels inside the image instead of a bind-mounted config.
    assert "configs" not in compose and "configs" not in creator
    assert "tescopricetracker" in creator["image"]


class FakeAdmin:
    def __init__(self, users=()):
        self.users = list(users)
        self.commands = []

    def command(self, name, *args, **kwargs):
        if name == "usersInfo":
            return {"users": [{"user": user} for user in self.users]}
        self.commands.append((name, args[0], kwargs["roles"]))
        return {"ok": 1}


def test_accounts_get_only_the_databases_they_use(monkeypatch):
    monkeypatch.setenv("MONGO_API_PASSWORD", "a")
    monkeypatch.setenv("MONGO_SCRAPER_PASSWORD", "b")
    monkeypatch.setenv("MONGO_ALERTS_PASSWORD", "c")
    by_user = {a["user"]: a for a in init_users.accounts("catalogue", "alerts")}

    assert by_user["svc_scraper"]["roles"] == [{"role": "readWrite", "db": "catalogue"}]
    assert by_user["svc_api"]["roles"] == [{"role": "readWrite", "db": "catalogue"}, {"role": "read", "db": "alerts"}]
    assert by_user["svc_alerts"]["roles"] == [{"role": "readWrite", "db": "alerts"}, {"role": "read", "db": "catalogue"}]


def test_existing_accounts_are_updated_and_new_ones_created():
    admin = FakeAdmin(users=["svc_api"])
    wanted = [
        {"user": "svc_api", "password": "a", "roles": [{"role": "readWrite", "db": "catalogue"}]},
        {"user": "svc_alerts", "password": "c", "roles": [{"role": "readWrite", "db": "alerts"}]},
    ]

    assert init_users.apply(admin, wanted) == {"created": 1, "updated": 1, "skipped": 0}
    assert [(name, user) for name, user, _ in admin.commands] == [("updateUser", "svc_api"), ("createUser", "svc_alerts")]


def test_an_account_without_a_password_is_left_alone(caplog):
    admin = FakeAdmin()
    counts = init_users.apply(admin, [{"user": "svc_api", "password": "", "roles": []}])

    assert counts == {"created": 0, "updated": 0, "skipped": 1}
    assert admin.commands == []
    assert [r for r in caplog.records if getattr(r, "Action", None) == "mongo.account_skipped"]
