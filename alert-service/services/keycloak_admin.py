"""Keycloak Admin API client for the daily user sync.

Authenticates as the ``tesco-alert-admin`` confidential client (client-credentials
grant) with the ``view-users`` realm-management role. Pages through realm users
and yields ``(sub, email)`` for each user that has an email.
"""

import logging
from typing import AsyncIterator, Optional

import httpx

import settings


logger = logging.getLogger(__name__)


class KeycloakAdminError(RuntimeError):
    pass


async def _get_admin_token(client: httpx.AsyncClient) -> str:
    url = (
        f"{settings.KC_ADMIN_BASE_URL}/realms/{settings.KEYCLOAK_REALM}"
        "/protocol/openid-connect/token"
    )
    data = {
        "grant_type": "client_credentials",
        "client_id": settings.KC_ADMIN_CLIENT_ID,
        "client_secret": settings.KC_ADMIN_CLIENT_SECRET,
    }
    r = await client.post(url, data=data, headers={"Accept": "application/json"})
    if r.status_code != 200:
        raise KeycloakAdminError(
            f"admin token request failed: {r.status_code} {r.text}"
        )
    payload = r.json()
    token = payload.get("access_token")
    if not token:
        raise KeycloakAdminError("admin token response missing access_token")
    return token


async def iter_users() -> AsyncIterator[tuple[str, Optional[str]]]:
    """Yield (sub, email) tuples for every user in the realm."""
    if not settings.KC_ADMIN_CLIENT_SECRET:
        raise KeycloakAdminError("KC_ADMIN_CLIENT_SECRET is not configured")

    page_size = settings.KEYCLOAK_SYNC_PAGE_SIZE
    users_url = (
        f"{settings.KC_ADMIN_BASE_URL}/admin/realms/{settings.KEYCLOAK_REALM}/users"
    )

    async with httpx.AsyncClient(timeout=20.0) as client:
        token = await _get_admin_token(client)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

        first = 0
        while True:
            r = await client.get(
                users_url,
                params={"first": first, "max": page_size, "briefRepresentation": "true"},
                headers=headers,
            )
            if r.status_code == 401:
                # Token can expire mid-sweep on a slow run. Refresh once and retry.
                token = await _get_admin_token(client)
                headers["Authorization"] = f"Bearer {token}"
                r = await client.get(
                    users_url,
                    params={"first": first, "max": page_size, "briefRepresentation": "true"},
                    headers=headers,
                )
            if r.status_code != 200:
                raise KeycloakAdminError(
                    f"admin users request failed: {r.status_code} {r.text}"
                )

            batch = r.json()
            if not batch:
                return
            for user in batch:
                sub = user.get("id")
                if not sub:
                    continue
                yield sub, user.get("email")
            if len(batch) < page_size:
                return
            first += page_size
