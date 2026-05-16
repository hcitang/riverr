"""Stdlib `logging` wiring for riverr.

One root handler, one rotating file at `<state_dir>/riverr.log`. Off by
default. Controlled by:
  - `[logging] level` in settings.toml (one of: off, debug, info, warning, error)
  - `[logging] file` in settings.toml (path override; optional)
  - `--debug` CLI flag (one-shot override → DEBUG)
  - `RIVERR_DEBUG=1` env var (back-compat fallback → DEBUG, only when
    no explicit `--debug` and settings level is "off")

All output goes to the file (NOT stdout/stderr — Textual would render over it).
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "error": logging.ERROR,
}

# Sentinel level that suppresses all output (above CRITICAL).
_OFF = logging.CRITICAL + 1

_CONFIGURED = False
_LOG_FORMAT = "%(asctime)s %(levelname)-5s %(name)s: %(message)s"
_ROOT_NAME = "riverr"


def _resolve_level(level: Optional[str]) -> int:
    if level is None:
        # Read from settings, with back-compat env-var fallback.
        try:
            from . import settings as settings_mod
            level = str(settings_mod.get("logging.level", "off"))
        except Exception:
            level = "off"
        if level.lower() == "off" and os.environ.get("RIVERR_DEBUG") == "1":
            level = "debug"
    lv = (level or "off").lower()
    if lv == "off":
        return _OFF
    return _LEVELS.get(lv, _OFF)


def _resolve_file(log_file: Optional[Path]) -> Path:
    if log_file is not None:
        return Path(log_file)
    # Settings override?
    try:
        from . import settings as settings_mod
        configured = settings_mod.get("logging.file", None)
    except Exception:
        configured = None
    if configured:
        return Path(configured).expanduser()
    try:
        from .config import get_paths
        return Path(get_paths().state_dir) / "riverr.log"
    except Exception:
        return Path.home() / ".local" / "share" / "riverr" / "riverr.log"


def configure(level: Optional[str] = None, log_file: Optional[Path] = None) -> None:
    """Idempotent setup of the `riverr` logger. No-op after the first
    successful call (within the process). Pass `level="debug"` from a CLI
    `--debug` flag to override settings for one invocation."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    lvl = _resolve_level(level)
    path = _resolve_file(log_file)
    logger = logging.getLogger(_ROOT_NAME)
    logger.setLevel(lvl)
    # Don't bubble up to the root logger (which may have a StreamHandler).
    logger.propagate = False
    if lvl <= logging.CRITICAL:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                path, maxBytes=512_000, backupCount=3, encoding="utf-8"
            )
            handler.setFormatter(logging.Formatter(_LOG_FORMAT))
            handler.setLevel(lvl)
            logger.addHandler(handler)
        except Exception:
            # If we can't open the file, swallow — logging must never crash
            # the app. The logger stays attached at the configured level
            # with no handler (messages are dropped).
            pass
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the `riverr` namespace. Safe to call
    before `configure()`; messages emitted before configuration are dropped
    (no handler attached yet)."""
    if name == _ROOT_NAME or name.startswith(_ROOT_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT_NAME}.{name}")


# Test-only hook: reset the one-shot guard and tear down handlers.
def _reset_for_tests() -> None:
    global _CONFIGURED
    logger = logging.getLogger(_ROOT_NAME)
    for h in list(logger.handlers):
        try:
            h.close()
        except Exception:
            pass
        logger.removeHandler(h)
    logger.setLevel(logging.NOTSET)
    _CONFIGURED = False
