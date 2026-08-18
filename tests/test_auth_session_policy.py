from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_realm_has_long_lived_refresh_session_policy() -> None:
    # The template contains unquoted JSON-array placeholders that are rendered
    # by docker-entrypoint.sh, so validate the policy fields textually here.
    realm = (ROOT / "keycloak" / "realm-template.json").read_text()
    assert '"accessTokenLifespan": 900' in realm
    assert '"ssoSessionIdleTimeout": 2592000' in realm
    assert '"ssoSessionMaxLifespan": 7776000' in realm
    assert '"clientSessionIdleTimeout": 2592000' in realm
    assert '"clientSessionMaxLifespan": 7776000' in realm


def test_retained_realm_is_updated_after_keycloak_starts() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    service = compose["services"]["keycloak-session-config"]
    assert service["restart"] == "no"
    assert service["depends_on"]["keycloak"]["condition"] == "service_healthy"
    script = (ROOT / "keycloak" / "configure-session-lifetimes.sh").read_text()
    assert 'update "realms/$REALM"' in script
    assert "ssoSessionIdleTimeout=2592000" in script


def test_refreshed_cookie_uses_refresh_token_lifetime() -> None:
    source = (ROOT / "auth-gateway" / "app.py").read_text()
    assert '"rt_exp": int(time.time()) + refresh_expires_in' in source
    assert source.count("max_age=_session_cookie_max_age(") == 3
    assert "max_age=max(expires_in, 60)" not in source
