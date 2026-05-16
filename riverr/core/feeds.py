from __future__ import annotations

import asyncio
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx

from .fetch import DEFAULT_HEADERS, fetch_one, fetch_url_bytes
from .storage import Storage


class _FeedLinkFinder(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.feeds: list[tuple[str, str]] = []  # (type, href)
        self.in_head = False

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self.in_head = True
        if tag == "link":
            a = dict(attrs)
            rel = (a.get("rel") or "").lower()
            t = (a.get("type") or "").lower()
            href = a.get("href")
            if href and "alternate" in rel and ("rss" in t or "atom" in t or "xml" in t):
                self.feeds.append((t, href))

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False


async def discover_feed_url(
    homepage_url: str,
    transport: httpx.BaseTransport | None = None,
) -> str | None:
    status, body, final_url = await fetch_url_bytes(homepage_url, transport=transport)
    if status >= 400:
        return None
    try:
        html = body.decode("utf-8", errors="replace")
    except Exception:
        return None
    finder = _FeedLinkFinder()
    try:
        finder.feed(html)
    except Exception:
        pass
    if not finder.feeds:
        # fallback: regex
        m = re.search(
            r'<link[^>]+rel=["\']alternate["\'][^>]+type=["\'](application/(?:rss|atom)\+xml)["\'][^>]+href=["\']([^"\']+)["\']',
            html, re.I,
        )
        if m:
            return urljoin(final_url, m.group(2))
        return None
    # prefer rss over atom
    finder.feeds.sort(key=lambda p: 0 if "rss" in p[0] else 1)
    return urljoin(final_url, finder.feeds[0][1])


async def add_by_url(
    url: str,
    storage: Storage,
    transport: httpx.BaseTransport | None = None,
) -> int:
    async with httpx.AsyncClient(transport=transport) as client:
        fetched = await fetch_one(client, url)
    if not fetched.ok:
        # try discovery if the URL looks like a homepage
        discovered = await discover_feed_url(url, transport=transport)
        if discovered:
            async with httpx.AsyncClient(transport=transport) as client:
                fetched = await fetch_one(client, discovered)
            if fetched.ok:
                url = discovered
    feed_id = storage.add_feed(url=url, title=fetched.title, site_url=fetched.site_url)
    if fetched.items:
        storage.upsert_items(feed_id, fetched.items)
    return feed_id


def add_by_url_sync(url: str, storage: Storage, transport: httpx.BaseTransport | None = None) -> int:
    return asyncio.run(add_by_url(url, storage, transport=transport))
