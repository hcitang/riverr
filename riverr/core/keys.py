from __future__ import annotations

import tomllib
from pathlib import Path


DEFAULTS: dict[str, list[str]] = {
    "move_down": ["j", "down"],
    "move_up": ["k", "up"],
    "page_down": ["ctrl+j", "space", "J"],
    "page_up": ["ctrl+k", "ctrl+space", "K", "b"],
    "toggle_images": ["v"],
    "go_top": ["g,g"],
    "go_bottom": ["G"],
    "open": ["enter", "right", "l"],
    "back": ["escape", "left", "h"],
    "refresh": ["ctrl+r", "ctrl+shift+r"],
    "mark_all_read": ["R"],
    "add_feed": ["a"],
    "edit_title": ["e"],
    "cycle_link_next": ["tab"],
    "cycle_link_prev": ["shift+tab"],
    "yank_url": ["y"],
    "open_url": ["o"],
    "filter": ["slash"],
    "search_global": ["question_mark"],
    "quit": ["q"],
    "star": ["s"],
    "mark_unread": ["u"],
    "view_next": ["greater_than_sign"],
    "view_prev": ["less_than_sign"],
}


def load(path: Path | str | None = None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {k: list(v) for k, v in DEFAULTS.items()}
    if path is None:
        return out
    p = Path(path)
    if not p.exists():
        return out
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return out
    user_keys = data.get("keys", data)
    for action, val in user_keys.items():
        if isinstance(val, str):
            out[action] = [val]
        elif isinstance(val, list):
            out[action] = [str(x) for x in val]
    return out


BEHAVIOR_DEFAULTS: dict[str, str] = {
    "expanded_j": "open_next",
    "expanded_k": "close_and_prev",
}

_BEHAVIOR_ALLOWED: dict[str, set[str]] = {
    "expanded_j": {"open_next", "collapse_only"},
    "expanded_k": {"close_and_prev", "collapse_only"},
}


def get_behavior(path: Path | str | None = None) -> dict[str, str]:
    """Load [behavior] from settings.toml; fall back to legacy keys.toml
    [behavior] (auto-migrated on first read); fall back to defaults.

    `path`, when given, is read directly as a legacy keys.toml — used by
    tests that point at a tmpdir keys.toml without going through
    XDG/get_paths.
    """
    out = dict(BEHAVIOR_DEFAULTS)
    # Direct keys.toml path (legacy / test): read it.
    if path is not None:
        p = Path(path)
        if p.exists():
            try:
                data = tomllib.loads(p.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            section = data.get("behavior", {}) if isinstance(data, dict) else {}
            if isinstance(section, dict):
                for k, v in section.items():
                    if k in _BEHAVIOR_ALLOWED and isinstance(v, str) and v in _BEHAVIOR_ALLOWED[k]:
                        out[k] = v
        return out
    # Default: read from settings.toml [behavior].
    try:
        from . import settings as settings_mod
        for k in BEHAVIOR_DEFAULTS:
            v = settings_mod.get(f"behavior.{k}", None)
            if isinstance(v, str) and v in _BEHAVIOR_ALLOWED.get(k, set()):
                out[k] = v
    except Exception:
        pass
    return out


LABELS: dict[str, str] = {
    "move_down": "Down", "move_up": "Up", "page_down": "Page Down",
    "page_up": "Page Up", "open": "Open", "back": "Back",
    "refresh": "Refresh", "mark_all_read": "Mark all read",
    "filter": "Filter", "search_global": "Search",
    "yank_url": "Yank", "open_url": "Open URL", "quit": "Quit",
    "cycle_link_next": "Next link", "cycle_link_prev": "Prev link",
    "add_feed": "Add feed", "edit_title": "Edit title",
    "go_top": "Top", "go_bottom": "Bottom",
    "star": "Star", "mark_unread": "Mark unread",
    "view_next": "Next view", "view_prev": "Prev view",
    "toggle_images": "Images",
}


def textual_bindings(keymap: dict[str, list[str]] | None = None) -> list[tuple[str, str, str]]:
    """Return Textual Binding tuples for an App.BINDINGS list."""
    km = keymap or DEFAULTS
    pairs: list[tuple[str, str, str]] = []
    for action, keys in km.items():
        for k in keys:
            # textual uses comma as separator, so skip chord defaults like g,g
            if "," in k:
                continue
            pairs.append((k, action, LABELS.get(action, action)))
    return pairs


def bindings_for(
    actions: list[str],
    action_map: dict[str, str] | None = None,
    keymap: dict[str, list[str]] | None = None,
    path: "Path | str | None" = None,
) -> list[tuple[str, str, str]]:
    """Build Textual binding tuples for a specific list of actions.

    actions:    action names to include (e.g. ["move_down","quit"]).
    action_map: optional mapping from keymap action name → Textual action name
                (defaults to action_<name>). E.g. {"open": "open"} stays as
                "open" which Textual will dispatch to action_open.
    keymap:     pre-loaded keymap; if None, load (optionally from path).
    """
    km = keymap if keymap is not None else load(path)
    out: list[tuple[str, str, str]] = []
    for action in actions:
        keys = km.get(action, [])
        action_name = (action_map or {}).get(action, action)
        for k in keys:
            if "," in k:
                continue
            out.append((k, action_name, LABELS.get(action, action)))
    return out


def build_bindings(
    actions: list[str],
    action_map: dict[str, str] | None = None,
    path: "Path | str | None" = None,
) -> list[tuple[str, str, str]]:
    """Convenience: load keymap from default config path (or `path`) and
    build bindings for the given actions. Called at class-definition time."""
    from .config import get_paths
    if path is None:
        try:
            p = get_paths().keys_toml
            path = p if p.exists() else None
        except Exception:
            path = None
    return bindings_for(actions, action_map=action_map, path=path)
