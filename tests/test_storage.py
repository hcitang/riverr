import time

import pytest


def test_add_and_list_feeds(tmp_storage):
    fid = tmp_storage.add_feed("https://example.com/rss", "Example", "https://example.com/")
    feeds = tmp_storage.list_feeds()
    assert len(feeds) == 1
    assert feeds[0].id == fid
    assert feeds[0].title == "Example"


def test_rename_feed(tmp_storage):
    fid = tmp_storage.add_feed("https://example.com/rss", "Example")
    tmp_storage.rename_feed(fid, "My Example")
    assert tmp_storage.get_feed(fid).name == "My Example"


def test_upsert_items_and_unread(tmp_storage):
    fid = tmp_storage.add_feed("https://example.com/rss", "Example")
    items = [
        {"guid": "1", "title": "First", "body": "hello world", "link": "https://e.com/1", "published_at": time.time()},
        {"guid": "2", "title": "Second", "body": "stuff", "link": "https://e.com/2", "published_at": time.time()},
    ]
    n = tmp_storage.upsert_items(fid, items)
    assert n == 2
    # idempotent
    assert tmp_storage.upsert_items(fid, items) == 0
    assert tmp_storage.unread_count(fid) == 2


def test_read_transitions(tmp_storage):
    fid = tmp_storage.add_feed("https://example.com/rss", "Example")
    tmp_storage.upsert_items(fid, [
        {"guid": "a", "title": "A", "body": "x", "link": "u"},
        {"guid": "b", "title": "B", "body": "y", "link": "u"},
    ])
    items = tmp_storage.items_for_feed(fid)
    tmp_storage.mark_read(items[0].id, True)
    assert tmp_storage.unread_count(fid) == 1
    tmp_storage.mark_feed_read(fid)
    assert tmp_storage.unread_count(fid) == 0


def test_new_since(tmp_storage):
    fid = tmp_storage.add_feed("https://example.com/rss", "Example")
    marker = time.time()
    time.sleep(0.01)
    tmp_storage.upsert_items(fid, [{"guid": "x", "title": "X", "body": "x", "link": "u"}])
    assert tmp_storage.new_since(marker) == 1
    assert tmp_storage.new_since(time.time() + 60) == 0


def test_starred_round_trip(tmp_storage):
    fid = tmp_storage.add_feed("https://example.com/rss", "Example")
    tmp_storage.upsert_items(fid, [
        {"guid": "1", "title": "A", "body": "x", "link": "u"},
        {"guid": "2", "title": "B", "body": "y", "link": "u"},
    ])
    items = tmp_storage.items_for_feed(fid)
    assert tmp_storage.is_starred(items[0].id) is False
    tmp_storage.set_starred(items[0].id, True)
    assert tmp_storage.is_starred(items[0].id) is True
    starred = tmp_storage.list_starred()
    assert len(starred) == 1
    assert starred[0].id == items[0].id
    assert starred[0].starred is True
    tmp_storage.set_starred(items[0].id, False)
    assert tmp_storage.list_starred() == []


def test_mark_unread(tmp_storage):
    fid = tmp_storage.add_feed("https://example.com/rss", "Example")
    tmp_storage.upsert_items(fid, [{"guid": "1", "title": "A", "body": "x", "link": "u"}])
    item = tmp_storage.items_for_feed(fid)[0]
    tmp_storage.mark_read(item.id, True)
    assert tmp_storage.unread_count(fid) == 0
    tmp_storage.mark_unread(item.id)
    assert tmp_storage.unread_count(fid) == 1


def test_mark_below_read(tmp_storage):
    fid = tmp_storage.add_feed("https://example.com/rss", "Example")
    tmp_storage.upsert_items(fid, [
        {"guid": "1", "title": "A", "body": "x", "link": "u"},
        {"guid": "2", "title": "B", "body": "y", "link": "u"},
    ])
    items = tmp_storage.items_for_feed(fid)
    n = tmp_storage.mark_below_read(items)
    assert n == 2
    assert tmp_storage.unread_count(fid) == 0


def test_set_abbrev(tmp_storage):
    fid = tmp_storage.add_feed("https://example.com/rss", "Example")
    assert tmp_storage.get_feed(fid).abbrev is None
    tmp_storage.set_abbrev(fid, "EXA")
    assert tmp_storage.get_feed(fid).abbrev == "EXA"
    tmp_storage.set_abbrev(fid, None)
    assert tmp_storage.get_feed(fid).abbrev is None


def test_set_color(tmp_storage):
    fid = tmp_storage.add_feed("https://example.com/rss", "Example")
    assert tmp_storage.get_feed(fid).color is None
    assert tmp_storage.get_color(fid) is None
    tmp_storage.set_color(fid, "#abcdef")
    assert tmp_storage.get_color(fid) == "#abcdef"
    assert tmp_storage.get_feed(fid).color == "#abcdef"
    tmp_storage.set_abbrev(fid, "EXA")
    feed = tmp_storage.get_feed(fid)
    assert feed.abbrev == "EXA" and feed.color == "#abcdef"
    tmp_storage.set_color(fid, None)
    assert tmp_storage.get_color(fid) is None


def test_previous_refresh_at(tmp_storage):
    fid = tmp_storage.add_feed("https://example.com/rss", "Example")
    assert tmp_storage.previous_refresh_at() is None
    tmp_storage.log_fetch(fid, True, 0)
    assert tmp_storage.previous_refresh_at() is None  # only one tick
    time.sleep(1.1)
    tmp_storage.log_fetch(fid, True, 0)
    prev = tmp_storage.previous_refresh_at()
    assert prev is not None
    assert prev < time.time()


def test_fts(tmp_storage):
    fid = tmp_storage.add_feed("https://example.com/rss", "Example")
    tmp_storage.upsert_items(fid, [
        {"guid": "1", "title": "Apples are great", "body": "they are red", "link": "u"},
        {"guid": "2", "title": "Bananas split", "body": "yellow fruit", "link": "u"},
    ])
    hits = tmp_storage.search("apples")
    assert len(hits) == 1
    assert hits[0].title == "Apples are great"
    hits = tmp_storage.search("yellow")
    assert len(hits) == 1


def test_upsert_stores_markdown(tmp_storage):
    fid = tmp_storage.add_feed("https://example.com/rss", "Example")
    tmp_storage.upsert_items(fid, [
        {
            "guid": "a",
            "title": "T",
            "body": "<p>Hello <strong>world</strong>.</p><p>Second.</p>",
            "link": "https://example.com/a",
        },
    ])
    items = tmp_storage.items_for_feed(fid)
    assert len(items) == 1
    assert items[0].body_format == "markdown"
    body = items[0].body
    # Meaningful text preserved
    assert "Hello" in body and "world" in body and "Second" in body
    # Markdown emphasis preserved
    assert "**world**" in body


def test_upsert_plain_text_body_passthrough(tmp_storage):
    fid = tmp_storage.add_feed("https://example.com/rss", "Example")
    tmp_storage.upsert_items(fid, [
        {"guid": "1", "title": "T", "body": "plain text body", "link": "u"},
    ])
    items = tmp_storage.items_for_feed(fid)
    assert items[0].body == "plain text body"
    assert items[0].body_format == "markdown"


def test_upsert_sets_body_source_rss(tmp_storage):
    fid = tmp_storage.add_feed("https://example.com/rss", "Example")
    tmp_storage.upsert_items(fid, [
        {"guid": "a", "title": "T", "body": "<p>x</p>", "link": "u"},
    ])
    items = tmp_storage.items_for_feed(fid)
    assert items[0].body_source == "rss"


def test_set_extracted_body_records_source(tmp_storage):
    fid = tmp_storage.add_feed("https://example.com/rss", "Example")
    tmp_storage.upsert_items(fid, [
        {"guid": "a", "title": "T", "body": "<p>x</p>", "link": "u"},
    ])
    items = tmp_storage.items_for_feed(fid)
    tmp_storage.set_extracted_body(
        items[0].id, "extracted", body_format="markdown",
        body_source="trafilatura",
    )
    refreshed = tmp_storage.get_item(items[0].id)
    assert refreshed.body_source == "trafilatura"


def test_clear_extracted(tmp_storage):
    fid = tmp_storage.add_feed("https://example.com/rss", "Example")
    tmp_storage.upsert_items(fid, [
        {"guid": "1", "title": "A", "body": "<p>body</p>", "link": "u"},
        {"guid": "2", "title": "B", "body": "<p>body</p>", "link": "u"},
    ])
    items = tmp_storage.items_for_feed(fid)
    tmp_storage.set_extracted_body(items[0].id, "extracted A", body_format="markdown")
    tmp_storage.set_extracted_body(items[1].id, "extracted B", body_format="markdown")
    n = tmp_storage.clear_extracted()
    assert n == 2
    for it in tmp_storage.items_for_feed(fid):
        assert it.extracted_body is None


def test_clear_extracted_by_feed(tmp_storage):
    fid1 = tmp_storage.add_feed("https://a.example/rss", "A")
    fid2 = tmp_storage.add_feed("https://b.example/rss", "B")
    tmp_storage.upsert_items(fid1, [{"guid": "1", "title": "x", "body": "<p>b</p>", "link": "u"}])
    tmp_storage.upsert_items(fid2, [{"guid": "1", "title": "x", "body": "<p>b</p>", "link": "u"}])
    i1 = tmp_storage.items_for_feed(fid1)[0]
    i2 = tmp_storage.items_for_feed(fid2)[0]
    tmp_storage.set_extracted_body(i1.id, "ex1", body_format="markdown")
    tmp_storage.set_extracted_body(i2.id, "ex2", body_format="markdown")
    n = tmp_storage.clear_extracted(feed_filter=fid1)
    assert n == 1
    assert tmp_storage.get_item(i1.id).extracted_body is None
    assert tmp_storage.get_item(i2.id).extracted_body == "ex2"


def test_html_body_format_migrated_to_markdown_on_open(tmp_path):
    """Rows persisted with body_format='html' or 'legacy' should be converted
    to markdown the next time Storage is opened. Idempotent on subsequent
    opens."""
    import sqlite3
    import time

    from riverr.core.storage import Storage

    db_path = tmp_path / "state.db"
    # First open creates the schema (Storage __init__ runs migrations).
    s = Storage(db_path)
    fid = s.add_feed("https://example.com/rss", "Example")
    s.close()

    # Hand-write a row in the legacy HTML format the migration should catch.
    raw = sqlite3.connect(str(db_path))
    raw.execute(
        "INSERT INTO items (feed_id, guid, title, body, body_format, body_source, "
        "fetched_at) VALUES (?, ?, ?, ?, 'html', 'legacy', ?)",
        (fid, "legacy-1", "Legacy", "<p>Hello <b>world</b></p>", time.time()),
    )
    raw.execute(
        "INSERT INTO items (feed_id, guid, title, body, extracted_body, "
        "body_format, body_source, fetched_at) VALUES (?, ?, ?, ?, ?, 'legacy', 'legacy', ?)",
        (fid, "legacy-2", "Legacy 2", "<p>body</p>",
         "<h1>Title</h1><p>Extracted</p>", time.time()),
    )
    raw.commit()
    raw.close()

    # Re-open: migration runs.
    s2 = Storage(db_path)
    items = sorted(s2.items_for_feed(fid), key=lambda i: i.id)
    assert all(it.body_format == "markdown" for it in items)
    # markdownify converts <b> to ** and headings to #-prefixed lines.
    assert "**world**" in (items[0].body or "")
    assert "Extracted" in (items[1].extracted_body or "")
    assert "#" in (items[1].extracted_body or "")
    s2.close()

    # Idempotent: re-opening finds nothing to migrate (no errors, still markdown).
    s3 = Storage(db_path)
    items = sorted(s3.items_for_feed(fid), key=lambda i: i.id)
    assert all(it.body_format == "markdown" for it in items)
    s3.close()


def test_storage_import_paths():
    from riverr.core.models import Feed, Item  # noqa: F401
    from riverr.core.storage import Feed as Feed2, Item as Item2, Storage  # noqa: F401
    assert Feed is Feed2
    assert Item is Item2


def test_reset_items_all_no_fts_corruption(tmp_storage):
    """reset_items(feed_filter=None) must not corrupt the FTS index.
    Regression: manual DELETE FROM items_fts clashed with the items_ad
    trigger and produced 'database disk image is malformed' on read."""
    fid = tmp_storage.add_feed("https://example.com/rss", "Example")
    tmp_storage.upsert_items(fid, [
        {"guid": "a", "title": "Apples", "body": "red", "link": "u"},
        {"guid": "b", "title": "Bananas", "body": "yellow", "link": "u"},
    ])
    assert tmp_storage.reset_items() == 2
    # FTS table must still be usable after the wipe.
    assert tmp_storage.search("apples") == []
    # And we must be able to re-insert + re-search without errors.
    tmp_storage.upsert_items(fid, [
        {"guid": "c", "title": "Cherries", "body": "red", "link": "u"},
    ])
    hits = tmp_storage.search("cherries")
    assert len(hits) == 1


def test_remove_feed_no_fts_corruption(tmp_storage):
    """remove_feed had the same manual-FTS-delete bug as reset_items."""
    fid = tmp_storage.add_feed("https://example.com/rss", "Example")
    tmp_storage.upsert_items(fid, [
        {"guid": "a", "title": "Apples", "body": "red", "link": "u"},
    ])
    assert tmp_storage.remove_feed(fid) == 1
    # FTS index still queryable.
    assert tmp_storage.search("apples") == []
    # New feed, new items, search still works.
    fid2 = tmp_storage.add_feed("https://example.com/rss2", "Example 2")
    tmp_storage.upsert_items(fid2, [
        {"guid": "c", "title": "Cherries", "body": "red", "link": "u"},
    ])
    assert len(tmp_storage.search("cherries")) == 1
