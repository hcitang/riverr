"""v7 River Plus.

Fork of v5_river with:
  - star / unstar / mark-unread
  - mark-below-cursor read
  - three switchable views (all / per-feed / starred)
  - edit-feed modal with 3-char abbrev
  - inline image rendering on Ghostty/Kitty/iTerm
  - expanded-article navigation (space scrolls body, then collapses;
    j/k move highlight and collapse the currently expanded item)
  - title truncation with ellipsis preserving the age column
  - custom VerticalScroll-based row list (not ListView) so the expanded
    body can reliably fill the viewport height

The package is split into:
  - rows.py        — RiverRow / BodyRow / RiverList / FeedPickRow
  - edit_modal.py  — EditFeedScreen
  - style.py       — colors, tags, age, title truncation, text helpers
  - behavior.py    — VIEW_* constants, source labels, debug helper

Tests and external callers import V7App from here. BodyRow / RiverRow /
EditFeedScreen / VIEW_STARRED are re-exported for back-compat.
"""
from __future__ import annotations

import os
import time

import httpx
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import Footer, Input, ListItem, ListView, Static

from riverr.core import images as imgmod
from riverr.core import keys as keymod
from riverr.core import opml as opml_mod
from riverr.core.app_base import RiverrApp
from riverr.core.config import get_paths
from riverr.core.extract import is_stub
from riverr.core.retention import human_size
from riverr.core.search import filter_items, fts_search
from riverr.core.storage import Feed, Item, Storage

from riverr.core.logging import get_logger

from .behavior import VIEW_ALL, VIEW_FEED, VIEW_STARRED


log = get_logger(__name__)
from .body import BodyRow
from .edit_modal import EditFeedScreen
from .rows import FeedPickRow, RiverList, RiverRow
from .style import _is_valid_hex_color, feed_tag, tag_color_for_feed


__all__ = [
    "V7App",
    "BodyRow",
    "RiverRow",
    "RiverList",
    "FeedPickRow",
    "EditFeedScreen",
    "VIEW_ALL",
    "VIEW_FEED",
    "VIEW_STARRED",
    "run",
]


class V7App(RiverrApp):
    CSS = """
    Screen { layout: vertical; }
    #breadcrumb { height: 1; background: $boost; color: $text; padding: 0 1; }
    RiverList { height: 1fr; }
    #status { height: 1; background: $boost; color: $text; padding: 0 1; }
    #picker {
        layer: overlay;
        dock: top;
        offset: 0 2;
        width: 50%;
        height: auto;
        max-height: 60%;
        border: round $primary;
        background: $surface;
    }
    Input { dock: bottom; }
    """

    _SIMPLE_ACTIONS = [
        "move_down", "move_up", "page_down", "page_up", "open", "back",
        "refresh", "mark_all_read",
        "add_feed", "edit_title",
        "yank_url", "open_url",
        "filter", "search_global", "quit",
        "star", "mark_unread",
        "view_next", "view_prev",
        "toggle_images",
    ]
    _CYCLE_ACTIONS = (("cycle_link_next", 1), ("cycle_link_prev", -1))

    BINDINGS = [
        Binding(k, a, d, show=False)
        for (k, a, d) in keymod.bindings_for(_SIMPLE_ACTIONS, keymap=keymod.DEFAULTS)
    ] + [
        Binding(k, f"cycle_link({arg})", d, show=False)
        for action, arg in _CYCLE_ACTIONS
        for (k, _, d) in keymod.bindings_for([action], keymap=keymod.DEFAULTS)
    ] + [
        Binding("f", "feed_filter", "Pick feed", show=False),
    ]

    breadcrumb_text: reactive[str] = reactive("riverr")
    status_text: reactive[str] = reactive("")

    def __init__(
        self,
        storage: Storage | None = None,
        transport: httpx.BaseTransport | None = None,
        keymap: dict | None = None,
    ) -> None:
        super().__init__(storage=storage, transport=transport, keymap=keymap)
        self.session_start = time.time()
        self.current_item: Item | None = None
        self.current_items: list[Item] = []
        self.filter_query: str = ""
        self._feeds_by_id: dict[int, Feed] = {}
        self.view_index: int = 0
        self._view_order: list[tuple[str, int | None, str]] = []
        self._kbd_mode: bool = False

    def compose(self) -> ComposeResult:
        yield Static(self.breadcrumb_text, id="breadcrumb")
        yield RiverList(id="river")
        yield Static(self.status_text, id="status")
        yield Footer()

    def on_mount(self) -> None:
        log.debug(
            "startup TERM=%r TERM_PROGRAM=%r KITTY_WINDOW_ID=%r "
            "RIVERR_FORCE_IMAGE_PROTOCOL=%r "
            "supports_kitty_graphics=%s supports_inline_images=%s",
            os.environ.get("TERM"),
            os.environ.get("TERM_PROGRAM"),
            os.environ.get("KITTY_WINDOW_ID"),
            os.environ.get("RIVERR_FORCE_IMAGE_PROTOCOL"),
            imgmod.supports_kitty_graphics(),
            imgmod.supports_inline_images(),
        )
        self._reload_feeds()
        self._rebuild_view_order()
        self.load_items()
        self.update_status()
        self._focus_first_item()
        try:
            self.query_one("#river", RiverList).focus()
        except Exception:
            pass

    def _focus_first_item(self) -> None:
        try:
            lv = self.query_one("#river", RiverList)
        except Exception:
            return
        for i, c in enumerate(lv.children):
            if isinstance(c, RiverRow):
                lv.set_cursor(i)
                return
        lv.set_cursor(None)

    # --- data ---

    def _reload_feeds(self) -> None:
        self._feeds_by_id = {f.id: f for f in self.storage.list_feeds()}

    def _rebuild_view_order(self) -> None:
        order: list[tuple[str, int | None, str]] = [(VIEW_ALL, None, "All Feeds")]
        for f in self.storage.list_feeds():
            order.append((VIEW_FEED, f.id, f.name))
        order.append((VIEW_STARRED, None, "Starred"))
        self._view_order = order
        if self.view_index >= len(order):
            self.view_index = 0

    def _current_view(self) -> tuple[str, int | None, str]:
        if not self._view_order:
            return (VIEW_ALL, None, "All Feeds")
        return self._view_order[self.view_index]

    def _merged_items(self) -> list[Item]:
        all_items: list[Item] = []
        for fid in self._feeds_by_id:
            all_items.extend(self.storage.items_for_feed(fid))
        all_items.sort(
            key=lambda it: it.published_at or it.fetched_at or 0.0,
            reverse=True,
        )
        return all_items

    def load_items(self) -> None:
        lv = self.query_one("#river", RiverList)
        lv.clear()
        kind, fid, _label = self._current_view()
        if kind == VIEW_STARRED:
            items = self.storage.list_starred()
        elif kind == VIEW_FEED and fid is not None:
            items = self.storage.items_for_feed(fid)
        else:
            items = self._merged_items()
        if self.filter_query:
            q = self.filter_query.lower()
            text_hits = set(id(it) for it in filter_items(items, self.filter_query))
            items = [
                it for it in items
                if id(it) in text_hits
                or q in (self._feeds_by_id.get(it.feed_id).name.lower()
                         if self._feeds_by_id.get(it.feed_id) else "")
            ]
        self.current_items = items

        for it in items:
            feed = self._feeds_by_id.get(it.feed_id)
            if feed is None:
                continue
            lv.append(RiverRow(it, feed))
        if items:
            self.current_item = items[0]
            self._focus_first_item()
        else:
            self.current_item = None
            lv.set_cursor(None)

    # --- status / breadcrumb ---

    def update_status(self) -> None:
        unread = self.storage.unread_count()
        last = self.storage.last_fetch_at() or self.session_start
        last_str = time.strftime("%H:%M:%S", time.localtime(last))
        kind, _fid, label = self._current_view()
        parts = ["river+", label]
        if self.filter_query:
            parts.append(f"/{self.filter_query}")
        size_str = human_size(self.storage.db_size_bytes())
        self.breadcrumb_text = (
            f"{' ▸ '.join(parts)}    "
            f"[dim]{unread} unread · last refresh {last_str} · db {size_str}[/]"
        )
        self.status_text = (
            "Enter expand  </> view  s star  u unread  f pick feed  "
            "/ filter  ^r refresh  R mark below read  q quit"
        )
        try:
            self.query_one("#breadcrumb", Static).update(self.breadcrumb_text)
            self.query_one("#status", Static).update(self.status_text)
        except Exception:
            pass

    # --- focused-row helpers ---

    def _focused_child(self):
        lv = self.query_one("#river", RiverList)
        if lv.index is None:
            return None
        try:
            return lv.children[lv.index]
        except IndexError:
            return None

    def _row_under_cursor(self) -> RiverRow | None:
        child = self._focused_child()
        if isinstance(child, RiverRow):
            return child
        if isinstance(child, BodyRow):
            return child.owner
        return None

    def _focused_body(self) -> BodyRow | None:
        child = self._focused_child()
        if isinstance(child, BodyRow):
            return child
        row = self._row_under_cursor()
        if row and row.expanded and row.body_row:
            return row.body_row
        return None

    def _expanded_rows(self) -> list[RiverRow]:
        lv = self.query_one("#river", RiverList)
        return [c for c in lv.children if isinstance(c, RiverRow) and c.expanded]

    def _collapse_all_expanded(self) -> None:
        for row in self._expanded_rows():
            self._collapse(row)

    # --- expand / collapse ---

    def _collapse(self, row: RiverRow) -> None:
        if not row.expanded:
            return
        if row.body_row is not None:
            try:
                row.body_row.remove()
            except Exception:
                pass
        row.expanded = False
        row.body_row = None
        row.refresh_label()

    def _compute_body_height(self) -> int:
        try:
            total = self.size.height
        except Exception:
            total = 24
        # chrome: breadcrumb(1) + status(1) + footer(~1)
        chrome = 3
        # plus the header RiverRow itself
        header = 1
        return max(5, total - chrome - header)

    def toggle_expand(self, row: RiverRow) -> None:
        lv = self.query_one("#river", RiverList)
        if row.expanded:
            self._collapse(row)
            return
        self._collapse_all_expanded()
        fresh = self.storage.get_item(row.item.id) or row.item
        row.item = fresh
        body = BodyRow(fresh, row, transport=self.transport)
        idx = lv.children.index(row)
        lv.insert_at(idx + 1, body)
        body.styles.height = self._compute_body_height()
        row.body_row = body
        row.expanded = True
        if not fresh.read:
            self.storage.mark_read(fresh.id, True)
            row.item.read = True
        self.call_after_refresh(body.render_body)
        try:
            lv.scroll_to_widget(row, top=True, animate=False)
        except Exception:
            pass
        lv.set_cursor(idx)
        row.refresh_label()
        if not fresh.extracted_body and is_stub(fresh):
            self._extract_for(fresh.id)
        self.current_item = fresh
        self.update_status()

    def on_resize(self, event) -> None:  # noqa: ANN001
        try:
            for row in self._expanded_rows():
                if row.body_row is not None:
                    row.body_row.styles.height = self._compute_body_height()
        except Exception:
            pass

    def _after_extract(self, item_id: int) -> None:
        refreshed = self.storage.get_item(item_id)
        if not refreshed:
            return
        try:
            lv = self.query_one("#river", RiverList)
        except Exception:
            return
        for child in list(lv.children):
            if isinstance(child, BodyRow) and child.item.id == item_id:
                child.item = refreshed
                child.render_body()
                break

    # --- events ---

    @on(RiverList.CursorChanged, "#river")
    def _on_cursor_changed(self, event: "RiverList.CursorChanged") -> None:
        if event.index is None:
            return
        try:
            child = event.sender_list.children[event.index]
        except IndexError:
            return
        if isinstance(child, RiverRow):
            self.current_item = child.item

    @on(ListView.Selected, "#picker")
    def _on_picker_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, FeedPickRow):
            target_fid = event.item.feed.id if event.item.feed else None
            for i, (kind, fid, _) in enumerate(self._view_order):
                if target_fid is None and kind == VIEW_ALL:
                    self.view_index = i
                    break
                if target_fid is not None and kind == VIEW_FEED and fid == target_fid:
                    self.view_index = i
                    break
            self._close_picker()
            self.load_items()
            self.update_status()

    # --- actions ---

    def _next_river_row(self, lv: RiverList, start_idx: int, direction: int) -> int | None:
        n = len(lv.children)
        i = start_idx + direction
        while 0 <= i < n:
            if isinstance(lv.children[i], RiverRow):
                return i
            i += direction
        return None

    def action_move_down(self) -> None:
        self._kbd_mode = True
        lv = self.query_one("#river", RiverList)
        row = self._row_under_cursor()
        if row is not None and row.expanded:
            owner_idx = lv.children.index(row)
            self._collapse(row)
            nxt = self._next_river_row(lv, owner_idx, +1)
            if nxt is None:
                lv.set_cursor(owner_idx)
                return
            lv.set_cursor(nxt)
            if self.behavior.get("expanded_j", "open_next") == "open_next":
                target = lv.children[nxt]
                if isinstance(target, RiverRow) and not target.expanded:
                    self.toggle_expand(target)
            return
        lv.move_cursor(+1)

    def action_move_up(self) -> None:
        self._kbd_mode = True
        lv = self.query_one("#river", RiverList)
        row = self._row_under_cursor()
        if row is not None and row.expanded:
            owner_idx = lv.children.index(row)
            self._collapse(row)
            prv = self._next_river_row(lv, owner_idx, -1)
            if prv is None:
                lv.set_cursor(owner_idx)
                return
            lv.set_cursor(prv)
            if self.behavior.get("expanded_k", "close_and_prev") == "open_next":
                target = lv.children[prv]
                if isinstance(target, RiverRow) and not target.expanded:
                    self.toggle_expand(target)
            return
        lv.move_cursor(-1)

    def action_open(self) -> None:
        row = self._row_under_cursor()
        if row is not None:
            self.toggle_expand(row)
            return
        try:
            self.query_one("#river", RiverList).focus()
        except Exception:
            pass

    def action_back(self) -> None:
        if self.query("#picker"):
            self._close_picker()
            return
        if self.filter_query:
            self.filter_query = ""
            self.load_items()
            self.update_status()
            return
        row = self._row_under_cursor()
        if row and row.expanded:
            self.toggle_expand(row)

    def _after_refresh(self) -> None:
        self._reload_feeds()
        self._rebuild_view_order()
        self.load_items()
        try:
            lv = self.query_one("#river", RiverList)
            lv.scroll_home(animate=False)
            self._focus_first_item()
        except Exception:
            pass
        self.update_status()

    def _step_cursor_rows(self, lv: "RiverList", delta_rows: int) -> None:
        """Shift the cursor by `delta_rows` RiverRow steps (skipping BodyRows).
        Deterministic — doesn't depend on Textual layout having settled."""
        cur = lv._cursor_index if lv._cursor_index is not None else 0
        n = len(lv.children)
        step = 1 if delta_rows > 0 else -1
        remaining = abs(delta_rows)
        i = cur
        last_river = cur
        while 0 <= i < n and remaining > 0:
            i += step
            if 0 <= i < n and isinstance(lv.children[i], RiverRow):
                last_river = i
                remaining -= 1
        lv.set_cursor(last_river)

    def action_page_down(self) -> None:
        body = self._focused_body()
        if body is not None:
            scroll = body.scroll
            try:
                at_bottom = (
                    scroll.max_scroll_y == 0
                    or scroll.scroll_y >= scroll.max_scroll_y - 1
                )
            except Exception:
                at_bottom = True
            if at_bottom:
                self._collapse(body.owner)
                return
            try:
                scroll.scroll_page_down(animate=False)
            except Exception:
                pass
            return
        try:
            lv = self.query_one("#river", RiverList)
            page = max(1, lv.size.height)
            self._step_cursor_rows(lv, +page)
            lv.scroll_page_down(animate=False)
        except Exception:
            pass

    def action_page_up(self) -> None:
        body = self._focused_body()
        if body is not None:
            try:
                body.scroll.scroll_page_up(animate=False)
            except Exception:
                pass
            return
        try:
            lv = self.query_one("#river", RiverList)
            page = max(1, lv.size.height)
            self._step_cursor_rows(lv, -page)
            lv.scroll_page_up(animate=False)
        except Exception:
            pass

    def action_mark_all_read(self) -> None:
        """Mark every item at or below the focused row, within the current
        view, as read. Stars preserved. Cursor stays put."""
        lv = self.query_one("#river", RiverList)
        idx = lv.index if lv.index is not None else 0
        cur_child = self._focused_child()
        cur_item_id = (
            cur_child.item.id if isinstance(cur_child, RiverRow) else None
        )
        below: list[Item] = []
        for c in lv.children[idx:]:
            if isinstance(c, RiverRow):
                below.append(c.item)
        self.storage.mark_below_read(below)
        self.load_items()
        def _restore_cursor() -> None:
            try:
                lv2 = self.query_one("#river", RiverList)
            except Exception:
                return
            if cur_item_id is not None:
                for i, c in enumerate(lv2.children):
                    if isinstance(c, RiverRow) and c.item.id == cur_item_id:
                        lv2.set_cursor(i)
                        return

        self.call_after_refresh(_restore_cursor)
        self.update_status()

    def action_star(self) -> None:
        row = self._row_under_cursor()
        if row is None:
            return
        new_state = not row.item.starred
        self.storage.set_starred(row.item.id, new_state)
        row.item.starred = new_state
        row.refresh_label()

    def action_mark_unread(self) -> None:
        row = self._row_under_cursor()
        if row is None:
            return
        if row.item.read:
            self.storage.mark_unread(row.item.id)
            row.item.read = False
        else:
            self.storage.mark_read(row.item.id, True)
            row.item.read = True
        row.refresh_label()
        self.update_status()

    def action_view_next(self) -> None:
        if not self._view_order:
            return
        self.view_index = (self.view_index + 1) % len(self._view_order)
        self.load_items()
        self.update_status()

    def action_view_prev(self) -> None:
        if not self._view_order:
            return
        self.view_index = (self.view_index - 1) % len(self._view_order)
        self.load_items()
        self.update_status()

    def _after_images_toggled(self) -> None:
        try:
            lv = self.query_one("#river", RiverList)
        except Exception:
            return
        for c in list(lv.children):
            if isinstance(c, RiverRow) and c.expanded and c.body_row is not None:
                self._collapse(c)
                self._expand(c)

    def action_cycle_link(self, delta: int) -> None:
        body = self._focused_body()
        if not body or not body.link_targets:
            return
        new_idx = (body.link_cursor + delta) % len(body.link_targets)
        url = body.highlight_link(new_idx)
        if url:
            self.status_text = f"link [{body.link_cursor+1}/{len(body.link_targets)}]: {url}"
            try:
                self.query_one("#status", Static).update(self.status_text)
            except Exception:
                pass

    def _url_under_cursor(self) -> str | None:
        body = self._focused_body()
        if body and body.link_targets and 0 <= body.link_cursor < len(body.link_targets):
            return body.link_targets[body.link_cursor]
        if self.current_item and self.current_item.link:
            return self.current_item.link
        return None

    def action_filter(self) -> None:
        self._prompt = "filter"
        self._show_prompt("filter")

    def action_search_global(self) -> None:
        self._prompt = "search"
        self._show_prompt("search")

    def action_add_feed(self) -> None:
        self._prompt = "add_feed"
        self._show_prompt("add feed URL")

    def action_edit_title(self) -> None:
        row = self._row_under_cursor()
        if row is None:
            return
        feed = self._feeds_by_id.get(row.feed.id)
        if feed is None:
            return

        def _after(result: tuple[str, str, str] | None) -> None:
            if result is None:
                return
            if len(result) == 2:
                title, abbrev = result
                color = ""
            else:
                title, abbrev, color = result
            if title:
                self.storage.rename_feed(feed.id, title)
            self.storage.set_abbrev(feed.id, abbrev or None)
            color_val = color or None
            if color_val and not _is_valid_hex_color(color_val):
                color_val = None
            self.storage.set_color(feed.id, color_val)
            try:
                opml_mod.update_entry(
                    get_paths().opml,
                    feed.url,
                    text=title or None,
                    abbrev=abbrev or "",
                    color=color_val or "",
                )
            except Exception:
                pass
            self._reload_feeds()
            self._rebuild_view_order()
            self.load_items()
            self.update_status()

        self.push_screen(EditFeedScreen(feed), _after)

    def action_feed_filter(self) -> None:
        if self.query("#picker"):
            self._close_picker()
            return
        self._open_picker()

    # --- picker overlay ---

    def _open_picker(self) -> None:
        self._reload_feeds()
        picker = ListView(id="picker")
        self.mount(picker)
        picker.append(ListItem(Static("[b]· all feeds ·[/]", markup=True), id="all"))
        for f in self._feeds_by_id.values():
            color = tag_color_for_feed(f)
            tag = feed_tag(f)
            label = f"[black on {color}] {tag} [/] [b]{f.name}[/]"
            li = ListItem(Static(label, markup=True))
            li.feed = f  # type: ignore[attr-defined]
            picker.append(li)
        picker.index = 0
        picker.focus()

    def _close_picker(self) -> None:
        for w in list(self.query("#picker")):
            w.remove()
        try:
            self.query_one("#river", RiverList).focus()
        except Exception:
            pass

    @on(ListView.Selected, "#picker")
    def _on_picker_selected_lv(self, event: ListView.Selected) -> None:
        feed = getattr(event.item, "feed", None)
        target_fid = feed.id if feed else None
        for i, (kind, fid, _) in enumerate(self._view_order):
            if target_fid is None and kind == VIEW_ALL:
                self.view_index = i
                break
            if target_fid is not None and kind == VIEW_FEED and fid == target_fid:
                self.view_index = i
                break
        self._close_picker()
        self.load_items()
        self.update_status()

    # --- prompt ---

    def _show_prompt(self, label: str) -> None:
        for w in self.query("#prompt"):
            w.remove()
        inp = Input(placeholder=f"{label}:", id="prompt")
        self.mount(inp)
        inp.focus()

    @on(Input.Submitted, "#prompt")
    async def _on_prompt(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        mode = getattr(self, "_prompt", "filter")
        event.input.remove()
        if mode == "filter":
            self.filter_query = value
            self.load_items()
        elif mode == "search":
            hits = fts_search(self.storage, value)
            self.current_items = hits
            lv = self.query_one("#river", RiverList)
            lv.clear()
            for it in hits:
                feed = self._feeds_by_id.get(it.feed_id)
                if feed is None:
                    continue
                lv.append(RiverRow(it, feed))
            if hits:
                self.current_item = hits[0]
                self._focus_first_item()
            else:
                self.current_item = None
        elif mode == "add_feed" and value:
            from riverr.core.feeds import add_by_url
            try:
                await add_by_url(value, self.storage, transport=self.transport)
            except Exception:
                pass
            self._reload_feeds()
            self._rebuild_view_order()
            self.load_items()
        self.update_status()
        try:
            self.query_one("#river", RiverList).focus()
        except Exception:
            pass


def run(storage: Storage | None = None, transport: httpx.BaseTransport | None = None) -> None:
    V7App(storage=storage, transport=transport).run()
