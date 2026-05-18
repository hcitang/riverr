"""Database retention policy.

One knob: `retention.max_items_per_feed` in settings.toml (default 500;
`0` disables pruning). Starred items are always exempt — they are never
deleted and don't count against the cap.

Pruning runs incrementally after each feed fetch. Maintenance
(`VACUUM` + FTS `optimize`) is heavier, so it runs at most once per day,
tracked via `retention.last_maintenance_at`.
"""
from __future__ import annotations

import time

from . import settings as settings_mod
from .storage import Storage


DEFAULT_MAX_ITEMS_PER_FEED = 500
MAINTENANCE_INTERVAL_SECONDS = 24 * 60 * 60


def get_cap() -> int:
    try:
        v = settings_mod.get(
            "retention.max_items_per_feed", DEFAULT_MAX_ITEMS_PER_FEED
        )
        return int(v)
    except (TypeError, ValueError):
        return DEFAULT_MAX_ITEMS_PER_FEED


def maybe_run_maintenance(storage: Storage, force: bool = False) -> bool:
    """Run `VACUUM` + FTS `optimize` if enough time has passed. Returns
    True if maintenance actually ran."""
    try:
        last = float(settings_mod.get("retention.last_maintenance_at", 0.0) or 0.0)
    except (TypeError, ValueError):
        last = 0.0
    now = time.time()
    if not force and (now - last) < MAINTENANCE_INTERVAL_SECONDS:
        return False
    storage.optimize_fts()
    storage.vacuum()
    try:
        settings_mod.set_("retention.last_maintenance_at", now)
    except Exception:
        pass
    return True


def human_size(nbytes: float) -> str:
    """Compact `ls -lh`-style size: 900B, 1.0K, 772K, 2.5M, 1.3G."""
    if nbytes < 1024:
        return f"{int(nbytes)}B"
    n = float(nbytes)
    for unit in ("K", "M", "G", "T"):
        n /= 1024
        if n < 1024:
            return f"{n:.1f}{unit}" if n < 10 else f"{n:.0f}{unit}"
    return f"{n:.1f}P"
