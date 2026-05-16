from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _xdg(env: str, default: Path) -> Path:
    raw = os.environ.get(env)
    return Path(raw).expanduser() if raw else default


@dataclass(frozen=True)
class Paths:
    config_dir: Path
    state_dir: Path

    @property
    def opml(self) -> Path:
        return self.config_dir / "feeds.opml"

    @property
    def keys_toml(self) -> Path:
        return self.config_dir / "keys.toml"

    @property
    def db(self) -> Path:
        return self.state_dir / "state.db"

    @property
    def settings_toml(self) -> Path:
        return self.config_dir / "settings.toml"


def get_paths(root: Path | None = None) -> Paths:
    if root is not None:
        cfg = root / "config"
        state = root / "state"
    else:
        cfg = _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / "riverr"
        state = _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share") / "riverr"
    cfg.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    return Paths(config_dir=cfg, state_dir=state)
