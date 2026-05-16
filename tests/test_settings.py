from __future__ import annotations

import json

import pytest

from riverr.core import settings as settings_mod
from riverr.core.config import get_paths


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    state = tmp_path / "state"
    cfg.mkdir()
    state.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.setenv("XDG_DATA_HOME", str(state))
    settings_mod._reset_migration_latch()
    yield get_paths()
    settings_mod._reset_migration_latch()


def test_get_missing_returns_default(isolated_config):
    assert settings_mod.get("display.images_enabled", True) is True
    assert settings_mod.get("display.cell_px_height", 20) == 20
    assert settings_mod.get("nope.also_nope", "fallback") == "fallback"


def test_set_then_get_dotted(isolated_config):
    settings_mod.set_("display.images_enabled", False)
    assert settings_mod.get("display.images_enabled", True) is False
    settings_mod.set_("display.cell_px_height", 32)
    assert settings_mod.get("display.cell_px_height", 0) == 32


def test_round_trip_persists_to_toml(isolated_config):
    settings_mod.set_("display.clipboard", "pbcopy")
    p = isolated_config.settings_toml
    assert p.exists()
    text = p.read_text()
    assert "[display]" in text
    assert 'clipboard = "pbcopy"' in text


def test_bare_key_uses_general_section(isolated_config):
    settings_mod.set_("foo", "bar")
    assert settings_mod.get("foo", None) == "bar"
    text = isolated_config.settings_toml.read_text()
    assert "[general]" in text


def test_migration_from_settings_json(isolated_config):
    paths = isolated_config
    json_path = paths.config_dir / "settings.json"
    json_path.write_text(json.dumps({"images_enabled": False}))
    settings_mod._reset_migration_latch()
    # Trigger a load by querying.
    assert settings_mod.get("display.images_enabled", True) is False
    # JSON gone; TOML present with [display].
    assert not json_path.exists()
    toml_path = paths.settings_toml
    assert toml_path.exists()
    assert "images_enabled = false" in toml_path.read_text()


def test_migration_from_keys_toml_behavior(isolated_config):
    paths = isolated_config
    paths.keys_toml.write_text(
        '[keys]\nquit = "Q"\n'
        '[behavior]\nexpanded_j = "collapse_only"\n'
    )
    settings_mod._reset_migration_latch()
    assert settings_mod.get("behavior.expanded_j", None) == "collapse_only"
    # [behavior] stripped from keys.toml.
    assert "[behavior]" not in paths.keys_toml.read_text()
    assert '"Q"' in paths.keys_toml.read_text()
