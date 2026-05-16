"""Shared App base class for riverr variants.

Owns boilerplate that has one right answer: keymap installation, the
non-blocking refresh worker, yank/open URL, quit, toggle-images plumbing,
and the system command palette hook. Variants override `_after_refresh`,
`_after_images_toggled`, and `_url_under_cursor` to plug into their own
layout/cursor model.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import httpx
from textual import work
from textual.app import App
from textual.binding import Binding
from textual.widgets import Static

from . import keys as keymod
from . import settings as settings_mod
from .config import get_paths
from .extract import ensure_extracted
from .fetch import fetch_all
from .links import copy_url, open_url
from .storage import Storage


class RiverrApp(App):
    """Base App with shared keymap, refresh, yank/open, quit, image plumbing.

    Subclasses must:
      - implement `compose()` and `on_mount()`
      - extend `_SIMPLE_ACTIONS` if they introduce additional managed
        actions, and (re)declare class-level BINDINGS the same way v7 does
      - override `_after_refresh()` to rebuild their view after fetch
      - override `_after_images_toggled()` to re-render any expanded bodies
      - override `_url_under_cursor()` to expose the URL for yank/open
    """

    _SIMPLE_ACTIONS: list[str] = [
        "refresh", "mark_all_read",
        "yank_url", "open_url",
        "quit", "toggle_images",
    ]
    _CYCLE_ACTIONS: tuple = (("cycle_link_next", 1), ("cycle_link_prev", -1))
    _SHOWN_BINDINGS: set[str] = {
        "refresh", "mark_all_read", "yank_url", "open_url", "quit",
        "star", "toggle_images",
    }

    def __init__(
        self,
        storage: Storage | None = None,
        transport: httpx.BaseTransport | None = None,
        keymap: dict | None = None,
    ) -> None:
        super().__init__()
        self.storage = storage or Storage(get_paths().db)
        self.transport = transport
        keys_path: Optional[Path] = None
        try:
            p = get_paths().keys_toml
            if p.exists():
                keys_path = p
        except Exception:
            keys_path = None
        if keymap is None:
            try:
                keymap = keymod.load(keys_path)
            except Exception:
                keymap = keymod.load()
        self.keymap = keymap
        try:
            # Primary source: settings.toml [behavior]. keys_path is passed
            # only so the migration step inside settings can pick up any
            # legacy [behavior] block that still lives in keys.toml.
            self.behavior = keymod.get_behavior()
        except Exception:
            self.behavior = dict(keymod.BEHAVIOR_DEFAULTS)
        self._install_keymap_bindings()
        try:
            self.images_enabled: bool = bool(
                settings_mod.get("display.images_enabled", True)
            )
        except Exception:
            self.images_enabled = True

    # --- keymap ---

    def _install_keymap_bindings(self) -> None:
        try:
            mapping = self._bindings.key_to_bindings
        except AttributeError:
            return
        managed_actions = (
            set(self._SIMPLE_ACTIONS) | {"cycle_link", "feed_filter"}
        )
        for key in list(mapping.keys()):
            kept = [
                b for b in mapping[key]
                if b.action.split("(")[0] not in managed_actions
            ]
            if kept:
                mapping[key] = kept
            else:
                del mapping[key]
        for (k, a, d) in keymod.bindings_for(
            self._SIMPLE_ACTIONS, keymap=self.keymap
        ):
            label = d
            if a == "mark_all_read":
                label = "Mark below read"
            mapping.setdefault(k, []).append(
                Binding(k, a, label, show=(a in self._SHOWN_BINDINGS))
            )
        for action, arg in self._CYCLE_ACTIONS:
            for (k, _, d) in keymod.bindings_for([action], keymap=self.keymap):
                mapping.setdefault(k, []).append(
                    Binding(k, f"cycle_link({arg})", d, show=False)
                )
        ff_keys = self.keymap.get("feed_filter") or ["f"]
        for k in ff_keys:
            if "," in k:
                continue
            mapping.setdefault(k, []).append(
                Binding(k, "feed_filter", "Pick feed", show=False)
            )

    # --- hooks for subclasses ---

    def _after_refresh(self) -> None:
        """Called after the refresh worker has finished updating storage.
        Subclasses should rebuild their view here."""

    def _after_images_toggled(self) -> None:
        """Called after `images_enabled` has been flipped and persisted.
        Subclasses re-render any expanded bodies here."""

    def _url_under_cursor(self) -> str | None:
        """Return the URL currently focused (for yank/open). Subclasses
        override; default has nothing to yank."""
        return None

    # --- shared actions ---

    def action_refresh(self) -> None:
        self._do_refresh()

    def action_quit(self) -> None:
        self.exit()

    def action_yank_url(self) -> None:
        url = self._url_under_cursor()
        if not url:
            return
        copy_url(url)
        try:
            self.query_one("#status", Static).update("Copied to clipboard")
        except Exception:
            pass
        self.set_timer(2.0, lambda: self._flash(""))

    def action_open_url(self) -> None:
        url = self._url_under_cursor()
        if url:
            open_url(url)

    def action_toggle_images(self) -> None:
        self.images_enabled = not self.images_enabled
        try:
            settings_mod.set_("display.images_enabled", self.images_enabled)
        except Exception:
            pass
        state = "on" if self.images_enabled else "off"
        self._flash(f"Inline images: {state}")
        self.set_timer(2.0, lambda: self._flash(""))
        self._after_images_toggled()

    # --- refresh worker ---

    @work(exclusive=True, group="refresh")
    async def _do_refresh(self) -> None:
        feeds = self.storage.list_feeds()
        urls = [f.url for f in feeds]
        total = len(urls)
        self._flash(f"Refreshing… (0/{total})")
        new_total = 0
        results = await fetch_all(urls, transport=self.transport)
        for f, res in zip(feeds, results):
            if res.ok:
                before = self.storage.unread_count(f.id)
                self.storage.upsert_items(f.id, res.items)
                self.storage.set_last_fetched(f.id, time.time())
                self.storage.log_fetch(f.id, True, len(res.items))
                after = self.storage.unread_count(f.id)
                new_total += max(0, after - before)
            else:
                self.storage.log_fetch(f.id, False, 0, res.error)
        self._after_refresh()
        self._flash(f"Refreshed: +{new_total} new")
        self.set_timer(3.0, lambda: self._flash(""))

    # --- extract worker ---

    @work(exclusive=False, group="extract")
    async def _extract_for(self, item_id: int) -> None:
        item = self.storage.get_item(item_id)
        if not item:
            return
        await ensure_extracted(item, self.storage, transport=self.transport)
        self._after_extract(item_id)

    def _after_extract(self, item_id: int) -> None:
        """Hook called after extraction finishes for `item_id`. Subclasses
        update any visible body for this item."""

    # --- status helper ---

    def _flash(self, msg: str) -> None:
        if not msg:
            # Subclasses with a richer status line override update_status.
            updater = getattr(self, "update_status", None)
            if callable(updater):
                updater()
                return
            try:
                self.query_one("#status", Static).update("")
            except Exception:
                pass
            return
        try:
            self.query_one("#status", Static).update(msg)
        except Exception:
            pass

    # --- system commands ---

    def get_system_commands(self, screen):  # noqa: ANN001
        try:
            yield from super().get_system_commands(screen)
        except Exception:
            pass
        from textual.command import SystemCommand
        state = "off" if self.images_enabled else "on"
        yield SystemCommand(
            f"Toggle inline images "
            f"(currently {'on' if self.images_enabled else 'off'})",
            f"Turn inline image rendering {state}",
            self.action_toggle_images,
        )
