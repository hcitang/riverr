from __future__ import annotations

import asyncio
import calendar
import time
from dataclasses import dataclass
from typing import Optional, Sequence

import feedparser
import httpx


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; riverr/0.1)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
}


@dataclass
class FetchedFeed:
    url: str
    ok: bool
    status: int
    title: str
    site_url: str | None
    items: list[dict]
    error: str | None = None


def _parse_entries(data: bytes, source_url: str) -> tuple[str, str | None, list[dict]]:
    parsed = feedparser.parse(data)
    title = (parsed.feed.get("title") if parsed.feed else None) or source_url
    site_url = parsed.feed.get("link") if parsed.feed else None
    items: list[dict] = []
    for e in parsed.entries:
        guid = e.get("id") or e.get("guid") or e.get("link") or e.get("title")
        if not guid:
            continue
        published_at: Optional[float] = None
        for k in ("published_parsed", "updated_parsed"):
            t = e.get(k)
            if t:
                # feedparser returns struct_time in UTC. mktime() treats
                # it as local time, so use calendar.timegm() for UTC.
                published_at = calendar.timegm(t)
                break
        body = ""
        if e.get("content"):
            body = e["content"][0].get("value", "")
        elif e.get("summary"):
            body = e.get("summary", "")
        items.append({
            "guid": str(guid),
            "title": e.get("title", ""),
            "author": e.get("author"),
            "link": e.get("link"),
            "comments_link": e.get("comments"),
            "body": body,
            "published_at": published_at,
        })
    return title, site_url, items


def _looks_cloudflare_blocked(resp: httpx.Response) -> bool:
    if resp.status_code not in (403, 503):
        return False
    server = (resp.headers.get("server") or "").lower()
    if "cloudflare" in server:
        return True
    if any(k.startswith("cf-") or k == "cf-ray" for k in resp.headers.keys()):
        return True
    return False


async def _fetch_with_cloudscraper(url: str) -> tuple[int, bytes] | None:
    """Retry a Cloudflare-blocked URL via cloudscraper (sync, in a thread).
    Returns (status, content) or None on import/runtime failure."""
    try:
        import cloudscraper
    except ImportError:
        return None
    def _run() -> tuple[int, bytes] | None:
        try:
            s = cloudscraper.create_scraper()
            r = s.get(url, headers={"Accept": DEFAULT_HEADERS["Accept"]}, timeout=25)
            return (r.status_code, r.content)
        except Exception:
            return None
    return await asyncio.to_thread(_run)


async def fetch_one(client: httpx.AsyncClient, url: str) -> FetchedFeed:
    try:
        r = await client.get(url, headers=DEFAULT_HEADERS, follow_redirects=True, timeout=20.0)
        if r.status_code >= 400:
            if _looks_cloudflare_blocked(r):
                cs = await _fetch_with_cloudscraper(url)
                if cs is not None and cs[0] < 400 and cs[1]:
                    title, site_url, items = _parse_entries(cs[1], url)
                    return FetchedFeed(url=url, ok=True, status=cs[0], title=title,
                                       site_url=site_url, items=items)
            return FetchedFeed(url=url, ok=False, status=r.status_code, title=url,
                               site_url=None, items=[],
                               error=f"HTTP {r.status_code}" + (
                                   " (Cloudflare)" if _looks_cloudflare_blocked(r) else ""
                               ))
        title, site_url, items = _parse_entries(r.content, url)
        return FetchedFeed(url=url, ok=True, status=r.status_code, title=title,
                           site_url=site_url, items=items)
    except Exception as ex:
        return FetchedFeed(url=url, ok=False, status=0, title=url, site_url=None,
                           items=[], error=str(ex))


async def fetch_all(
    urls: Sequence[str],
    transport: httpx.BaseTransport | None = None,
    concurrency: int = 8,
) -> list[FetchedFeed]:
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(transport=transport) as client:
        async def _run(u: str) -> FetchedFeed:
            async with sem:
                return await fetch_one(client, u)
        return await asyncio.gather(*[_run(u) for u in urls])


async def fetch_url_bytes(
    url: str,
    transport: httpx.BaseTransport | None = None,
) -> tuple[int, bytes, str]:
    async with httpx.AsyncClient(transport=transport) as client:
        r = await client.get(url, headers=DEFAULT_HEADERS, follow_redirects=True, timeout=20.0)
        if r.status_code >= 400 and _looks_cloudflare_blocked(r) and transport is None:
            cs = await _fetch_with_cloudscraper(url)
            if cs is not None and cs[0] < 400 and cs[1]:
                return cs[0], cs[1], url
        return r.status_code, r.content, str(r.url)
