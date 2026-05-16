"""Tests for the shared RiverrApp base class."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static

from riverr.core.app_base import RiverrApp


class _BareApp(RiverrApp):
    """Minimal subclass — just enough to mount and exercise the base."""

    def compose(self) -> ComposeResult:
        yield Static("", id="status")


def test_feed_reader_app_instantiable(tmp_storage):
    app = _BareApp(storage=tmp_storage)
    assert app.storage is tmp_storage
    assert app.images_enabled in (True, False)
    # default managed actions include the shared set.
    for a in ("refresh", "yank_url", "open_url", "quit", "toggle_images"):
        assert a in app._SIMPLE_ACTIONS


def test_keymap_override_via_keys_toml(tmp_path, monkeypatch, tmp_storage):
    """User remap of quit q->Q must land in the binding mapping for a
    bare subclass that only calls super().__init__."""
    cfg = tmp_path / "config"
    state = tmp_path / "state"
    (cfg / "riverr").mkdir(parents=True)
    (state / "riverr").mkdir(parents=True)
    (cfg / "riverr" / "keys.toml").write_text(
        '[keys]\n'
        'quit = "Q"\n'
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.setenv("XDG_DATA_HOME", str(state))

    app = _BareApp(storage=tmp_storage)
    mapping = app._bindings.key_to_bindings
    assert "Q" in mapping
    assert any(b.action == "quit" for b in mapping["Q"])
    if "q" in mapping:
        assert not any(b.action == "quit" for b in mapping["q"])
