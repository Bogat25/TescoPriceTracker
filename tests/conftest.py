import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "real_insight_rebuild: keep the real stores.insights.rebuild_store")
    config.addinivalue_line("markers", "real_alerts_feed: keep the real stores.alerts_feed.notify")


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
