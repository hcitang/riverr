from pathlib import Path

from riverr.core import opml as opml_mod


SEEDS = Path(__file__).resolve().parent.parent / "seeds.opml"


def test_parse_seeds():
    entries = opml_mod.parse(SEEDS)
    titles = [e.title for e in entries]
    assert "Hacker News" in titles
    assert "CBC Top Stories" in titles
    assert "CNA Top Stories" in titles
    assert "Daring Fireball" in titles
    for e in entries:
        assert e.xml_url.startswith("http")


def test_roundtrip(tmp_path):
    entries = opml_mod.parse(SEEDS)
    out = tmp_path / "out.opml"
    opml_mod.write(entries, out)
    again = opml_mod.parse(out)
    assert [(e.title, e.xml_url) for e in again] == [(e.title, e.xml_url) for e in entries]
