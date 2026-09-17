"""HTTP client for the auchan.hu shop API.

The shop gives every anonymous visitor a bearer token (``/fe-api/get-token``)
and serves the catalogue from ``/api/v2``. The client paces requests, renews
the token when it expires, and separates outages (worth retrying later) from
contract changes (a code fix is needed).
"""

import logging
import os
import random
import time
from typing import Callable, Optional

import requests


logger = logging.getLogger(__name__)

BASE_URL = os.getenv("AUCHAN_BASE_URL", "https://auchan.hu").rstrip("/")
USER_AGENT = os.getenv(
    "AUCHAN_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36",
)
MIN_REQUEST_INTERVAL_SECONDS = float(os.getenv("AUCHAN_MIN_REQUEST_INTERVAL_SECONDS", "1.0"))
MAX_ITEMS_PER_PAGE = 100          # the API rejects larger pages
MAX_RETRY_AFTER_SECONDS = 15 * 60  # longer waits end the pass instead


class AuchanError(RuntimeError):
    pass


class AuchanUnavailable(AuchanError):
    """Transient failure (network, 429, 5xx); a later pass can resume."""

    def __init__(self, message, retry_after: Optional[float] = None, status_code: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after
        self.status_code = status_code


class AuchanContractError(AuchanError):
    """The API answered, but not in the shape this client was written for."""


def _retry_after_seconds(value) -> Optional[float]:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


class AuchanClient:

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        base_url: str = BASE_URL,
        min_interval: float = MIN_REQUEST_INTERVAL_SECONDS,
        max_attempts: int = 4,
        timeout: float = 90.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._session = session or requests.Session()
        self._session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Origin": base_url,
            "Referer": f"{base_url}/shop",
        })
        self._base_url = base_url
        self._min_interval = min_interval
        self._max_attempts = max_attempts
        self._timeout = timeout
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: Optional[float] = None
        self._token: Optional[str] = None

    # -- transport ----------------------------------------------------------

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            wait = self._min_interval - (self._clock() - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = self._clock()

    def _send(self, method: str, path: str, **kwargs) -> requests.Response:
        self._throttle()
        return self._session.request(method, f"{self._base_url}{path}", timeout=self._timeout, **kwargs)

    def _refresh_token(self) -> None:
        response = self._send("POST", "/fe-api/get-token", json={"grant_type": "anonymous"})
        if response.status_code in (429,) or response.status_code >= 500:
            raise AuchanUnavailable(f"token endpoint HTTP {response.status_code}",
                                    retry_after=_retry_after_seconds(response.headers.get("Retry-After")),
                                    status_code=response.status_code)
        if response.status_code != 200:
            raise AuchanContractError(f"token endpoint HTTP {response.status_code}")
        try:
            body = response.json()
            token = body["access_token"]
        except (ValueError, KeyError, TypeError) as exc:
            raise AuchanContractError("token response has no access_token") from exc
        self._token = f"{body.get('token_type') or 'Bearer'} {token}"
        logger.info("Obtained an anonymous Auchan API token.",
                    extra={"Action": "auchan.token_refreshed", "Category": "upstream"})

    def get_json(self, path: str, params: Optional[dict] = None):
        """GET an ``/api/v2`` path with pacing, token renewal and retries."""
        renewed = False
        for attempt in range(1, self._max_attempts + 1):
            try:
                if self._token is None:
                    self._refresh_token()
                response = self._send("GET", path, params=params, headers={"Authorization": self._token})
            except requests.RequestException as exc:
                error: AuchanUnavailable = AuchanUnavailable(f"{type(exc).__name__} for {path}")
            except AuchanUnavailable as exc:
                error = exc
            else:
                if response.status_code == 401 and not renewed:
                    self._token = None
                    renewed = True
                    continue
                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise AuchanContractError(f"non-JSON response for {path}") from exc
                if response.status_code == 429 or response.status_code >= 500:
                    error = AuchanUnavailable(
                        f"HTTP {response.status_code} for {path}",
                        retry_after=_retry_after_seconds(response.headers.get("Retry-After")),
                        status_code=response.status_code,
                    )
                else:
                    raise AuchanContractError(f"HTTP {response.status_code} for {path}: {response.text[:300]}")

            if error.retry_after is not None and error.retry_after > MAX_RETRY_AFTER_SECONDS:
                raise error
            if attempt == self._max_attempts:
                logger.error(
                    "Auchan request failed after %s attempts: %s", attempt, error,
                    extra={"Action": "auchan.request_retry_exhausted", "Category": "upstream",
                           "HttpStatus": error.status_code},
                )
                raise error
            delay = max(error.retry_after or 0, 2 ** attempt + random.uniform(0, 1))
            logger.warning(
                "Auchan request failed (attempt %s/%s), retrying in %.0fs: %s",
                attempt, self._max_attempts, delay, error,
                extra={"Action": "auchan.request_retry", "Category": "upstream",
                       "HttpStatus": error.status_code, "RetryAfterSeconds": error.retry_after},
            )
            self._sleep(delay)
        raise AuchanUnavailable(f"token renewal did not succeed for {path}")

    # -- endpoints ----------------------------------------------------------

    def category_tree(self) -> list:
        body = self.get_json("/api/v2/tree/0", params={"depth": 1})
        children = body.get("children") if isinstance(body, dict) else None
        if not isinstance(children, list):
            raise AuchanContractError("category tree has no children list")
        return children

    def list_products(self, category_id: int, page: int, per_page: int = MAX_ITEMS_PER_PAGE) -> dict:
        body = self.get_json("/api/v2/products", params={
            "page": page,
            "itemsPerPage": min(per_page, MAX_ITEMS_PER_PAGE),
            "isCached": "true",
            "categories": category_id,
        })
        if not isinstance(body, dict) or not isinstance(body.get("results"), list):
            raise AuchanContractError(f"product list for category {category_id} has no results list")
        try:
            body["pageCount"] = int(body.get("pageCount") or 0)
            body["itemCount"] = int(body.get("itemCount") or 0)
        except (TypeError, ValueError) as exc:
            raise AuchanContractError("product list paging fields are not numbers") from exc
        return body

    def product_details(self, product_id, variant_id) -> list:
        body = self.get_json(f"/api/v2/products/{int(product_id)}/variants/{int(variant_id)}/details")
        if not isinstance(body, list):
            raise AuchanContractError(f"details for product {product_id} are not a list")
        return body
