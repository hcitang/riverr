from __future__ import annotations

import base64

from riverr.core.links import copy_url, truncate_middle


def test_truncate_middle_short_unchanged():
    assert truncate_middle("https://x.test", 80) == "https://x.test"


def test_truncate_middle_long_uses_ellipsis():
    url = "https://example.com/" + ("a" * 200)
    out = truncate_middle(url, 50)
    assert "…" in out
    # default left=25, right=15 -> 25 + 1 + 15 = 41 chars when width allows
    assert len(out) <= 50
    assert out.startswith(url[:25])
    assert out.endswith(url[-15:])


def test_truncate_middle_tight_width():
    out = truncate_middle("abcdefghijklmnop", 10)
    assert len(out) <= 10
    assert "…" in out


def test_copy_url_writes_osc52(capsys, monkeypatch):
    monkeypatch.delenv("RIVERR_CLIPBOARD", raising=False)
    url = "https://example.com/x?y=1"
    assert copy_url(url) is True
    out = capsys.readouterr().out
    assert out.startswith("\x1b]52;c;")
    assert out.endswith("\x07")
    payload = out[len("\x1b]52;c;"):-1]
    assert base64.b64decode(payload).decode("utf-8") == url


def test_copy_url_empty_false():
    assert copy_url("") is False
