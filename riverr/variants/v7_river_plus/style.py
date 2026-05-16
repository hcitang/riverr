"""Color, tag, age, title-truncation, and text helpers for v7."""
from __future__ import annotations

import hashlib
import time
from typing import Optional

from rich.text import Text

from riverr.core.storage import Feed


_TAG_PALETTE = [
    "bright_cyan", "bright_magenta", "bright_yellow", "bright_green",
    "bright_blue", "bright_red", "cyan", "magenta", "yellow", "green",
    "blue", "red",
]

TAG_WIDTH = 5
ABBREV_WIDTH = 3
AGE_WIDTH = 4  # max visual width of " 12mo" etc; we pad to fixed 5 cols incl. leading space
STAR_WIDTH = 2  # "★ "

CURSOR_BLUE = "#1e6fff"


def _is_valid_hex_color(s: str) -> bool:
    if not s or len(s) != 7 or s[0] != "#":
        return False
    return all(c in "0123456789abcdefABCDEF" for c in s[1:])


def tag_color_for_url(url: str) -> str:
    h = hashlib.sha1((url or "").encode()).digest()
    n = int.from_bytes(h[1:5], "big")
    return _TAG_PALETTE[n % len(_TAG_PALETTE)]


def tag_color_for_feed(feed: Feed) -> str:
    """Per-feed color: explicit override first, else hash of abbrev/name."""
    if feed.color and _is_valid_hex_color(feed.color):
        return feed.color
    seed = (feed.abbrev or _short_tag(feed.name)).strip() or feed.url
    h = hashlib.sha1(seed.encode()).digest()
    n = int.from_bytes(h[1:5], "big")
    return _TAG_PALETTE[n % len(_TAG_PALETTE)]


def _short_tag(name: str, n: int = TAG_WIDTH) -> str:
    name = (name or "").strip()
    parts = name.split()
    if len(parts) >= 2:
        initials = "".join(p[0].upper() for p in parts)
        if 0 < len(initials) <= n:
            name = initials
    if len(name) <= n:
        return name.ljust(n)
    return name[: n - 1] + "…"


def feed_tag(feed: Feed) -> str:
    """Display tag — abbrev if set, else v5-style auto tag."""
    if feed.abbrev:
        return feed.abbrev.ljust(TAG_WIDTH)[:TAG_WIDTH]
    return _short_tag(feed.name)


def _age(ts: Optional[float]) -> str:
    if not ts:
        return ""
    delta = max(0, time.time() - ts)
    if delta < 60:
        return f"{int(delta)}s"
    if delta < 3600:
        return f"{int(delta/60)}m"
    if delta < 86400:
        return f"{int(delta/3600)}h"
    if delta < 86400 * 30:
        return f"{int(delta/86400)}d"
    return f"{int(delta/86400/30)}mo"


def _truncate_title(title: str, max_width: int) -> str:
    if max_width <= 0:
        return ""
    if len(title) <= max_width:
        return title
    if max_width <= 1:
        return "…"
    return title[: max_width - 1] + "…"


def _norm_title(s: str) -> str:
    """Normalize a title for duplicate-detection: lowercase, collapse
    whitespace, strip leading symbols (DF's ★, etc.)."""
    import re as _re
    out = _re.sub(r"\s+", " ", (s or "")).strip().lower()
    return out.lstrip("★☆*# ").strip()


def _strip_trailing_blanklines(t: Text) -> Text:
    """Trim trailing whitespace/newlines from a Rich Text. We mount one
    Static per block and rely on the body-scroll CSS margin-bottom for
    inter-block spacing; trailing \\n\\n inside the Static would double it."""
    plain = t.plain
    stripped = plain.rstrip()
    if stripped == plain:
        return t
    if not stripped:
        return Text()
    return t[: len(stripped)]
