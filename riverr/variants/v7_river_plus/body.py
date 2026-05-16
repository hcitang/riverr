"""BodyRow — the expanded-article container with inline image support."""
from __future__ import annotations

import httpx
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from riverr.core import images as imgmod
from riverr.core.extract import is_stub
from riverr.core.links import truncate_middle
from riverr.core.logging import get_logger
from riverr.core.render import (
    Heading,
    Image as ImageNode,
    _render_block,
    item_body_to_ast,
)
from riverr.core.storage import Item

from .behavior import _SOURCE_LABELS
from .style import _norm_title, _strip_trailing_blanklines


log = get_logger(__name__)


class BodyRow(Vertical):
    """Expanded article container. Hosts a VerticalScroll of mixed
    Static (text blocks) and Image (image blocks) widgets so that images
    render inline interleaved with text on supporting terminals.

    Sizes its own height to the remaining viewport — the app sets this
    when the row is expanded and on resize.
    """

    DEFAULT_CSS = """
    BodyRow { height: 20; background: $boost; padding: 1 1 0 4; }
    BodyRow #body-scroll { height: 1fr; }
    BodyRow #body-scroll > * { margin-bottom: 1; margin-right: 2; }
    """

    def __init__(
        self,
        item: Item,
        owner,  # RiverRow — typed loosely to avoid circular import
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.item = item
        self.owner = owner
        self.link_targets: list[str] = []
        self.link_cursor: int = -1
        self.transport = transport
        super().__init__()
        self.add_class("body-row")

    def compose(self) -> ComposeResult:
        self.scroll = VerticalScroll(id="body-scroll")
        yield self.scroll

    def render_body(self) -> None:
        for child in list(self.scroll.children):
            try:
                child.remove()
            except Exception:
                pass
        it = self.item
        head = Text()
        if it.title:
            head.append(it.title + "\n", style="bold underline bright_white")
        if it.author:
            head.append(f"by {it.author}\n", style="dim italic")
        src_key = getattr(it, "body_source", "legacy") or "legacy"
        fmt_key = getattr(it, "body_format", "html") or "html"
        src_label = _SOURCE_LABELS.get(src_key, src_key)
        head.append(
            f"[source: {src_label} · {fmt_key}]", style="dim italic"
        )
        head.append("\n", style="dim")
        if it.link:
            try:
                width = max(20, (self.size.width or 80) - 4)
            except Exception:
                width = 80
            head.append(truncate_middle(it.link, width) + "\n", style="dim blue")
        head = _strip_trailing_blanklines(head)
        self.scroll.mount(Static(head, classes="body-header"))

        if not it.extracted_body and is_stub(it):
            self.scroll.mount(Static(Text("Extracting…", style="italic dim")))
            return

        doc = item_body_to_ast(it)
        self.link_targets = []
        self.link_cursor = -1
        blocks = list(doc.children)
        if blocks and isinstance(blocks[0], Heading):
            head_text = Text()
            _render_block(blocks[0], head_text, [], depth=0)
            if _norm_title(head_text.plain) == _norm_title(it.title or ""):
                blocks = blocks[1:]
        for block in blocks:
            self._mount_block(block)

        if self.link_targets:
            out = Text()
            out.append("\nLinks:\n", style="bold dim")
            for i, href in enumerate(self.link_targets, 1):
                out.append(f"  [{i}] {href}\n", style="dim blue")
            self.scroll.mount(Static(out))

    def _mount_block(self, block) -> None:
        images = self._collect_images(block)
        if not images:
            text = Text()
            _render_block(block, text, self.link_targets, depth=0)
            text = _strip_trailing_blanklines(text)
            if text.plain.strip():
                self.scroll.mount(Static(text))
            return
        text = Text()
        _render_block(block, text, self.link_targets, depth=0)
        text = _strip_trailing_blanklines(text)
        if text.plain.strip():
            self.scroll.mount(Static(text))
        for src, alt in images:
            placeholder = Static(Text(
                f"[image: {alt or src}]",
                style="italic magenta dim" if imgmod.supports_inline_images()
                      else "italic magenta",
            ))
            self.scroll.mount(placeholder)
            log.debug(
                "placeholder mounted src=%r alt=%r inline_supported=%s",
                src, alt, imgmod.supports_inline_images(),
            )
            images_on = getattr(self.app, "images_enabled", True)
            if imgmod.supports_inline_images() and images_on:
                self._fetch_and_mount_image(src, alt, placeholder)

    def _collect_images(self, block) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []

        def walk(n):
            if isinstance(n, ImageNode):
                found.append((n.src, n.alt))
                return
            for attr in ("children", "items"):
                kids = getattr(n, attr, None)
                if kids:
                    for k in kids:
                        walk(k)

        walk(block)
        return found

    @work(exclusive=False, group="images")
    async def _fetch_and_mount_image(
        self, src: str, alt: str, placeholder: Static
    ) -> None:
        if not src:
            return
        data = await imgmod.fetch_image(src, transport=self.transport)
        if not data:
            log.warning("image fetch failed src=%r", src)
            self._mark_placeholder_failed(placeholder, alt or src, "fetch")
            return
        widget = imgmod.make_image_widget(data)
        if widget is None:
            log.debug("make_image_widget returned None src=%r", src)
            self._mark_placeholder_failed(placeholder, alt or src, "decode")
            return
        siblings = list(self.scroll.children)
        try:
            ph_idx = siblings.index(placeholder)
        except ValueError:
            ph_idx = -1
        next_sibling = (
            siblings[ph_idx + 1] if 0 <= ph_idx < len(siblings) - 1 else None
        )
        try:
            if next_sibling is not None:
                await self.scroll.mount(widget, before=next_sibling)
            else:
                await self.scroll.mount(widget)
            try:
                await placeholder.remove()
            except Exception:
                pass
            log.debug("image mounted src=%r bytes=%d", src, len(data))
        except Exception as e:
            log.warning("mount image raised src=%r: %r", src, e)
            self._mark_placeholder_failed(placeholder, alt or src, "mount")

    def _mark_placeholder_failed(self, placeholder: Static, label: str, why: str) -> None:
        try:
            placeholder.update(Text(
                f"[image: failed to load ({why}): {label}]",
                style="italic red",
            ))
        except Exception:
            pass

    def highlight_link(self, idx: int) -> str | None:
        if not self.link_targets:
            return None
        self.link_cursor = idx % len(self.link_targets)
        return self.link_targets[self.link_cursor]
