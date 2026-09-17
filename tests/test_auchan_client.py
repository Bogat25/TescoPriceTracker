"""The auchan.hu API client: token handling, pacing, retries and contract errors."""

import pytest
import requests

from stores.auchan.client import AuchanClient, AuchanContractError, AuchanUnavailable


class Response:
    def __init__(self, status, body=None, headers=None, text=""):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = text

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


TOKEN = Response(200, {"token_type": "Bearer", "access_token": "tok-1", "expires_in": 86400})
TOKEN_2 = Response(200, {"token_type": "Bearer", "access_token": "tok-2", "expires_in": 86400})
PAGE = Response(200, {"results": [{"id": 1}], "pageCount": 3.0, "itemCount": 250.0})


def client(responses, sleeps=None, **kwargs):
    session = Session(responses)
    sleeps = sleeps if sleeps is not None else []
    return AuchanClient(session=session, min_interval=0, sleep=sleeps.append, **kwargs), session


def test_fetches_a_token_first_and_sends_it():
    api, session = client([TOKEN, PAGE])
    body = api.list_products(14740, 2)

    assert body["pageCount"] == 3 and body["itemCount"] == 250
    assert session.calls[0][0:2] == ("POST", "https://auchan.hu/fe-api/get-token")
    method, url, kwargs = session.calls[1]
    assert (method, url) == ("GET", "https://auchan.hu/api/v2/products")
    assert kwargs["headers"]["Authorization"] == "Bearer tok-1"
    assert kwargs["params"] == {"page": 2, "itemsPerPage": 100, "isCached": "true", "categories": 14740}


def test_expired_token_is_renewed_once():
    api, session = client([TOKEN, Response(401, {}), TOKEN_2, PAGE])
    api.list_products(1, 1)
    assert session.calls[-1][2]["headers"]["Authorization"] == "Bearer tok-2"


def test_rate_limit_waits_for_retry_after():
    sleeps = []
    api, _ = client([TOKEN, Response(429, {}, {"Retry-After": "40"}), PAGE], sleeps=sleeps)
    api.list_products(1, 1)
    assert sleeps == [40.0]


def test_long_rate_limit_ends_the_pass_instead_of_waiting():
    api, _ = client([TOKEN, Response(429, {}, {"Retry-After": "7200"})])
    with pytest.raises(AuchanUnavailable) as exc:
        api.list_products(1, 1)
    assert exc.value.retry_after == 7200


def test_transient_failures_are_retried_then_reported():
    failures = [requests.ConnectionError("reset"), Response(502), Response(503), Response(500)]
    api, _ = client([TOKEN, *failures], max_attempts=4)
    with pytest.raises(AuchanUnavailable):
        api.list_products(1, 1)


def test_unexpected_status_is_a_contract_error_without_retry():
    api, session = client([TOKEN, Response(400, {}, text="items_per_page_is_too_large")])
    with pytest.raises(AuchanContractError):
        api.list_products(1, 1)
    assert len(session.calls) == 2


@pytest.mark.parametrize("body", [{"items": []}, {"results": [], "pageCount": "x"}, ValueError("not json")])
def test_malformed_list_is_a_contract_error(body):
    api, _ = client([TOKEN, Response(200, body)])
    with pytest.raises(AuchanContractError):
        api.list_products(1, 1)


def test_token_without_access_token_is_a_contract_error():
    api, _ = client([Response(200, {"token_type": "Bearer"})])
    with pytest.raises(AuchanContractError):
        api.category_tree()


def test_requests_are_paced():
    sleeps = []
    # token at 0.0; first page 10 s later (no wait); second page 0.2 s after that.
    ticks = iter([0.0, 10.0, 10.0, 10.2, 11.0])
    session = Session([TOKEN, PAGE, PAGE])
    api = AuchanClient(session=session, min_interval=1.0, sleep=sleeps.append, clock=lambda: next(ticks))
    api.list_products(1, 1)
    api.list_products(1, 2)
    assert sleeps == [pytest.approx(0.8)]
