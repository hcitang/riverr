from __future__ import annotations

import time

import pytest

from riverr.core import retention
from riverr.core import settings as settings_mod
from riverr.core.config import get_paths


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point XDG dirs at tmp_path and reset settings migration latch."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    settings_mod._reset_migration_latch()
    get_paths()  # ensure dirs exist
    yield
    settings_mod._reset_migration_latch()


def _seed(storage, feed_id, n, start_ts=1_700_000_000.0):
    items = [
        {
            "guid": f"g{i}",
            "title": f"Item {i}",
            "body": f"body {i}",
            "link": f"https://example.com/{i}",
            "published_at": start_ts + i,  # higher = newer
        }
        for i in range(n)
    ]
    storage.upsert_items(feed_id, items)


def test_prune_feed_caps_to_max(tmp_storage):
    fid = tmp_storage.add_feed("https://e.com/rss", "Ex")
    _seed(tmp_storage, fid, 10)
    deleted = tmp_storage.prune_feed(fid, max_items=4)
    assert deleted == 6
    remaining = tmp_storage.items_for_feed(fid)
    assert len(remaining) == 4
    # Most recent kept (highest published_at).
    titles = {it.title for it in remaining}
    assert titles == {"Item 9", "Item 8", "Item 7", "Item 6"}


def test_prune_feed_noop_when_under_cap(tmp_storage):
    fid = tmp_storage.add_feed("https://e.com/rss", "Ex")
    _seed(tmp_storage, fid, 3)
    assert tmp_storage.prune_feed(fid, max_items=500) == 0
    assert len(tmp_storage.items_for_feed(fid)) == 3


def test_prune_feed_disabled_with_zero(tmp_storage):
    fid = tmp_storage.add_feed("https://e.com/rss", "Ex")
    _seed(tmp_storage, fid, 5)
    assert tmp_storage.prune_feed(fid, max_items=0) == 0
    assert len(tmp_storage.items_for_feed(fid)) == 5


def test_prune_feed_exempts_starred(tmp_storage):
    fid = tmp_storage.add_feed("https://e.com/rss", "Ex")
    _seed(tmp_storage, fid, 10)
    # Star the OLDEST item — it must survive even though it would
    # otherwise be the first to go.
    items = tmp_storage.items_for_feed(fid)  # sorted newest-first
    oldest = items[-1]
    tmp_storage.set_starred(oldest.id, True)

    deleted = tmp_storage.prune_feed(fid, max_items=4)
    # 10 total, 1 starred, cap=4 non-starred → delete 5 non-starred
    assert deleted == 5
    remaining = tmp_storage.items_for_feed(fid)
    remaining_ids = {it.id for it in remaining}
    assert oldest.id in remaining_ids
    assert len(remaining) == 5  # 4 newest non-starred + 1 starred


def test_prune_feed_isolates_other_feeds(tmp_storage):
    f1 = tmp_storage.add_feed("https://a.com/rss", "A")
    f2 = tmp_storage.add_feed("https://b.com/rss", "B")
    _seed(tmp_storage, f1, 5)
    _seed(tmp_storage, f2, 5)
    tmp_storage.prune_feed(f1, max_items=2)
    assert len(tmp_storage.items_for_feed(f1)) == 2
    assert len(tmp_storage.items_for_feed(f2)) == 5


def test_prune_feed_cascades_to_read_state(tmp_storage):
    fid = tmp_storage.add_feed("https://e.com/rss", "Ex")
    _seed(tmp_storage, fid, 5)
    items = tmp_storage.items_for_feed(fid)
    for it in items:
        tmp_storage.mark_read(it.id, True)
    tmp_storage.prune_feed(fid, max_items=2)
    # read_state rows for deleted items should be gone.
    rs_count = tmp_storage.conn.execute(
        "SELECT COUNT(*) AS c FROM read_state"
    ).fetchone()["c"]
    assert rs_count == 2


def test_db_size_bytes_positive(tmp_storage):
    fid = tmp_storage.add_feed("https://e.com/rss", "Ex")
    _seed(tmp_storage, fid, 5)
    assert tmp_storage.db_size_bytes() > 0


def test_vacuum_runs_without_error(tmp_storage):
    fid = tmp_storage.add_feed("https://e.com/rss", "Ex")
    _seed(tmp_storage, fid, 20)
    tmp_storage.prune_feed(fid, max_items=2)
    tmp_storage.vacuum()  # must not raise
    # writes still work after vacuum
    tmp_storage.upsert_items(fid, [
        {"guid": "new", "title": "post-vacuum", "body": "x", "link": "u",
         "published_at": time.time()},
    ])
    assert tmp_storage.unread_count(fid) >= 1


def test_optimize_fts_runs_without_error(tmp_storage):
    fid = tmp_storage.add_feed("https://e.com/rss", "Ex")
    _seed(tmp_storage, fid, 5)
    tmp_storage.optimize_fts()  # must not raise


def test_get_cap_default_and_override(isolated_config):
    assert retention.get_cap() == retention.DEFAULT_MAX_ITEMS_PER_FEED
    settings_mod.set_("retention.max_items_per_feed", 42)
    assert retention.get_cap() == 42
    settings_mod.set_("retention.max_items_per_feed", 0)
    assert retention.get_cap() == 0


def test_maybe_run_maintenance_rate_limits(tmp_storage, isolated_config):
    assert retention.maybe_run_maintenance(tmp_storage) is True
    # Second call within the interval should be a no-op.
    assert retention.maybe_run_maintenance(tmp_storage) is False
    # force=True overrides the rate limit.
    assert retention.maybe_run_maintenance(tmp_storage, force=True) is True


def test_human_size():
    assert retention.human_size(0) == "0B"
    assert retention.human_size(900) == "900B"
    assert retention.human_size(1024) == "1.0K"
    assert retention.human_size(150 * 1024) == "150K"
    assert retention.human_size(int(2.5 * 1024 * 1024)) == "2.5M"
    assert retention.human_size(int(1.3 * 1024 * 1024 * 1024)) == "1.3G"
