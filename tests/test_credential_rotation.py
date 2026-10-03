"""Applying a new MongoDB root password and Keycloak credentials on deploy.

MongoDB and Keycloak read their admin credentials only on the very first start,
so a value changed in Infisical has to be applied by the deploy itself: the
mongo-users and keycloak-config jobs log in with the last value that worked
and change it to the configured one.
"""

import logging
import os
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

import pytest
from pymongo.errors import OperationFailure
import yaml

from mongo import init_users


ROOT = Path(__file__).resolve().parent.parent


class FakeServer:
    def __init__(self, password):
        self.user = "admin"
        self.password = password
        self.updated = []


class FakeClient:
    """Logs in on every command, as pymongo does with credentials in the URI."""

    def __init__(self, server, uri):
        parts = urlsplit(uri)
        self.server = server
        self.user = unquote(parts.username or "")
        self.password = unquote(parts.password or "")
        self.admin = self

    def command(self, name, *args, **kwargs):
        if self.password and (self.user, self.password) != (self.server.user, self.server.password):
            raise OperationFailure("Authentication failed.", code=18)
        if name == "updateUser":
            self.server.password = kwargs["pwd"]
            self.server.updated.append(args[0])
        return {"ok": 1}

    def close(self):
        pass


def _factory(server):
    return lambda uri, **_: FakeClient(server, uri)


def _uri(password):
    return f"mongodb://admin:{password}@mongo:27017/"


def _record(state_dir):
    return (state_dir / init_users.ROOT_STATE_FILE).read_text()


def _actions(caplog):
    return [getattr(r, "Action", None) for r in caplog.records]


def test_the_root_password_in_use_is_recorded(tmp_path):
    server = FakeServer("current")

    client = init_users.connect_as_root(_uri("current"), tmp_path, _factory(server))

    assert client.password == "current"
    assert server.updated == []
    assert _record(tmp_path) == "current"


def test_a_new_root_password_is_applied_with_the_recorded_one(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    server = FakeServer("old")
    (tmp_path / init_users.ROOT_STATE_FILE).write_text("old")

    client = init_users.connect_as_root(_uri("new"), tmp_path, _factory(server))

    assert server.updated == ["admin"]
    assert server.password == "new"
    assert client.password == "new"
    assert _record(tmp_path) == "new"
    assert "mongo.root_password_rotated" in _actions(caplog)


def test_a_percent_encoded_password_is_applied_decoded(tmp_path):
    server = FakeServer("old")
    (tmp_path / init_users.ROOT_STATE_FILE).write_text("old")

    init_users.connect_as_root(_uri("p%40ss%3Aw%2Frd"), tmp_path, _factory(server))

    assert server.password == "p@ss:w/rd"
    assert _record(tmp_path) == "p@ss:w/rd"


def test_nothing_changes_when_the_recorded_password_is_refused_too(tmp_path):
    server = FakeServer("changed-by-hand")
    (tmp_path / init_users.ROOT_STATE_FILE).write_text("old")

    with pytest.raises(init_users.RootPasswordUnknown):
        init_users.connect_as_root(_uri("new"), tmp_path, _factory(server))

    assert server.password == "changed-by-hand"
    assert _record(tmp_path) == "old"


def test_a_refused_password_without_a_record_is_reported(tmp_path):
    with pytest.raises(init_users.RootPasswordUnknown):
        init_users.connect_as_root(_uri("new"), tmp_path, _factory(FakeServer("old")))


def test_a_uri_without_credentials_is_left_alone(tmp_path):
    init_users.connect_as_root("mongodb://localhost:27017/", tmp_path, _factory(FakeServer("old")))

    assert not (tmp_path / init_users.ROOT_STATE_FILE).exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_the_record_is_readable_by_its_owner_only(tmp_path):
    init_users.connect_as_root(_uri("current"), tmp_path, _factory(FakeServer("current")))

    assert (tmp_path / init_users.ROOT_STATE_FILE).stat().st_mode & 0o777 == 0o600


def test_an_unwritable_record_does_not_stop_the_job(tmp_path, caplog):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("")

    client = init_users.connect_as_root(_uri("current"), blocked, _factory(FakeServer("current")))

    assert client.password == "current"
    assert "mongo.root_password_unrecorded" in _actions(caplog)


def test_an_unknown_root_password_does_not_block_the_deploy(monkeypatch, caplog):
    def refuse(uri):
        raise init_users.RootPasswordUnknown()

    monkeypatch.setenv("MONGO_URI", _uri("new"))
    monkeypatch.setattr(init_users, "setup_logging", lambda: None)
    monkeypatch.setattr(init_users, "connect_as_root", refuse)

    assert init_users.main() == 0
    assert "mongo.root_password_unknown" in _actions(caplog)


def _compose():
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_the_mongo_health_check_does_not_log_in():
    test = " ".join(_compose()["services"]["mongo"]["healthcheck"]["test"])

    assert "PASSWORD" not in test and " -p " not in test
    assert "ping" in test


def test_mongo_users_keeps_its_record_on_a_volume():
    compose = _compose()
    job = compose["services"]["mongo-users"]
    state_dir = job["environment"]["CREDENTIAL_STATE_DIR"]

    assert f"mongo-credential-state:{state_dir}" in job["volumes"]
    assert "mongo-credential-state" in compose["volumes"]


def test_keycloak_config_gets_the_credentials_it_applies():
    job = _compose()["services"]["keycloak-config"]

    for key in ("KC_BOOTSTRAP_ADMIN_PASSWORD", "KC_ADMIN_CLIENT_ID", "KC_ADMIN_CLIENT_SECRET"):
        assert key in job["environment"], key
    assert "keycloak-data:/opt/keycloak/data" in job["volumes"]
    assert job["entrypoint"][-1] == "/opt/keycloak/bin/configure-keycloak.sh"
    dockerfile = (ROOT / "keycloak" / "Dockerfile").read_text()
    assert "keycloak/configure-keycloak.sh /opt/keycloak/bin/configure-keycloak.sh" in dockerfile


def test_keycloak_config_never_puts_a_credential_on_a_command_line_or_in_the_log():
    script = (ROOT / "keycloak" / "configure-keycloak.sh").read_text()
    credentials = r"\$\{?(KC_BOOTSTRAP_ADMIN_PASSWORD|KC_ADMIN_CLIENT_SECRET|current)\b"

    assert "--password" not in script and "--secret" not in script
    assert 'KC_CLI_PASSWORD="$1"' in script
    for line in script.splitlines():
        if re.search(r"\becho\b", line):
            assert not re.search(credentials, line), line
