"""Phase 3: OPML as source of truth for subscriptions."""
from __future__ import annotations

from pathlib import Path

import pytest

from riverr.cli import main
from riverr.core import opml as opml_mod
from riverr.core.opml import OpmlEntry
from riverr.core.storage import Storage


def _write_seed(p: Path, entries: list[OpmlEntry]) -> None:
    opml_mod.write(entries, p)


def test_add_entry_roundtrip(tmp_path):
    p = tmp_path / "f.opml"
    _write_seed(p, [])
    assert opml_mod.add_entry(p, OpmlEntry(title="A", xml_url="http://a/rss")) is True
    assert opml_mod.add_entry(p, OpmlEntry(title="A", xml_url="http://a/rss")) is False
    entries = opml_mod.parse(p)
    assert [e.xml_url for e in entries] == ["http://a/rss"]


def test_remove_entry(tmp_path):
    p = tmp_path / "f.opml"
    _write_seed(p, [
        OpmlEntry(title="A", xml_url="http://a/rss"),
        OpmlEntry(title="B", xml_url="http://b/rss"),
    ])
    assert opml_mod.remove_entry(p, "http://a/rss") is True
    assert opml_mod.remove_entry(p, "http://a/rss") is False
    assert [e.xml_url for e in opml_mod.parse(p)] == ["http://b/rss"]


def test_update_entry_preserves_extension_attrs(tmp_path):
    p = tmp_path / "f.opml"
    _write_seed(p, [OpmlEntry(title="A", xml_url="http://a/rss")])
    assert opml_mod.update_entry(
        p, "http://a/rss",
        text="My A", abbrev="AAA", color="#112233",
        html_url="http://a/",
    ) is True
    entries = opml_mod.parse(p)
    assert len(entries) == 1
    e = entries[0]
    assert e.title == "My A"
    assert e.abbrev == "AAA"
    assert e.color == "#112233"
    assert e.html_url == "http://a/"

    # Clear abbrev/color with empty string
    opml_mod.update_entry(p, "http://a/rss", abbrev="", color="")
    e = opml_mod.parse(p)[0]
    assert e.abbrev is None
    assert e.color is None
    # Title preserved
    assert e.title == "My A"


def test_sync_to_db_fresh(tmp_path):
    opml_path = tmp_path / "f.opml"
    _write_seed(opml_path, [
        OpmlEntry(title="A", xml_url="http://a/rss", abbrev="AAA", color="#ff0000"),
        OpmlEntry(title="B", xml_url="http://b/rss"),
    ])
    s = Storage(tmp_path / "db.sqlite")
    try:
        added, updated = opml_mod.sync_to_db(opml_path, s)
        assert added == 2
        assert updated == 0
        feeds = {f.url: f for f in s.list_feeds()}
        assert feeds["http://a/rss"].abbrev == "AAA"
        assert feeds["http://a/rss"].color == "#ff0000"
        assert feeds["http://a/rss"].name == "A"
        assert feeds["http://b/rss"].abbrev is None
    finally:
        s.close()


def test_sync_to_db_leaves_extra_feeds_alone(tmp_path):
    opml_path = tmp_path / "f.opml"
    _write_seed(opml_path, [OpmlEntry(title="A", xml_url="http://a/rss")])
    s = Storage(tmp_path / "db.sqlite")
    try:
        s.add_feed(url="http://ghost/rss", title="Ghost")  # not in OPML
        opml_mod.sync_to_db(opml_path, s)
        urls = {f.url for f in s.list_feeds()}
        assert "http://ghost/rss" in urls
        assert "http://a/rss" in urls
    finally:
        s.close()


def test_sync_to_db_opml_wins_on_updates(tmp_path):
    opml_path = tmp_path / "f.opml"
    _write_seed(opml_path, [
        OpmlEntry(title="A new title", xml_url="http://a/rss",
                  abbrev="ANT", color="#abcdef"),
    ])
    s = Storage(tmp_path / "db.sqlite")
    try:
        s.add_feed(url="http://a/rss", title="A old")
        added, updated = opml_mod.sync_to_db(opml_path, s)
        assert added == 0
        assert updated == 1
        f = s.list_feeds()[0]
        assert f.name == "A new title"
        assert f.abbrev == "ANT"
        assert f.color == "#abcdef"
    finally:
        s.close()


# --- end-to-end CLI ---

@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    state = tmp_path / "state"
    (cfg / "riverr").mkdir(parents=True)
    (state / "riverr").mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.setenv("XDG_DATA_HOME", str(state))
    return {
        "opml": cfg / "riverr" / "feeds.opml",
        "db": state / "riverr" / "state.db",
    }


def test_remove_writes_opml_and_survives_db_wipe(cli_env, capsys):
    # Seed an OPML manually so we don't need network for `add`.
    opml_mod.write([
        OpmlEntry(title="Keep", xml_url="http://keep/rss"),
        OpmlEntry(title="Gone", xml_url="http://gone/rss"),
    ], cli_env["opml"])

    # Bootstrap (sync OPML → DB), then remove "Gone".
    rc = main(["remove", "http://gone/rss"])
    assert rc == 0

    # OPML now lacks Gone.
    urls = {e.xml_url for e in opml_mod.parse(cli_env["opml"])}
    assert urls == {"http://keep/rss"}

    # Wipe DB.
    cli_env["db"].unlink()

    # Relaunch via `list` — bootstrap should NOT resurrect Gone.
    rc = main(["list"])
    assert rc == 0
    s = Storage(cli_env["db"])
    try:
        urls = {f.url for f in s.list_feeds()}
    finally:
        s.close()
    assert urls == {"http://keep/rss"}, f"removed feed resurrected: {urls}"


def test_bootstrap_seeds_opml_from_packaged_on_first_launch(cli_env):
    # No OPML present yet.
    assert not cli_env["opml"].exists()
    rc = main(["list"])
    assert rc == 0
    assert cli_env["opml"].exists()
    # Packaged seeds should now be in OPML.
    titles = {e.title for e in opml_mod.parse(cli_env["opml"])}
    assert "Hacker News" in titles
