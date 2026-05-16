"""Row widgets for v7: _Row base, RiverRow, RiverList, FeedPickRow.

BodyRow lives in body.py — it's chunky enough (image fetch + render loop)
to warrant its own module. RiverList references it via late import to
keep the dependency one-way.
"""
from __future__ import annotations

from typing import Optional

from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Static

from riverr.core.storage import Feed, Item

from .body import BodyRow
from .style import (
    AGE_WIDTH,
    TAG_WIDTH,
    _age,
    _truncate_title,
    feed_tag,
    tag_color_for_feed,
)


class _Row(Static):
    """Base for all rows in the river list. Tracks whether it's the
    cursor row via the `cursor` CSS class."""

    DEFAULT_CSS = """
    _Row { height: 1; padding: 0 1; }
    _Row.cursor { background: #1e6fff; color: white; }
    """

    def set_cursor(self, on_: bool) -> None:
        if on_:
            self.add_class("cursor")
        else:
            self.remove_class("cursor")
        refresh = getattr(self, "refresh_label", None)
        if callable(refresh):
            refresh()


class RiverRow(_Row):
    """One item row in the river. Renders a single line:
    dot · tag · star · title (truncated) · ··· age"""

    DEFAULT_CSS = """
    RiverRow { height: 1; padding: 0 1; }
    RiverRow.cursor { background: #1e6fff; color: white; }
    """

    def __init__(self, item: Item, feed: Feed) -> None:
        self.item = item
        self.feed = feed
        self.expanded = False
        self.body_row: Optional[BodyRow] = None
        super().__init__("", markup=True)
        self.refresh_label()

    def _row_width(self) -> int:
        try:
            w = self.size.width
        except Exception:
            w = 0
        if not w:
            try:
                w = self.app.size.width
            except Exception:
                w = 80
        return max(20, w)

    def _render_text(self, width: int) -> str:
        it = self.item
        f = self.feed
        dot = "●" if not it.read else " "
        dot_style = "bold cyan" if not it.read else "dim"
        title_style = "bold" if not it.read else "dim"
        tag = feed_tag(f)
        color = tag_color_for_feed(f)
        age = _age(it.published_at or it.fetched_at)
        star = "★ " if it.starred else ""
        focused = "cursor" in self.classes
        if focused and self.expanded:
            marker = "▼ "
        elif focused:
            marker = "▶ "
        else:
            marker = "  "
        fixed = (
            2          # marker
            + 2        # dot + space
            + TAG_WIDTH + 3  # " TAG " padded with surrounding space
            + (2 if star else 0)
            + 2        # 2 spaces gap
            + max(len(age), AGE_WIDTH)
            + 2        # outer padding (CSS padding: 0 1)
        )
        max_title = max(1, width - fixed)
        title = _truncate_title(it.title, max_title)
        # Pad the title to max_title so the age column always lands at the
        # same right-aligned position across every row, regardless of title
        # length. Without this, short titles let age float left.
        title_padded = title.ljust(max_title)
        age_pad = age.rjust(max(len(age), AGE_WIDTH))
        star_part = f"[bold yellow]{star}[/]" if star else ""
        return (
            f"{marker}"
            f"[{dot_style}]{dot}[/] "
            f"[black on {color}] {tag} [/] "
            f"{star_part}[{title_style}]{title_padded}[/]  [dim]{age_pad}[/]"
        )

    def refresh_label(self) -> None:
        try:
            self.update(self._render_text(self._row_width()))
        except Exception:
            pass

    def on_resize(self, event) -> None:  # noqa: ANN001
        self.refresh_label()


class RiverList(VerticalScroll):
    """Custom row container with explicit cursor tracking.

    Holds RiverRow / BodyRow children in order. Tracks
    `cursor_index`. Posts CursorChanged when the cursor moves.
    """

    DEFAULT_CSS = """
    RiverList { height: 1fr; }
    """

    BINDINGS = [
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
    ]

    can_focus = True

    def action_cursor_down(self) -> None:
        self.move_cursor(+1)

    def action_cursor_up(self) -> None:
        self.move_cursor(-1)

    class CursorChanged(Message):
        def __init__(self, sender: "RiverList", index: int | None) -> None:
            super().__init__()
            self.sender_list = sender
            self.index = index

        @property
        def control(self) -> "RiverList":
            return self.sender_list

    class Activated(Message):
        def __init__(self, sender: "RiverList", index: int | None) -> None:
            super().__init__()
            self.sender_list = sender
            self.index = index

        @property
        def control(self) -> "RiverList":
            return self.sender_list

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cursor_index: int | None = None

    @property
    def rows(self) -> list:
        return [c for c in self.children]

    @property
    def index(self) -> int | None:
        return self._cursor_index

    @index.setter
    def index(self, value: int | None) -> None:
        self.set_cursor(value)

    def clear(self) -> None:
        for c in list(self.children):
            try:
                c.remove()
            except Exception:
                pass
        self._cursor_index = None

    def append(self, widget) -> None:
        self.mount(widget)

    def insert_at(self, index: int, widget) -> None:
        siblings = list(self.children)
        if index >= len(siblings):
            self.mount(widget)
        else:
            self.mount(widget, before=siblings[index])

    def set_cursor(self, index: int | None) -> None:
        if index is None:
            self._clear_cursor_class()
            self._cursor_index = None
            self.post_message(self.CursorChanged(self, None))
            return
        n = len(self.children)
        if n == 0:
            self._cursor_index = None
            return
        index = max(0, min(n - 1, index))
        self._clear_cursor_class()
        self._cursor_index = index
        try:
            child = self.children[index]
        except IndexError:
            return
        if hasattr(child, "set_cursor"):
            child.set_cursor(True)
        elif hasattr(child, "add_class"):
            child.add_class("cursor")
        try:
            self.scroll_to_widget(child, top=False, animate=False)
        except Exception:
            pass
        self.post_message(self.CursorChanged(self, index))

    def _clear_cursor_class(self) -> None:
        for c in self.children:
            if hasattr(c, "set_cursor"):
                c.set_cursor(False)
            elif hasattr(c, "remove_class"):
                c.remove_class("cursor")

    def move_cursor(self, delta: int) -> None:
        idx = self._cursor_index if self._cursor_index is not None else 0
        n = len(self.children)
        i = idx + delta
        while 0 <= i < n:
            child = self.children[i]
            if isinstance(child, BodyRow):
                i += delta
                continue
            self.set_cursor(i)
            return

    def activate(self) -> None:
        self.post_message(self.Activated(self, self._cursor_index))


class FeedPickRow(_Row):
    DEFAULT_CSS = """
    FeedPickRow { height: 1; padding: 0 1; }
    FeedPickRow.cursor { background: #1e6fff; color: white; }
    """

    def __init__(self, feed: Feed | None) -> None:
        self.feed = feed
        if feed is None:
            label = "[b]· all feeds ·[/]"
        else:
            color = tag_color_for_feed(feed)
            tag = feed_tag(feed)
            label = f"[black on {color}] {tag} [/] [b]{feed.name}[/]"
        super().__init__(label, markup=True)
