"""EditFeedScreen modal — 3-field per-feed editor (title / abbrev / color)."""
from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label

from riverr.core.logging import get_logger
from riverr.core.storage import Feed


log = get_logger(__name__)


class EditFeedScreen(ModalScreen[tuple[str, str, str] | None]):
    """Three-field modal per MODAL_SPEC.md.

    Layout:
        title line
        for each field:
            Label (field name)
            Horizontal: marker Label ("▶ ") + Input
        help footer

    Marker visibility is toggled via the `.on` CSS class — only the focused
    row's marker is visible. We deliberately do NOT override the Input's
    own `border` (doing so previously collapsed the input to zero height);
    instead we tint background + add a coloured border *only on :focus*.
    """

    DEFAULT_CSS = """
    EditFeedScreen { align: center middle; }
    #edit-box {
        width: 64; height: auto; padding: 1 2;
        border: round $primary; background: $panel;
    }
    #edit-title-line { height: 1; margin-bottom: 1; color: $text; }
    .field-block { height: 5; width: 100%; layout: vertical; }
    .field-block Label.field-label { height: 1; margin: 0; color: $text-muted; }
    .field-block Label.field-label.on { color: #1e6fff; }
    .field-block Input { height: 3; width: 100%; }
    .field-block Input:focus { background: #1e6fff 20%; }
    #edit-help { color: $text-muted; height: 1; margin-top: 1; text-align: center; }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    _FIELDS = (
        ("edit-title",  "Display title:"),
        ("edit-abbrev", "3-char abbreviation:"),
        ("edit-color",  "Color (optional, #RRGGBB):"),
    )

    def __init__(self, feed: Feed) -> None:
        super().__init__()
        self.feed = feed

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-box"):
            yield Label(f"[b]Edit feed: {self.feed.name}[/]", id="edit-title-line")

            with Vertical(classes="field-block"):
                yield Label("  Display title:", classes="field-label", id="label-title")
                yield Input(
                    value=self.feed.display_title or self.feed.title,
                    placeholder="display title",
                    id="edit-title",
                )

            with Vertical(classes="field-block"):
                yield Label("  3-char abbreviation:", classes="field-label", id="label-abbrev")
                yield Input(
                    value=self.feed.abbrev or "",
                    placeholder="abc",
                    max_length=3,
                    id="edit-abbrev",
                )

            with Vertical(classes="field-block"):
                yield Label("  Color (optional, #RRGGBB):", classes="field-label", id="label-color")
                yield Input(
                    value=self.feed.color or "",
                    placeholder="#1e6fff",
                    max_length=7,
                    id="edit-color",
                )

            yield Label(
                "Tab: next field   Enter: save   Esc: cancel",
                id="edit-help",
            )

    def on_mount(self) -> None:
        def _focus() -> None:
            try:
                inp = self.query_one("#edit-title", Input)
                self.set_focus(inp)
                self._update_markers("edit-title")
            except Exception:
                pass
        self.call_after_refresh(_focus)

    def _update_markers(self, focused_id: str | None) -> None:
        for fid, label_text in self._FIELDS:
            label_id = "label-" + fid.split("-")[1]
            try:
                lbl = self.query_one(f"#{label_id}", Label)
            except Exception:
                continue
            prefix = "▶ " if fid == focused_id else "  "
            lbl.update(prefix + label_text)
            if fid == focused_id:
                lbl.add_class("on")
            else:
                lbl.remove_class("on")

    def on_descendant_focus(self, event) -> None:  # noqa: ANN001
        node = getattr(event, "widget", None)
        node_id = getattr(node, "id", None)
        if node_id in (fid for fid, _ in self._FIELDS):
            self._update_markers(node_id)

    def on_key(self, event) -> None:  # noqa: ANN001
        log.debug("edit modal key: %r focused=%r", event.key, self.app.focused)

    @on(Input.Submitted)
    def _submit(self, event: Input.Submitted) -> None:
        title = self.query_one("#edit-title", Input).value.strip()
        abbrev = self.query_one("#edit-abbrev", Input).value.strip()
        color = self.query_one("#edit-color", Input).value.strip()
        self.dismiss((title, abbrev, color))

    def action_cancel(self) -> None:
        self.dismiss(None)
