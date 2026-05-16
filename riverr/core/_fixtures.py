"""Private fixture transport for offline smoke/test runs.

Routes the seed feed URLs and known article URLs to bundled fixture files.
Used by `riverr smoke` when RIVERR_FIXTURES is set and by the test
suite. Lives under core/ so tests aren't an import target for production code.
"""
from __future__ import annotations

from pathlib import Path

import httpx


FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures"


_MAPPING: dict[str, tuple[str, str]] = {
    "https://hnrss.org/frontpage": ("hnrss.xml", "application/rss+xml"),
    "https://www.cbc.ca/webfeed/rss/rss-topstories": ("cbc.xml", "application/rss+xml"),
    "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml": ("cna.xml", "application/rss+xml"),
    "https://daringfireball.net/feeds/main": ("df.xml", "application/atom+xml"),
    # article URLs
    "https://www.cbc.ca/news/politics/budget-2026-1.0000001": ("cbc_article.html", "text/html"),
    "https://www.channelnewsasia.com/singapore/housing-scheme-1000001": ("cna_article.html", "text/html"),
    "https://www.apple.com/newsroom/q2-2026": ("df_linked.html", "text/html"),
    "https://example.com/rust-port-scanner": ("hn_article.html", "text/html"),
}


def route(request: httpx.Request, fixtures_dir: Path | None = None) -> httpx.Response:
    base = fixtures_dir or FIXTURES_DIR
    url = str(request.url)
    pair = _MAPPING.get(url)
    if pair is None:
        return httpx.Response(404, content=b"not found")
    fname, ctype = pair
    data = (base / fname).read_bytes()
    return httpx.Response(200, content=data, headers={"content-type": ctype})


def make_transport(fixtures_dir: Path | None = None) -> httpx.MockTransport:
    return httpx.MockTransport(lambda req: route(req, fixtures_dir))
