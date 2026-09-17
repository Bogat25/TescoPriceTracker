"""Outgoing request pacing: a floor between requests that widens after a 429."""

from types import SimpleNamespace

import pytest

from scraper import scraper


class Clock:
    """Monotonic time the test controls; sleeping just advances it."""

    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(scraper.time, "monotonic", fake.time)
    monkeypatch.setattr(scraper.time, "sleep", fake.sleep)
    return fake


def pacer(minimum=0.25, maximum=8.0, recovery_after=3):
    return scraper.RequestPacer(minimum=minimum, maximum=maximum, recovery_after=recovery_after)


def test_requests_are_spaced_by_the_interval(clock):
    p = pacer()
    assert p.wait() == 0.0          # first request goes immediately
    assert p.wait() == pytest.approx(0.25)
    assert p.wait() == pytest.approx(0.25)


def test_a_slow_caller_is_not_delayed(clock):
    p = pacer()
    p.wait()
    clock.now += 5  # the caller took longer than the interval on its own
    assert p.wait() == 0.0


def test_a_rate_limit_doubles_the_gap_up_to_the_ceiling():
    p = pacer(minimum=0.25, maximum=1.0)
    assert p.on_rate_limited() == pytest.approx(0.5)
    assert p.on_rate_limited() == pytest.approx(1.0)
    assert p.on_rate_limited() is None      # already at the ceiling
    assert p.interval == pytest.approx(1.0)


def test_successes_bring_the_pace_back_to_the_floor():
    p = pacer(recovery_after=3)
    p.on_rate_limited()
    p.on_rate_limited()                     # 1.0s
    assert [p.on_success() for _ in range(2)] == [None, None]
    assert p.on_success() == pytest.approx(0.5)
    # A new rate limit resets the streak, so recovery starts again.
    p.on_rate_limited()
    assert p.on_success() is None
    assert [p.on_success(), p.on_success()][-1] == pytest.approx(0.5)


def test_pace_never_drops_below_the_floor():
    p = pacer(recovery_after=1)
    p.on_rate_limited()
    for _ in range(10):
        p.on_success()
    assert p.interval == pytest.approx(0.25)
    assert p.on_success() is None           # nothing to report at the floor


def test_posting_paces_and_reacts_to_the_response(monkeypatch, clock):
    events = []
    p = pacer()
    monkeypatch.setattr(scraper, "_pacer", p)
    monkeypatch.setattr(scraper, "_log_pace", lambda interval, reason: events.append((interval, reason)))
    responses = [SimpleNamespace(status_code=429), SimpleNamespace(status_code=200)]
    monkeypatch.setattr(scraper, "_get_http_session",
                        lambda: SimpleNamespace(post=lambda *a, **k: responses.pop(0)))

    scraper._post_tesco_request("https://example.test", json={})
    assert p.interval == pytest.approx(0.5)
    assert events[-1][1] == "slowed after a rate limit"

    scraper._post_tesco_request("https://example.test", json={})
    assert clock.slept  # the second request waited for its slot
