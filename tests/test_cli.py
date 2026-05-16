"""CLI integration tests — no subprocess, just direct invocations."""
from __future__ import annotations

import pytest

from riverr.cli import main


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    state = tmp_path / "state"
    (cfg / "riverr").mkdir(parents=True)
    (state / "riverr").mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.setenv("XDG_DATA_HOME", str(state))
    return state / "riverr" / "state.db"


def _seed_one_extracted(db_path):
    from riverr.core.storage import Storage

    s = Storage(db_path)
    fid = s.add_feed("https://example.com/rss", "Example")
    s.upsert_items(fid, [
        {"guid": "1", "title": "A", "body": "<p>x</p>", "link": "u"},
    ])
    item = s.items_for_feed(fid)[0]
    s.set_extracted_body(item.id, "extracted text", body_format="markdown")
    s.close()
    return fid, item.id


def test_items_reset_soft_default(cli_env, capsys):
    """`riverr items reset` defaults to --soft (clears extracted bodies)."""
    from riverr.core.storage import Storage

    _, item_id = _seed_one_extracted(cli_env)

    rc = main(["items", "reset"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Cleared extracted bodies for 1 items" in out

    s2 = Storage(cli_env)
    try:
        item = s2.get_item(item_id)
        assert item is not None
        assert item.extracted_body is None
    finally:
        s2.close()


def test_items_reset_hard_with_feed_filter(cli_env, capsys):
    """`riverr items reset --hard --feed <id>` deletes only that feed's items."""
    from riverr.core.storage import Storage

    s = Storage(cli_env)
    fid1 = s.add_feed("https://a.example/rss", "A")
    fid2 = s.add_feed("https://b.example/rss", "B")
    s.upsert_items(fid1, [{"guid": "1", "title": "A", "body": "<p>x</p>", "link": "u"}])
    s.upsert_items(fid2, [{"guid": "1", "title": "B", "body": "<p>y</p>", "link": "u2"}])
    s.close()

    rc = main(["items", "reset", "--hard", "--feed", str(fid1)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Deleted 1 items" in out

    s2 = Storage(cli_env)
    try:
        assert len(s2.items_for_feed(fid1)) == 0
        assert len(s2.items_for_feed(fid2)) == 1
    finally:
        s2.close()


def test_items_reset_hard_filter_by_feed(cli_env, capsys):
    from riverr.core.storage import Storage

    s = Storage(cli_env)
    fid1 = s.add_feed("https://a.example/rss", "A")
    fid2 = s.add_feed("https://b.example/rss", "B")
    for fid in (fid1, fid2):
        s.upsert_items(fid, [{"guid": "1", "title": "x", "body": "<p>b</p>", "link": "u"}])
    s.close()

    rc = main(["items", "reset", "--hard", "--feed", str(fid1)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Deleted 1 items" in out

    s2 = Storage(cli_env)
    try:
        assert len(s2.items_for_feed(fid1)) == 0
        assert len(s2.items_for_feed(fid2)) == 1
    finally:
        s2.close()


def test_clear_cache_deprecated_still_works(cli_env, capsys):
    """Old `clear-cache` still dispatches but emits a deprecation note on stderr."""
    from riverr.core.storage import Storage

    _, item_id = _seed_one_extracted(cli_env)

    rc = main(["clear-cache"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Cleared extracted bodies for 1 items" in captured.out
    assert "deprecated" in captured.err
    assert "items reset --soft" in captured.err

    s2 = Storage(cli_env)
    try:
        assert s2.get_item(item_id).extracted_body is None
    finally:
        s2.close()


def test_clear_cache_deprecated_filter_by_feed(cli_env, capsys):
    from riverr.core.storage import Storage

    s = Storage(cli_env)
    fid1 = s.add_feed("https://a.example/rss", "A")
    fid2 = s.add_feed("https://b.example/rss", "B")
    for fid in (fid1, fid2):
        s.upsert_items(fid, [{"guid": "1", "title": "x", "body": "<p>b</p>", "link": "u"}])
        it = s.items_for_feed(fid)[0]
        s.set_extracted_body(it.id, "ex", body_format="markdown")
    s.close()

    rc = main(["clear-cache", "--feed", str(fid1)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "1 items" in out


def test_reset_items_deprecated_still_works(cli_env, capsys):
    from riverr.core.storage import Storage

    s = Storage(cli_env)
    fid1 = s.add_feed("https://a.example/rss", "A")
    fid2 = s.add_feed("https://b.example/rss", "B")
    s.upsert_items(fid1, [{"guid": "1", "title": "A", "body": "<p>x</p>", "link": "u"}])
    s.upsert_items(fid2, [{"guid": "1", "title": "B", "body": "<p>y</p>", "link": "u2"}])
    s.close()

    rc = main(["reset-items", "--feed", str(fid1)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Deleted 1 items" in captured.out
    assert "deprecated" in captured.err
    assert "items reset --hard" in captured.err

    s2 = Storage(cli_env)
    try:
        assert len(s2.items_for_feed(fid1)) == 0
        assert len(s2.items_for_feed(fid2)) == 1
    finally:
        s2.close()
