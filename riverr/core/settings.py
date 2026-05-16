"""User-tunable preferences persisted to ~/.config/riverr/settings.toml.

Sections:
  [display]   images_enabled, cell_px_height, clipboard
  [logging]   level
  [behavior]  expanded_j, expanded_k

API: `get("section.key", default)`, `set_("section.key", value)`.
Bare keys (no dot) live in a `[general]` section.

On first read, performs a one-shot migration from the legacy
`settings.json` and from any `[behavior]` block in `keys.toml`.
"""
from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import tomli_w

from .config import get_paths


_DEFAULT_SECTION = "general"


def _split(key: str) -> tuple[str, str]:
    if "." in key:
        sect, _, name = key.partition(".")
        return sect, name
    return _DEFAULT_SECTION, key


def _read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_toml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(data), encoding="utf-8")


def _migrate(toml_path: Path) -> None:
    """One-shot migration of legacy settings.json → settings.toml and
    any [behavior] in keys.toml → settings.toml. Safe to call repeatedly."""
    paths = get_paths()
    changed = False
    data = _read_toml(toml_path)

    # settings.json → [display]
    json_path = paths.config_dir / "settings.json"
    if json_path.exists():
        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        if isinstance(raw, dict):
            disp = data.setdefault("display", {})
            if "images_enabled" in raw and "images_enabled" not in disp:
                disp["images_enabled"] = bool(raw["images_enabled"])
                changed = True
        try:
            json_path.unlink()
        except Exception:
            pass

    # [behavior] in keys.toml → settings.toml [behavior]
    keys_path = paths.keys_toml
    if keys_path.exists():
        try:
            ktext = keys_path.read_text(encoding="utf-8")
            kdata = tomllib.loads(ktext)
        except Exception:
            kdata = None
            ktext = None
        if isinstance(kdata, dict) and isinstance(kdata.get("behavior"), dict):
            beh = data.setdefault("behavior", {})
            for k, v in kdata["behavior"].items():
                if k not in beh:
                    beh[k] = v
                    changed = True
            # strip [behavior] from keys.toml
            try:
                new_kdata = {k: v for k, v in kdata.items() if k != "behavior"}
                _write_toml(keys_path, new_kdata)
            except Exception:
                pass

    if changed:
        _write_toml(toml_path, data)


_MIGRATED_PATHS: set[str] = set()


def _load() -> dict:
    p = get_paths().settings_toml
    key = str(p)
    if key not in _MIGRATED_PATHS:
        try:
            _migrate(p)
        except Exception:
            pass
        _MIGRATED_PATHS.add(key)
    return _read_toml(p)


def _save(data: dict) -> None:
    _write_toml(get_paths().settings_toml, data)


def get(key: str, default: Any = None) -> Any:
    sect, name = _split(key)
    data = _load()
    section = data.get(sect)
    if not isinstance(section, dict):
        return default
    return section.get(name, default)


def set_(key: str, value: Any) -> None:
    sect, name = _split(key)
    data = _load()
    section = data.setdefault(sect, {})
    if not isinstance(section, dict):
        section = {}
        data[sect] = section
    section[name] = value
    _save(data)


# Test-only hook: reset the one-shot migration latch between tests.
def _reset_migration_latch() -> None:
    _MIGRATED_PATHS.clear()


# Back-compat shims (kept so any external callers using the old names
# don't blow up). Not part of the documented API.
def load() -> dict:
    """Flatten current TOML into a single-level dict (legacy callers)."""
    flat: dict = {}
    for sect, body in _load().items():
        if not isinstance(body, dict):
            continue
        if sect == _DEFAULT_SECTION:
            flat.update(body)
        else:
            for k, v in body.items():
                flat[f"{sect}.{k}"] = v
    return flat
