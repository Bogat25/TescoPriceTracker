"""Browser origin policy: the site and the extension are allowed, nothing else."""

import re

import pytest

import cors_policy


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)


def test_defaults_to_the_sites_own_hostnames():
    assert cors_policy.allowed_origins() == list(cors_policy.DEFAULT_ORIGINS)
    assert "*" not in cors_policy.allowed_origins()


def test_configuration_overrides_the_defaults(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", " https://example.test , https://second.test ")
    assert cors_policy.allowed_origins() == ["https://example.test", "https://second.test"]


def test_extension_origins_are_matched_by_scheme():
    pattern = re.compile(cors_policy.EXTENSION_ORIGIN_REGEX)
    assert pattern.match("chrome-extension://abcdefghijklmnopabcdefghijklmnop")
    assert pattern.match("moz-extension://8f3c1d2e-4b5a-6789-abcd-ef0123456789")
    # Firefox gives every installation its own UUID, so only the scheme can be pinned.
    assert not pattern.match("https://evil.test")
    assert not pattern.match("chrome-extension://abc/../../evil")


def test_credentials_are_allowed_only_with_a_real_allowlist(monkeypatch):
    strict = cors_policy.cors_kwargs(["GET"])
    assert strict["allow_credentials"] is True
    assert strict["allow_origin_regex"] == cors_policy.EXTENSION_ORIGIN_REGEX
    assert strict["allow_methods"] == ["GET"]
    assert "*" not in strict["allow_headers"]

    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    wide = cors_policy.cors_kwargs(["GET"])
    # Browsers reject "*" together with credentials, so the wildcard drops them.
    assert wide["allow_credentials"] is False
    assert "allow_origin_regex" not in wide


def test_wildcard_is_logged_as_a_warning(monkeypatch, caplog):
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    cors_policy.allowed_origins()
    assert [r for r in caplog.records if getattr(r, "Action", None) == "cors.wildcard_configured"]
