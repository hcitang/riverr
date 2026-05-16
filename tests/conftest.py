from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from riverr.core._fixtures import make_transport, route

FIXTURES = Path(__file__).parent / "fixtures"


def _route_for_feeds(request: httpx.Request) -> httpx.Response:
    return route(request, FIXTURES)


@pytest.fixture
def mock_transport() -> httpx.MockTransport:
    return make_transport(FIXTURES)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def tmp_storage(tmp_path):
    from riverr.core.storage import Storage
    s = Storage(tmp_path / "state.db")
    yield s
    s.close()


@pytest.fixture
def seeded_storage(tmp_path, mock_transport):
    """Storage seeded with fixtures, no network."""
    import asyncio
    from riverr.core.fetch import fetch_all
    from riverr.core.storage import Storage

    s = Storage(tmp_path / "state.db")
    urls = [
        "https://hnrss.org/frontpage",
        "https://www.cbc.ca/webfeed/rss/rss-topstories",
        "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml",
        "https://daringfireball.net/feeds/main",
    ]
    results = asyncio.run(fetch_all(urls, transport=mock_transport))
    for url, res in zip(urls, results):
        fid = s.add_feed(url=url, title=res.title or url, site_url=res.site_url)
        if res.ok:
            s.upsert_items(fid, res.items)
    yield s
    s.close()
