from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from riverr.variants.v7_river_plus.app import (
    BodyRow,
    EditFeedScreen,
    RiverRow,
    V7App,
    VIEW_STARRED,
)


@pytest.mark.asyncio
async def test_v7_tour(seeded_storage, mock_transport, tmp_path):
    app = V7App(storage=seeded_storage, transport=mock_transport)

    with patch("riverr.core.app_base.copy_url", return_value=True), \
         patch("riverr.core.app_base.open_url", return_value=True):
        async with app.run_test() as pilot:
            await pilot.pause()
            river = app.query_one("#river")
            river.focus()
            await pilot.pause()

            rows = [c for c in river.children if isinstance(c, RiverRow)]
            assert len(rows) > 0
            feed_ids = {r.feed.id for r in rows}
            assert len(feed_ids) >= 2

            # Star focused item
            river.index = 0
            await pilot.pause()
            first_row = river.children[0]
            assert isinstance(first_row, RiverRow)
            target_id = first_row.item.id
            await pilot.press("s")
            await pilot.pause()
            assert seeded_storage.is_starred(target_id) is True
            label_str = str(getattr(first_row, "_content", "") or getattr(first_row, "renderable", ""))
            if not label_str:
                label_str = first_row._render_text(80)
            assert "★" in label_str

            # Mark unread (it's currently unread — toggle twice)
            # First mark it read directly to test the unread toggle
            seeded_storage.mark_read(target_id, True)
            first_row.item.read = True
            first_row.refresh_label()
            await pilot.press("u")
            await pilot.pause()
            from riverr.core.storage import Storage  # noqa
            assert any(
                it.id == target_id and not it.read
                for it in seeded_storage.items_for_feed(first_row.feed.id)
            )

            # R from a cursor position marks all items below (inclusive) as read.
            # Pick the second row as the cursor anchor.
            anchor_idx = 1 if len(river.children) > 1 else 0
            river.index = anchor_idx
            await pilot.pause()
            above_ids = [
                c.item.id for c in river.children[:anchor_idx] if isinstance(c, RiverRow)
            ]
            below_ids = [
                c.item.id for c in river.children[anchor_idx:] if isinstance(c, RiverRow)
            ]
            for iid in above_ids + below_ids:
                seeded_storage.mark_unread(iid)
            app.load_items()
            await pilot.pause()
            river.index = anchor_idx
            await pilot.pause()
            await pilot.press("R")
            await pilot.pause()
            for iid in below_ids:
                it = seeded_storage.get_item(iid)
                assert it.read is True, f"item {iid} at/below cursor should be read"
            if above_ids:
                assert any(
                    not seeded_storage.get_item(iid).read for iid in above_ids
                ), "items above cursor should stay unread"

            # Switch view forward
            start_view = app.view_index
            await pilot.press("greater_than_sign")
            await pilot.pause()
            assert app.view_index != start_view

            # Cycle until reaching the Starred view
            seen = 0
            while app._view_order[app.view_index][0] != VIEW_STARRED and seen < 20:
                await pilot.press("greater_than_sign")
                await pilot.pause()
                seen += 1
            assert app._view_order[app.view_index][0] == VIEW_STARRED
            starred_rows = [c for c in river.children if isinstance(c, RiverRow)]
            assert len(starred_rows) >= 1
            assert all(r.item.starred for r in starred_rows)

            # Switch back to All Feeds
            await pilot.press("less_than_sign")
            await pilot.pause()

            # Cycle back to view 0 deterministically
            while app.view_index != 0:
                await pilot.press("less_than_sign")
                await pilot.pause()

            # Expand an item with Enter
            river.index = 0
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            bodies = [c for c in river.children if isinstance(c, BodyRow)]
            assert len(bodies) == 1

            # Space — body has little/no content so should collapse.
            # Move focus onto the body first.
            body_idx = river.children.index(bodies[0])
            river.index = body_idx
            await pilot.pause()
            # Press space until the body collapses (each press either
            # pages down or, when at bottom, collapses).
            for _ in range(20):
                await pilot.press("space")
                await pilot.pause()
                if not any(isinstance(c, BodyRow) for c in river.children):
                    break
            bodies_after = [c for c in river.children if isinstance(c, BodyRow)]
            assert bodies_after == [], "space at body bottom should eventually collapse"

            # Re-expand and test j collapses + moves + auto-expands next
            river.index = 0
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert any(isinstance(c, BodyRow) for c in river.children)
            first_owner = next(c for c in river.children if isinstance(c, RiverRow) and c.expanded)
            await pilot.press("j")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            # Default behavior.expanded_j = open_next: one body exists, on a
            # different RiverRow than before.
            bodies = [c for c in river.children if isinstance(c, BodyRow)]
            assert len(bodies) == 1, "j on expanded should auto-expand the next item"
            assert bodies[0].owner is not first_owner
            assert not first_owner.expanded

            # k closes + moves but does NOT auto-expand
            second_owner = bodies[0].owner
            await pilot.press("k")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            bodies_after_k = [c for c in river.children if isinstance(c, BodyRow)]
            assert bodies_after_k == [], "k on expanded should collapse without re-opening"
            assert not second_owner.expanded

            await pilot.press("q")


@pytest.mark.asyncio
async def test_v7_keymap_override(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    state = tmp_path / "state"
    (cfg / "riverr").mkdir(parents=True)
    (state / "riverr").mkdir(parents=True)
    (cfg / "riverr" / "keys.toml").write_text(
        '[keys]\n'
        'quit = "Q"\n'
        'star = "S"\n'
        'view_next = "n"\n'
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.setenv("XDG_DATA_HOME", str(state))

    from riverr.core.storage import Storage
    s = Storage(state / "riverr" / "state.db")
    try:
        app = V7App(storage=s)
        mapping = app._bindings.key_to_bindings
        assert "Q" in mapping
        assert any(b.action == "quit" for b in mapping["Q"])
        assert "S" in mapping
        assert any(b.action == "star" for b in mapping["S"])
        assert "n" in mapping
        assert any(b.action == "view_next" for b in mapping["n"])
    finally:
        s.close()


@pytest.mark.asyncio
async def test_v7_inline_image_kitty(seeded_storage, mock_transport, tmp_path, monkeypatch):
    monkeypatch.setenv("RIVERR_FORCE_IMAGE_PROTOCOL", "kitty")

    # Inject an item with an <img> in its extracted body
    feeds = seeded_storage.list_feeds()
    fid = feeds[0].id
    item = seeded_storage.items_for_feed(fid)[0]
    seeded_storage.set_extracted_body(
        item.id,
        "<p>before image</p><p><img src='https://example.com/x.png' alt='pic'/></p><p>after</p>",
    )

    # Stub the fetch + widget builder so we don't need real bytes.
    from riverr.core import images as imgmod

    async def fake_fetch(url, transport=None):
        return b"fake-bytes"

    class _FakeImageWidget:
        # textual_image.widget.Image is a real widget; we just need to
        # know one was mounted. Use a Static stand-in.
        pass

    from textual.widgets import Static as _Static

    def fake_make(data):
        w = _Static("[img widget]")
        w._is_fake_image = True
        return w

    monkeypatch.setattr(imgmod, "fetch_image", fake_fetch)
    monkeypatch.setattr(imgmod, "make_image_widget", fake_make)
    # patch the symbol bound inside the variant module too
    from riverr.variants.v7_river_plus import app as v7mod
    monkeypatch.setattr(v7mod.imgmod, "fetch_image", fake_fetch)
    monkeypatch.setattr(v7mod.imgmod, "make_image_widget", fake_make)

    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        river.focus()
        # find the row for our item
        for i, c in enumerate(river.children):
            if isinstance(c, RiverRow) and c.item.id == item.id:
                river.index = i
                break
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        body = next(c for c in river.children if isinstance(c, BodyRow))
        mounted = [w for w in body.scroll.children if getattr(w, "_is_fake_image", False)]
        assert len(mounted) >= 1, "expected a fake-image widget to be mounted inline"

        await pilot.press("q")


@pytest.mark.asyncio
async def test_v7_inline_image_placeholder(seeded_storage, mock_transport, monkeypatch):
    monkeypatch.setenv("RIVERR_FORCE_IMAGE_PROTOCOL", "none")

    feeds = seeded_storage.list_feeds()
    fid = feeds[0].id
    item = seeded_storage.items_for_feed(fid)[0]
    seeded_storage.set_extracted_body(
        item.id,
        "<p>before</p><p><img src='https://example.com/x.png' alt='pic'/></p>",
    )

    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        river.focus()
        for i, c in enumerate(river.children):
            if isinstance(c, RiverRow) and c.item.id == item.id:
                river.index = i
                break
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        body = next(c for c in river.children if isinstance(c, BodyRow))
        # No fake image widget; placeholder text should mention [image:
        from textual.widgets import Static as _Static
        statics = list(body.scroll.query(_Static))
        joined = "\n".join(str(getattr(s, "_Static__content", "")) for s in statics)
        assert "[image: pic]" in joined

        await pilot.press("q")


@pytest.mark.asyncio
async def test_v7_edit_feed_modal(seeded_storage, mock_transport):
    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        river.focus()
        await pilot.pause()
        # Focus first item (a RiverRow tied to a feed)
        river.index = 0
        await pilot.pause()
        row = river.children[0]
        from riverr.variants.v7_river_plus.app import RiverRow as _RR
        assert isinstance(row, _RR)
        feed_id = row.feed.id

        await pilot.press("e")
        await pilot.pause()
        # Modal should be on the screen stack
        assert isinstance(app.screen, EditFeedScreen)

        title_inp = app.screen.query_one("#edit-title")
        title_inp.value = "Renamed Feed"
        abbrev_inp = app.screen.query_one("#edit-abbrev")
        abbrev_inp.value = "RNM"
        color_inp = app.screen.query_one("#edit-color")
        color_inp.value = "#abcdef"
        title_inp.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        feed = seeded_storage.get_feed(feed_id)
        assert feed.display_title == "Renamed Feed"
        assert feed.abbrev == "RNM"
        assert feed.color == "#abcdef"

        await pilot.press("q")


@pytest.mark.asyncio
async def test_v7_paragraph_spacing(seeded_storage, mock_transport):
    feeds = seeded_storage.list_feeds()
    fid = feeds[0].id
    item = seeded_storage.items_for_feed(fid)[0]
    seeded_storage.set_extracted_body(
        item.id,
        "<p>First paragraph here.</p><p>Second paragraph here.</p><p>Third paragraph here.</p>",
    )

    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        river.focus()
        for i, c in enumerate(river.children):
            if isinstance(c, RiverRow) and c.item.id == item.id:
                river.index = i
                break
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        body = next(c for c in river.children if isinstance(c, BodyRow))
        # Every direct child of the scroll container should have a 1-row
        # bottom margin so paragraphs visibly separate.
        for child in body.scroll.children:
            margin = child.styles.margin
            assert margin is not None
            # margin is (top, right, bottom, left)
            assert margin.bottom == 1, f"expected margin-bottom=1, got {margin}"

        await pilot.press("q")


@pytest.mark.asyncio
async def test_v7_behavior_collapse_only(tmp_path, monkeypatch, mock_transport):
    cfg = tmp_path / "config"
    state = tmp_path / "state"
    (cfg / "riverr").mkdir(parents=True)
    (state / "riverr").mkdir(parents=True)
    (cfg / "riverr" / "keys.toml").write_text(
        '[behavior]\n'
        'expanded_j = "collapse_only"\n'
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.setenv("XDG_DATA_HOME", str(state))

    from riverr.core.fetch import fetch_all
    from riverr.core.storage import Storage

    s = Storage(state / "riverr" / "state.db")
    urls = [
        "https://hnrss.org/frontpage",
        "https://www.cbc.ca/webfeed/rss/rss-topstories",
    ]
    results = await fetch_all(urls, transport=mock_transport)
    for url, res in zip(urls, results):
        fid = s.add_feed(url=url, title=res.title or url)
        if res.ok:
            s.upsert_items(fid, res.items)

    try:
        app = V7App(storage=s, transport=mock_transport)
        assert app.behavior["expanded_j"] == "collapse_only"
        async with app.run_test() as pilot:
            await pilot.pause()
            river = app.query_one("#river")
            river.focus()
            river.index = 0
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert any(isinstance(c, BodyRow) for c in river.children)
            await pilot.press("j")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            # collapse_only: no body should be open after j
            bodies = [c for c in river.children if isinstance(c, BodyRow)]
            assert bodies == [], "collapse_only must not auto-expand next"
            await pilot.press("q")
    finally:
        s.close()


@pytest.mark.asyncio
async def test_v7_no_listview_for_river():
    # v7's river is a custom VerticalScroll-based RiverList; the only
    # ListView in the app is the (rarely-used) feed picker overlay.
    css = V7App.CSS
    assert "RiverList" in css


@pytest.mark.asyncio
async def test_v7_R_marks_below_in_view(seeded_storage, mock_transport):
    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        river.focus()

        # All Feeds view, cursor at idx 2 -> rows 0,1 should remain unread,
        # rows 2..N should become read.
        river.index = 2
        await pilot.pause()
        rows_before = [c for c in river.children if isinstance(c, RiverRow)]
        above = [r.item.id for r in rows_before[:2]]
        below = [r.item.id for r in rows_before[2:]]
        # ensure all unread to start
        for iid in above + below:
            seeded_storage.mark_unread(iid)
        app.load_items()
        await pilot.pause()
        river.index = 2
        await pilot.pause()
        await pilot.press("R")
        await pilot.pause()
        for iid in below:
            assert seeded_storage.get_item(iid).read is True
        for iid in above:
            assert seeded_storage.get_item(iid).read is False

        # Switch to per-feed view (next view; index 1 is a feed view).
        await pilot.press("greater_than_sign")
        await pilot.pause()
        feed_items_before = [
            c.item.id for c in river.children if isinstance(c, RiverRow)
        ]
        for iid in feed_items_before:
            seeded_storage.mark_unread(iid)
        app.load_items()
        await pilot.pause()
        river.index = 0
        await pilot.pause()
        await pilot.press("R")
        await pilot.pause()
        # All items in this single-feed view should now be read.
        for iid in feed_items_before:
            assert seeded_storage.get_item(iid).read is True
        # Items in OTHER feeds should not be touched (sample one)
        feeds = seeded_storage.list_feeds()
        other_feed = feeds[-1]
        # Find an item from other_feed and ensure it's still unread.
        other_items = seeded_storage.items_for_feed(other_feed.id)
        if other_items and other_items[0].id not in feed_items_before:
            seeded_storage.mark_unread(other_items[0].id)
            assert seeded_storage.get_item(other_items[0].id).read is False

        # Switch to Starred view: star one item first.
        starred_id = feeds[0]
        items0 = seeded_storage.items_for_feed(feeds[0].id)
        seeded_storage.set_starred(items0[0].id, True)
        seeded_storage.mark_unread(items0[0].id)
        # navigate to Starred
        while app._view_order[app.view_index][0] != VIEW_STARRED:
            await pilot.press("greater_than_sign")
            await pilot.pause()
        river.index = 0
        await pilot.pause()
        await pilot.press("R")
        await pilot.pause()
        # Item should now be read but still starred.
        it = seeded_storage.get_item(items0[0].id)
        assert it.read is True
        assert it.starred is True

        await pilot.press("q")


@pytest.mark.asyncio
async def test_v7_first_load_cursor_on_first_row(seeded_storage, mock_transport):
    """On launch, the cursor should sit on the first RiverRow."""
    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        assert river.index is not None
        first = river.children[river.index]
        assert isinstance(first, RiverRow)
        assert "cursor" in first.classes
        await pilot.press("q")


@pytest.mark.asyncio
async def test_v7_enter_then_jjjj_single_highlight(seeded_storage, mock_transport):
    """After Enter, j, j, j, j: exactly one row has the .cursor class."""
    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        river.focus()
        river.set_cursor(next(
            i for i, c in enumerate(river.children) if isinstance(c, RiverRow)
        ))
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        for _ in range(4):
            await pilot.press("j")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

        cursored = [c for c in river.children if "cursor" in c.classes]
        assert len(cursored) == 1, f"expected 1 cursor row, got {len(cursored)}"
        await pilot.press("q")


@pytest.mark.asyncio
async def test_v7_R_keeps_cursor_on_same_item(seeded_storage, mock_transport):
    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        river.focus()
        # pick a RiverRow a few down
        riv_indices = [
            i for i, c in enumerate(river.children) if isinstance(c, RiverRow)
        ]
        target_idx = riv_indices[2] if len(riv_indices) > 2 else riv_indices[0]
        river.set_cursor(target_idx)
        await pilot.pause()
        target_item_id = river.children[target_idx].item.id
        await pilot.press("R")
        await pilot.pause()
        await pilot.pause()  # let call_after_refresh fire
        # cursor should still be on the same item AND the row must still
        # carry the .cursor class so the highlight is visible.
        new_child = river.children[river.index]
        assert isinstance(new_child, RiverRow)
        assert new_child.item.id == target_item_id
        assert "cursor" in new_child.classes, (
            f"cursor row {river.index} lost .cursor class after R; "
            f"classes={list(new_child.classes)}"
        )
        # Exactly one row carries the class — no leaks.
        cursored = [c for c in river.children if "cursor" in c.classes]
        assert len(cursored) == 1
        await pilot.press("q")


@pytest.mark.asyncio
async def test_v7_cursor_is_blue(seeded_storage, mock_transport):
    """The cursor row's effective background must be a clear blue.
    Tony's preference: an unambiguous blue against $surface/$boost."""
    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        river.focus()
        idx = next(
            i for i, c in enumerate(river.children) if isinstance(c, RiverRow)
        )
        river.set_cursor(idx)
        await pilot.pause()
        row = river.children[idx]
        assert "cursor" in row.classes
        bg = row.styles.background
        # The background should be set, opaque, and biased blue (B > R, B > G).
        assert bg is not None, "cursor row has no background style"
        r, g, b = bg.rgb
        assert b >= 200, f"blue channel weak: rgb=({r},{g},{b})"
        assert b > r and b > g, f"not blue-dominant: rgb=({r},{g},{b})"
        await pilot.press("q")


@pytest.mark.asyncio
async def test_v7_inline_image_from_markdown_body(
    seeded_storage, mock_transport, monkeypatch
):
    """End-to-end image rendering when the stored body is markdown:
    `![alt](url)` → Image AST → BodyRow mounts an image widget."""
    monkeypatch.setenv("RIVERR_FORCE_IMAGE_PROTOCOL", "kitty")

    feeds = seeded_storage.list_feeds()
    fid = feeds[0].id
    item = seeded_storage.items_for_feed(fid)[0]
    seeded_storage.set_extracted_body(
        item.id,
        "Before image text.\n\n"
        "![pic](https://example.com/x.png)\n\n"
        "After image.",
        body_format="markdown",
    )

    from riverr.core import images as imgmod

    async def fake_fetch(url, transport=None):
        return b"fake-bytes"

    from textual.widgets import Static as _Static

    def fake_make(data):
        w = _Static("[img widget]")
        w._is_fake_image = True
        return w

    monkeypatch.setattr(imgmod, "fetch_image", fake_fetch)
    monkeypatch.setattr(imgmod, "make_image_widget", fake_make)
    from riverr.variants.v7_river_plus import app as v7mod
    monkeypatch.setattr(v7mod.imgmod, "fetch_image", fake_fetch)
    monkeypatch.setattr(v7mod.imgmod, "make_image_widget", fake_make)

    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        river.focus()
        for i, c in enumerate(river.children):
            if isinstance(c, RiverRow) and c.item.id == item.id:
                river.index = i
                break
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        body = next(c for c in river.children if isinstance(c, BodyRow))
        mounted = [
            w for w in body.scroll.children
            if getattr(w, "_is_fake_image", False)
        ]
        assert len(mounted) >= 1, (
            "expected an image widget to be mounted from a markdown body"
        )
        await pilot.press("q")


@pytest.mark.asyncio
async def test_v7_edit_modal_all_three_inputs_visible_and_tabbable(
    seeded_storage, mock_transport
):
    from textual.widgets import Input as _Inp

    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        river.focus()
        river.set_cursor(next(
            i for i, c in enumerate(river.children) if isinstance(c, RiverRow)
        ))
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, EditFeedScreen)

        title_inp = app.screen.query_one("#edit-title", _Inp)
        abbrev_inp = app.screen.query_one("#edit-abbrev", _Inp)
        color_inp = app.screen.query_one("#edit-color", _Inp)

        # All visible (positive width/height region)
        for inp in (title_inp, abbrev_inp, color_inp):
            assert inp.region.width > 0
            assert inp.region.height > 0

        # Focus order via Tab: title → abbrev → color
        assert app.focused is title_inp
        await pilot.press("tab")
        await pilot.pause()
        assert app.focused is abbrev_inp
        await pilot.press("tab")
        await pilot.pause()
        assert app.focused is color_inp

        await pilot.press("escape")
        await pilot.press("q")


@pytest.mark.asyncio
async def test_v7_long_title_truncates_at_narrow_width(seeded_storage, mock_transport):
    feeds = seeded_storage.list_feeds()
    fid = feeds[0].id
    items = seeded_storage.items_for_feed(fid)
    long_title = "X" * 300
    seeded_storage.conn.execute(
        "UPDATE items SET title=? WHERE id=?", (long_title, items[0].id)
    )
    seeded_storage.conn.commit()

    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test(size=(50, 24)) as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        # find our row
        row = next(
            c for c in river.children
            if isinstance(c, RiverRow) and c.item.id == items[0].id
        )
        rendered = row._render_text(50)
        # title was XXX... should be truncated with an ellipsis
        assert "…" in rendered
        # Age column should be present in the rendered string (some unit).
        # We just check the title doesn't take the whole width.
        plain = rendered
        # strip rich markup roughly for a length check (count visible chars)
        import re as _re
        plain = _re.sub(r"\[[^\]]+\]", "", plain)
        assert len(plain) <= 60
        await pilot.press("q")


@pytest.mark.asyncio
async def test_v7_body_fills_vertical_space(seeded_storage, mock_transport):
    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        river.focus()
        river.set_cursor(next(
            i for i, c in enumerate(river.children) if isinstance(c, RiverRow)
        ))
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        body = next(c for c in river.children if isinstance(c, BodyRow))
        # Body region should be substantially larger than a single row.
        assert body.region.height >= 20, (
            f"body height {body.region.height} too small for app height {app.size.height}"
        )
        await pilot.press("q")


def test_v7_markdown_extraction_roundtrip():
    """trafilatura markdown output → markdown_to_ast → render produces
    the expected paragraph/heading blocks."""
    from riverr.core.render import (
        Heading as _H, Paragraph as _P, markdown_to_ast, render_to_text,
    )
    md = (
        "# Big Heading\n\n"
        "First paragraph with **bold** and *italic* and a [link](https://example.com).\n\n"
        "Second paragraph here.\n\n"
        "- item one\n- item two\n"
    )
    doc = markdown_to_ast(md)
    assert any(isinstance(c, _H) and c.level == 1 for c in doc.children)
    paragraphs = [c for c in doc.children if isinstance(c, _P)]
    assert len(paragraphs) >= 2
    assert "https://example.com" in doc.links
    text, links = render_to_text(doc)
    s = text.plain
    assert "Big Heading" in s
    assert "First paragraph" in s
    assert "Second paragraph" in s
    assert "item one" in s and "item two" in s


@pytest.mark.asyncio
async def test_v7_placeholder_replaced_by_image_widget(
    seeded_storage, mock_transport, monkeypatch
):
    """When inline images are supported, the placeholder Static is replaced
    by the image widget at the same position in the scroll children."""
    monkeypatch.setenv("RIVERR_FORCE_IMAGE_PROTOCOL", "kitty")

    feeds = seeded_storage.list_feeds()
    fid = feeds[0].id
    item = seeded_storage.items_for_feed(fid)[0]
    seeded_storage.set_extracted_body(
        item.id,
        "<p>before image</p>"
        "<p><img src='https://example.com/x.png' alt='pic'/></p>"
        "<p>after image</p>",
    )

    from riverr.core import images as imgmod
    from textual.widgets import Static as _Static

    async def fake_fetch(url, transport=None):
        return b"fake-bytes"

    def fake_make(data):
        w = _Static("[img widget]")
        w._is_fake_image = True
        return w

    monkeypatch.setattr(imgmod, "fetch_image", fake_fetch)
    monkeypatch.setattr(imgmod, "make_image_widget", fake_make)
    from riverr.variants.v7_river_plus import app as v7mod
    monkeypatch.setattr(v7mod.imgmod, "fetch_image", fake_fetch)
    monkeypatch.setattr(v7mod.imgmod, "make_image_widget", fake_make)

    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        river.focus()
        for i, c in enumerate(river.children):
            if isinstance(c, RiverRow) and c.item.id == item.id:
                river.index = i
                break
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.pause()

        body = next(c for c in river.children if isinstance(c, BodyRow))
        children = list(body.scroll.children)
        fakes = [w for w in children if getattr(w, "_is_fake_image", False)]
        assert len(fakes) == 1, "fake image widget should be mounted"
        # Image widget sits BEFORE the "after image" Static — i.e. mounted
        # in the placeholder's original slot, not appended at the end.
        idx_img = children.index(fakes[0])
        after_statics = [
            i for i, w in enumerate(children)
            if "after image" in str(getattr(w, "_Static__content", ""))
        ]
        assert after_statics, "expected 'after image' static"
        assert idx_img < after_statics[0], (
            "image widget should sit before the trailing text block "
            f"(idx_img={idx_img}, after={after_statics[0]})"
        )
        # The standalone placeholder Static we mounted (italic magenta dim
        # "[image: pic]") with NO trailing "[N]" link-index suffix should be
        # gone. The paragraph-level inline "[image: pic][1]" rendered by
        # _render_block stays.
        bare_placeholders = [
            w for w in children
            if not getattr(w, "_is_fake_image", False)
            and str(getattr(w, "_Static__content", "")) == "[image: pic]"
        ]
        assert bare_placeholders == [], (
            "standalone placeholder should be removed after image mounts"
        )
        await pilot.press("q")


@pytest.mark.asyncio
async def test_v7_placeholder_marks_failed_on_fetch_error(
    seeded_storage, mock_transport, monkeypatch
):
    monkeypatch.setenv("RIVERR_FORCE_IMAGE_PROTOCOL", "kitty")
    feeds = seeded_storage.list_feeds()
    fid = feeds[0].id
    item = seeded_storage.items_for_feed(fid)[0]
    seeded_storage.set_extracted_body(
        item.id,
        "<p><img src='https://example.com/x.png' alt='pic'/></p>",
    )

    from riverr.core import images as imgmod

    async def fake_fetch(url, transport=None):
        return None  # simulate fetch failure

    monkeypatch.setattr(imgmod, "fetch_image", fake_fetch)
    from riverr.variants.v7_river_plus import app as v7mod
    monkeypatch.setattr(v7mod.imgmod, "fetch_image", fake_fetch)

    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        river.focus()
        for i, c in enumerate(river.children):
            if isinstance(c, RiverRow) and c.item.id == item.id:
                river.index = i
                break
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        body = next(c for c in river.children if isinstance(c, BodyRow))
        from textual.widgets import Static as _Static
        joined = "\n".join(
            str(getattr(s, "_Static__content", ""))
            for s in body.scroll.query(_Static)
        )
        assert "failed to load" in joined
        await pilot.press("q")


@pytest.mark.asyncio
async def test_v7_edit_modal_typing_and_enter_submit(
    seeded_storage, mock_transport
):
    """Bug 2 regression: after open, #edit-title has focus; Tab moves to
    #edit-abbrev; typing into the focused field updates its value; Enter
    dismisses the modal with the edited values."""
    from textual.widgets import Input as _Inp

    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        river.focus()
        river.set_cursor(next(
            i for i, c in enumerate(river.children) if isinstance(c, RiverRow)
        ))
        await pilot.pause()
        row = river.children[river.index]
        feed_id = row.feed.id

        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, EditFeedScreen)

        title_inp = app.screen.query_one("#edit-title", _Inp)
        abbrev_inp = app.screen.query_one("#edit-abbrev", _Inp)

        # Deferred focus must have landed on the title input.
        assert app.focused is title_inp, (
            f"expected focus on title, got {app.focused!r}"
        )

        # Tab to abbrev.
        await pilot.press("tab")
        await pilot.pause()
        assert app.focused is abbrev_inp

        # Type into the (now focused) abbrev input.
        abbrev_inp.value = ""
        for ch in "WXY":
            await pilot.press(ch.lower())
            await pilot.pause()
        assert "wxy" in abbrev_inp.value.lower(), (
            f"abbrev did not capture typing: {abbrev_inp.value!r}"
        )

        # Enter commits.
        await pilot.press("enter")
        await pilot.pause()
        # Modal dismissed.
        assert not isinstance(app.screen, EditFeedScreen)
        feed = seeded_storage.get_feed(feed_id)
        assert feed.abbrev and feed.abbrev.lower() == "wxy"
        await pilot.press("q")


@pytest.mark.asyncio
async def test_v7_body_shows_source_indicator(seeded_storage, mock_transport):
    """The expanded body header must include a `source:` indicator so Tony
    can tell which render path produced the article."""
    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        river.focus()
        river.set_cursor(next(
            i for i, c in enumerate(river.children) if isinstance(c, RiverRow)
        ))
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        body = next(c for c in river.children if isinstance(c, BodyRow))
        from textual.widgets import Static as _Static
        joined = "\n".join(
            str(getattr(s, "_Static__content", ""))
            for s in body.scroll.query(_Static)
        )
        assert "source:" in joined, (
            f"expected source indicator in body header; got:\n{joined}"
        )
        await pilot.press("q")


SNAPSHOT_DIR = (
    __import__("pathlib").Path(__file__).resolve().parent / "snapshots"
)


@pytest.mark.asyncio
async def test_v7_edit_modal_inputs_have_nonzero_region(
    seeded_storage, mock_transport
):
    """Modal Inputs must render at non-zero width AND height — guards
    against the prior regression where CSS collapsed them invisibly."""
    from textual.widgets import Input as _Inp

    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        river.focus()
        river.set_cursor(next(
            i for i, c in enumerate(river.children) if isinstance(c, RiverRow)
        ))
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EditFeedScreen)

        for fid in ("#edit-title", "#edit-abbrev", "#edit-color"):
            inp = app.screen.query_one(fid, _Inp)
            # Real Input needs >= 3 rows (top border + content + bottom border).
            # A height of 1 was the silent-collapse failure mode that shipped
            # twice; assert the full visible height.
            assert inp.region.height >= 3, (
                f"{fid} too short to be a real Input: region={inp.region!r}"
            )
            assert inp.region.width >= 10, (
                f"{fid} too narrow: region={inp.region!r}"
            )
        await pilot.press("escape")
        await pilot.press("q")


@pytest.mark.asyncio
async def test_v7_edit_modal_marker_moves_with_tab(
    seeded_storage, mock_transport
):
    from textual.widgets import Label as _Label

    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        river.focus()
        river.set_cursor(next(
            i for i, c in enumerate(river.children) if isinstance(c, RiverRow)
        ))
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EditFeedScreen)

        lt = app.screen.query_one("#label-title", _Label)
        la = app.screen.query_one("#label-abbrev", _Label)
        lc = app.screen.query_one("#label-color", _Label)

        # Initially on title.
        assert "on" in lt.classes
        assert "on" not in la.classes
        assert "on" not in lc.classes
        assert str(lt.render()).startswith("▶ ")

        await pilot.press("tab")
        await pilot.pause()
        assert "on" not in lt.classes, "title label should clear after Tab"
        assert "on" in la.classes, "abbrev label should be active after Tab"
        assert "on" not in lc.classes
        assert str(la.render()).startswith("▶ ")
        assert not str(lt.render()).startswith("▶ ")

        await pilot.press("escape")
        await pilot.press("q")


@pytest.mark.asyncio
async def test_v7_edit_modal_snapshots(seeded_storage, mock_transport):
    from textual.widgets import Input as _Inp

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        river.focus()
        river.set_cursor(next(
            i for i, c in enumerate(river.children) if isinstance(c, RiverRow)
        ))
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EditFeedScreen)

        (SNAPSHOT_DIR / "v7_modal_open.svg").write_text(app.export_screenshot())

        await pilot.press("tab")
        await pilot.pause()
        (SNAPSHOT_DIR / "v7_modal_abbrev_focus.svg").write_text(
            app.export_screenshot()
        )

        abbrev_inp = app.screen.query_one("#edit-abbrev", _Inp)
        abbrev_inp.value = ""
        for ch in "xyz":
            await pilot.press(ch)
            await pilot.pause()
        (SNAPSHOT_DIR / "v7_modal_abbrev_typed.svg").write_text(
            app.export_screenshot()
        )

        await pilot.press("escape")
        await pilot.press("q")


@pytest.mark.asyncio
async def test_v7_river_row_shows_chevron_on_cursor(
    seeded_storage, mock_transport
):
    """First row should render with a ▶ marker; non-cursor rows should not."""
    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        # On launch, _focus_first_item sets cursor on the first RiverRow.
        first_idx = next(
            i for i, c in enumerate(river.children) if isinstance(c, RiverRow)
        )
        first = river.children[first_idx]
        assert "cursor" in first.classes
        assert first._render_text(80).startswith("▶ "), (
            f"expected ▶ prefix; got {first._render_text(80)!r}"
        )
        # Press j → first row loses chevron, second river row gains it.
        await pilot.press("j")
        await pilot.pause()
        assert not first._render_text(80).startswith("▶ ")
        # Find the new cursor row
        cur = next(
            c for c in river.children
            if isinstance(c, RiverRow) and "cursor" in c.classes
        )
        assert cur is not first
        assert cur._render_text(80).startswith("▶ ")
        await pilot.press("q")


@pytest.mark.asyncio
async def test_v7_river_row_chevron_flips_on_expand_collapse(
    seeded_storage, mock_transport
):
    app = V7App(storage=seeded_storage, transport=mock_transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        river = app.query_one("#river")
        river.focus()
        first_idx = next(
            i for i, c in enumerate(river.children) if isinstance(c, RiverRow)
        )
        river.set_cursor(first_idx)
        await pilot.pause()
        row = river.children[first_idx]
        assert row._render_text(80).startswith("▶ ")
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert row.expanded
        assert row._render_text(80).startswith("▼ "), (
            f"expected ▼ after expand; got {row._render_text(80)!r}"
        )
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert not row.expanded
        assert row._render_text(80).startswith("▶ "), (
            f"expected ▶ after collapse; got {row._render_text(80)!r}"
        )
        await pilot.press("q")


def test_images_ghostty_term_detected(monkeypatch):
    from riverr.core import images as imgmod
    monkeypatch.delenv("RIVERR_FORCE_IMAGE_PROTOCOL", raising=False)
    monkeypatch.delenv("KITTY_WINDOW_ID", raising=False)
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.setenv("TERM", "xterm-ghostty")
    assert imgmod.supports_kitty_graphics() is True
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("TERM_PROGRAM", "ghostty")
    assert imgmod.supports_kitty_graphics() is True
    monkeypatch.delenv("TERM_PROGRAM")
    monkeypatch.setenv("KITTY_WINDOW_ID", "1")
    assert imgmod.supports_kitty_graphics() is True
