from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx
import trafilatura

from .fetch import fetch_url_bytes
from .storage import Item, Storage


HN_HOSTS = {"news.ycombinator.com", "hnrss.org"}


_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^\)]+)\)")


def _strip_markdown(text: str) -> str:
    """Reduce a markdown body to roughly its prose content for length
    measurement: drop link URLs but keep link text, drop image syntax,
    drop heading/blockquote/list markers, collapse whitespace."""
    s = text
    # Images first (otherwise the alt text survives but src counts).
    s = re.sub(r"!\[[^\]]*\]\([^\)]*\)", " ", s)
    # Markdown links → keep the visible text only.
    s = _MD_LINK_RE.sub(lambda m: m.group(1), s)
    # Autolinks <http://...>
    s = re.sub(r"<https?://[^>]+>", " ", s)
    # HTML tags (if any survived markdownify).
    s = re.sub(r"<[^>]+>", " ", s)
    # Heading / blockquote / list markers at line start.
    s = re.sub(r"(?m)^\s{0,3}(#{1,6}\s+|>\s+|[-*+]\s+|\d+\.\s+)", "", s)
    # Inline emphasis / code markers.
    s = re.sub(r"[`*_~]+", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _ends_with_bare_link(body: str) -> bool:
    """Last non-blank line is just a single markdown link (the classic
    "Read more at …" stub pattern)."""
    lines = [ln for ln in (body or "").splitlines() if ln.strip()]
    if not lines:
        return False
    last = lines[-1].strip()
    m = _MD_LINK_RE.fullmatch(last)
    return m is not None


def is_stub(item: Item) -> bool:
    body = item.body or ""
    if not body:
        # No body but a link to follow → worth extracting.
        return bool(getattr(item, "link", None))
    fmt = (getattr(item, "body_format", "html") or "html").lower()
    source = (getattr(item, "body_source", "legacy") or "legacy").lower()
    link = getattr(item, "link", None)
    # Markdown-aware path: strip formatting before measuring length.
    if fmt == "markdown":
        prose = _strip_markdown(body)
        # RSS-sourced markdown with a link and not-much-prose → stub.
        if source == "rss" and link and len(prose) < 1200:
            return True
        # Classic "read more at <link>" trailing-link stub.
        if link and _ends_with_bare_link(body) and len(prose) < 1500:
            return True
        if len(prose) < 500:
            return True
        return False
    # Legacy HTML path: original heuristic preserved for cached html bodies.
    text = re.sub(r"<[^>]+>", " ", body).strip()
    if len(text) < 500:
        return True
    n_links = len(re.findall(r"https?://", body))
    if n_links and len(text) / max(n_links, 1) < 80:
        return True
    return False


def is_hn(url: str | None) -> bool:
    if not url:
        return False
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    return any(h in host for h in HN_HOSTS)


def extract_url_for_item(item: Item) -> tuple[str | None, str | None]:
    """Return (url_to_extract, comments_url). For HN, the item link IS the article."""
    if is_hn(item.link) or is_hn(item.comments_link):
        return item.link, item.comments_link or item.link
    return item.link, None


def _html_to_markdown(html: str) -> str | None:
    try:
        from markdownify import markdownify as md
    except Exception:
        return None
    try:
        out = md(html, heading_style="ATX", strip=["script", "style"])
        if not out:
            return None
        # Normalize: collapse 3+ blank lines to 2.
        out = re.sub(r"\n{3,}", "\n\n", out).strip()
        return out
    except Exception:
        return None


def _readability_fallback_markdown(html: str) -> str | None:
    try:
        from readability import Document as _RDoc
    except Exception:
        return None
    try:
        doc = _RDoc(html)
        summary = doc.summary(html_partial=True)
        if not summary:
            return None
        text = re.sub(r"<[^>]+>", "", summary).strip()
        if len(text) < 200:
            return None
        return _html_to_markdown(summary)
    except Exception:
        return None


def extract_html(html: str, url: str | None = None) -> tuple[str, str, str] | None:
    """Extract main content from `html`. Returns (body, format, source)
    where format is 'markdown' or 'html' and source is 'trafilatura' or
    'readability'. None on failure.
    """
    out: str | None = None
    try:
        out = trafilatura.extract(
            html, url=url,
            include_comments=False,
            include_tables=False,
            include_links=True,
            include_images=True,
            include_formatting=True,
            output_format="markdown",
            favor_recall=True,
        )
    except Exception:
        out = None
    if out:
        cleaned = re.sub(r"\n{3,}", "\n\n", out).strip()
        # Sanity: very short markdown — fall through to readability.
        if len(cleaned) >= 200:
            return (cleaned, "markdown", "trafilatura")
        out = cleaned
    fb = _readability_fallback_markdown(html)
    if fb:
        return (fb, "markdown", "readability")
    if out:
        return (out, "markdown", "trafilatura")
    return None


async def ensure_extracted(
    item: Item,
    storage: Storage,
    transport: httpx.BaseTransport | None = None,
) -> Item:
    if item.extracted_body:
        return item
    if not is_stub(item):
        return item
    url, comments = extract_url_for_item(item)
    if not url:
        return item
    try:
        status, body, _ = await fetch_url_bytes(url, transport=transport)
    except Exception:
        return item
    if status >= 400 or not body:
        return item
    try:
        html = body.decode("utf-8", errors="replace")
    except Exception:
        return item
    result = extract_html(html, url=url)
    if not result:
        return item
    extracted, fmt, source = result
    storage.set_extracted_body(item.id, extracted, body_format=fmt, body_source=source)
    refreshed = storage.get_item(item.id)
    return refreshed or item
