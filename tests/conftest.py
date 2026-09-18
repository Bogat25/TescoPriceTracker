import logging

import pytest

# The suite captures DEBUG so tests can assert on their own log records; these
# libraries would bury them.
NOISY_LOGGERS = ("pymongo", "httpx", "httpcore", "urllib3", "asyncio", "faker")


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: needs the live services CI starts")
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    config.addinivalue_line("markers", "real_insight_rebuild: keep the real stores.insights.rebuild_store")
    config.addinivalue_line("markers", "real_alerts_feed: keep the real stores.alerts_feed.notify")
    config.addinivalue_line("markers", "real_category_rebuild: keep the real stores.categories.rebuild_safely")


@pytest.fixture(autouse=True)
def _no_insight_rebuild(request, monkeypatch):
    """Scrape tests must not reach MongoDB through the statistics rebuild."""
    if request.node.get_closest_marker("real_insight_rebuild"):
        return
    from stores import insights

    monkeypatch.setattr(insights, "rebuild_store", lambda *_args, **_kwargs: True)


@pytest.fixture(autouse=True)
def _no_alert_trigger(request, monkeypatch):
    """Crawl tests must not reach MongoDB or the alert service when publishing."""
    if request.node.get_closest_marker("real_alerts_feed"):
        return
    from stores import alerts_feed

    monkeypatch.setattr(alerts_feed, "notify", lambda *_args, **_kwargs: True)


@pytest.fixture(autouse=True)
def _no_category_rebuild(request, monkeypatch):
    """Scrape tests must not reach MongoDB through the category mapping rebuild."""
    if request.node.get_closest_marker("real_category_rebuild"):
        return
    from stores import categories

    monkeypatch.setattr(categories, "rebuild_safely", lambda *_args, **_kwargs: True)
