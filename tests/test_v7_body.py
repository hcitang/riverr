"""Unit tests for v7's BodyRow render path: duplicate-title skipping
and inter-paragraph spacing."""
from __future__ import annotations

import pytest
from textual.widgets import Static

from riverr.core.storage import Item
from riverr.variants.v7_river_plus.app import BodyRow, RiverRow, V7App


def _static_plain(s: Static) -> str:
    """Pull plain text out of a mounted Static. v7 always mounts
    rich.text.Text instances, which Static stores on `_Static__content`."""
    from rich.text import Text
    content = getattr(s, "_Static__content", None)
    if isinstance(content, Text):
        return content.plain
    return str(content or "")


def _item(title: str, body: str) -> Item:
    return Item(
        id=42, feed_id=1, guid="g", title=title, author=None,
        link="https://example.com/x", comments_link=None,
        body=body, extracted_body=body,
        published_at=None, fetched_at=0.0, read=False,
        body_format="markdown", body_source="trafilatura",
    )


@pytest.mark.asyncio
async def test_body_skips_duplicate_title_heading(seeded_storage, mock_transport):
    title = "Federal Budget 2026"
    body = f"# {title}\n\nFirst paragraph of the article.\n\nSecond paragraph."
    it = _item(title, body)

    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Build a fake owner RiverRow + BodyRow manually.
        feeds = seeded_storage.list_feeds()
        feed = feeds[0]
        owner = RiverRow(it, feed)
        body_row = BodyRow(it, owner, transport=mock_transport)
        await app.mount(body_row)
        await pilot.pause()
        body_row.render_body()
        await pilot.pause()

        statics = [c for c in body_row.scroll.children if isinstance(c, Static)]
        # First static = header (contains the title once).
        header_text = _static_plain(statics[0])
        assert title in header_text
        # No subsequent Static should be just the title (the markdown
        # H1 must have been dropped).
        for s in statics[1:]:
            plain = _static_plain(s).strip()
            assert plain != title, f"duplicate title leaked into body: {plain!r}"


@pytest.mark.asyncio
async def test_body_three_paragraphs_no_empty_statics(
    seeded_storage, mock_transport,
):
    body = (
        "Paragraph one with several words.\n\n"
        "Paragraph two with several words.\n\n"
        "Paragraph three with several words."
    )
    it = _item("Doc", body)

    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        feed = seeded_storage.list_feeds()[0]
        owner = RiverRow(it, feed)
        body_row = BodyRow(it, owner, transport=mock_transport)
        await app.mount(body_row)
        await pilot.pause()
        body_row.render_body()
        await pilot.pause()

        statics = [c for c in body_row.scroll.children if isinstance(c, Static)]
        body_statics = statics[1:]  # drop header
        # Each paragraph → one Static, with no empty whitespace Static.
        assert len(body_statics) == 3, (
            f"expected 3 paragraph statics, got {len(body_statics)}: "
            f"{[_static_plain(s) for s in body_statics]}"
        )
        for s in body_statics:
            plain = _static_plain(s)
            assert plain.strip(), f"empty body Static mounted: {plain!r}"
            # No trailing blank line baked into the Static — spacing
            # comes from the CSS margin-bottom rule.
            assert not plain.endswith("\n\n"), (
                f"Static carries trailing blank line: {plain!r}"
            )
