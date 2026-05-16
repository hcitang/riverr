import asyncio

import pytest

from riverr.core.extract import (
    ensure_extracted,
    extract_html,
    extract_url_for_item,
    is_hn,
    is_stub,
)
from riverr.core.storage import Item


def _stub_item(**kw):
    base = dict(
        id=1, feed_id=1, guid="g", title="t", author=None, link=None,
        comments_link=None, body=None, extracted_body=None,
        published_at=None, fetched_at=0.0, read=False,
    )
    base.update(kw)
    return Item(**base)


def test_is_stub_short():
    it = _stub_item(body="<p>short</p>")
    assert is_stub(it)


def test_is_stub_long():
    body = "<p>" + ("real content " * 100) + "</p>"
    it = _stub_item(body=body)
    assert not is_stub(it)


def test_hn_routing_uses_article_link():
    it = _stub_item(
        link="https://example.com/article",
        comments_link="https://news.ycombinator.com/item?id=1",
    )
    url, comments = extract_url_for_item(it)
    assert url == "https://example.com/article"
    assert comments == "https://news.ycombinator.com/item?id=1"


def test_is_hn():
    assert is_hn("https://news.ycombinator.com/item?id=1")
    assert is_hn("https://hnrss.org/frontpage")
    assert not is_hn("https://example.com/")


def test_extract_preserves_images_and_links():
    html = """
    <html><body>
      <article>
        <h1>Test Article With Links and Images</h1>
        <p>Here is a paragraph that mentions
        <a href="https://example.com/destination">an external link</a>
        as part of the prose. The paragraph keeps going with enough content
        to satisfy any minimum-length heuristics that trafilatura might
        apply when deciding what to extract. We add more sentences so the
        body is well over five hundred characters in length and so the
        extractor recognises this as a real article body rather than
        a navigation or boilerplate fragment. Lorem ipsum dolor sit amet,
        consectetur adipiscing elit, sed do eiusmod tempor incididunt ut
        labore et dolore magna aliqua. Ut enim ad minim veniam, quis
        nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo
        consequat.</p>
        <p>Below is an embedded image:</p>
        <p><img src="https://example.com/pic.png" alt="a picture"/></p>
        <p>And a closing paragraph with another
        <a href="https://example.com/two">second link</a> for good
        measure. We keep adding text so that this paragraph also has
        enough length to be preserved by trafilatura's recall-favoured
        extraction mode.</p>
      </article>
    </body></html>
    """
    from riverr.core.extract import extract_html
    result = extract_html(html, url="https://example.com/")
    assert result is not None
    out, fmt, source = result
    assert fmt in ("markdown", "html")
    assert source in ("trafilatura", "readability")
    assert "pic.png" in out
    assert "example.com/destination" in out


def test_trafilatura_extracts_cbc(fixtures_dir):
    html = (fixtures_dir / "cbc_article.html").read_text()
    result = extract_html(html, url="https://www.cbc.ca/x")
    assert result is not None
    out, fmt, source = result
    assert len(out) > 500
    assert "budget" in out.lower()
    assert fmt in ("markdown", "html")
    assert source in ("trafilatura", "readability")


def test_is_stub_markdown_long_but_rss_with_link():
    """A markdownified RSS body can easily exceed 500 chars yet still be
    just a stub + 'read more' link. body_source='rss' + a link should
    trip is_stub regardless of length (up to 1200 chars of prose)."""
    body = (
        "The federal government tabled its 2026 budget on Monday "
        "afternoon, with new spending on housing and clean energy. "
        * 6  # ~700 chars of prose, no links
    ) + "\n\n[Read more](https://www.cbc.ca/news/politics/budget)"
    it = _stub_item(
        body=body,
        body_format="markdown",
        body_source="rss",
        link="https://www.cbc.ca/news/politics/budget",
    )
    assert is_stub(it)


def test_is_stub_markdown_full_article():
    """A real full-content markdown body (e.g. an extracted blog post or
    a feed that ships the whole article) must NOT be flagged as stub."""
    paragraph = (
        "This is a real paragraph of article prose that contains enough "
        "actual content to count as full body text and not a stub. "
    )
    body = ("\n\n".join([paragraph * 4] * 6))  # >>1200 chars of prose
    it = _stub_item(
        body=body,
        body_format="markdown",
        body_source="trafilatura",
        link="https://example.com/post",
    )
    assert not is_stub(it)


def test_is_stub_trailing_link_pattern():
    body = (
        "A short blurb about the news event. "
        "[Read the full story](https://example.com/story)"
    )
    it = _stub_item(
        body=body, body_format="markdown", body_source="rss",
        link="https://example.com/story",
    )
    assert is_stub(it)


def test_ensure_extracted_flips_source(seeded_storage, mock_transport):
    """Live storage path: upsert a stub-style markdown item, run
    ensure_extracted, and confirm body_source flips to extracted."""
    feeds = seeded_storage.list_feeds()
    cbc = next(f for f in feeds if "CBC" in f.title)
    items = seeded_storage.items_for_feed(cbc.id)
    target = next(i for i in items if "budget" in i.title.lower())
    assert target.body_source == "rss"
    assert target.body_format == "markdown"
    assert is_stub(target)
    result = asyncio.run(
        ensure_extracted(target, seeded_storage, transport=mock_transport)
    )
    assert result.body_source in ("trafilatura", "readability")
    assert result.body_format == "markdown"


def test_ensure_extracted_caches(seeded_storage, mock_transport):
    feeds = seeded_storage.list_feeds()
    cbc = next(f for f in feeds if "CBC" in f.title)
    items = seeded_storage.items_for_feed(cbc.id)
    target = next(i for i in items if "budget" in i.title.lower())
    assert is_stub(target)
    result = asyncio.run(ensure_extracted(target, seeded_storage, transport=mock_transport))
    assert result.extracted_body
    assert len(result.extracted_body) > 500
    # cached - second call should not re-fetch (set extracted_body present)
    again = seeded_storage.get_item(target.id)
    assert again.extracted_body
