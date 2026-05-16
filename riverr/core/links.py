from __future__ import annotations

import base64
import os
import subprocess
import sys


def open_url(url: str) -> bool:
    if not url:
        return False
    try:
        subprocess.run(["open", url], check=False)
        return True
    except FileNotFoundError:
        return False


def _clipboard_mode() -> str:
    """Resolve clipboard backend. Env var overrides settings for tests /
    back-compat; settings.toml [display].clipboard is the primary source.
    """
    env = os.environ.get("RIVERR_CLIPBOARD")
    if env:
        return env
    try:
        from . import settings as settings_mod
        v = settings_mod.get("display.clipboard", "osc52")
        return str(v) if v else "osc52"
    except Exception:
        return "osc52"


def copy_url(url: str) -> bool:
    """Copy `url` to the clipboard.

    Default path emits an OSC 52 escape to stdout — works on Ghostty,
    iTerm, and inside tmux (when `set -g set-clipboard on`). Set
    `[display] clipboard = "pbcopy"` in settings.toml (or
    `RIVERR_CLIPBOARD=pbcopy` as a one-shot override) to force the
    legacy pbcopy subprocess.
    """
    if not url:
        return False
    if _clipboard_mode() == "pbcopy":
        try:
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            p.communicate(url.encode("utf-8"))
            return p.returncode == 0
        except FileNotFoundError:
            return False
    try:
        b64 = base64.b64encode(url.encode("utf-8")).decode("ascii")
        seq = f"\x1b]52;c;{b64}\x07"
        sys.stdout.write(seq)
        sys.stdout.flush()
        return True
    except Exception:
        return False


def truncate_middle(url: str, width: int, left: int = 25, right: int = 15) -> str:
    """Middle-ellipsis truncate `url` to fit in `width` columns.

    Keeps the first `left` and last `right` chars with `…` between.
    If `width` is wide enough for the whole string, return it unchanged.
    """
    if url is None:
        return ""
    if width <= 0:
        return ""
    if len(url) <= width:
        return url
    # need at least left + 1 (ellipsis) + right chars; clamp to width
    keep = max(0, width - 1)
    if keep <= left + right:
        # rescale proportionally so we still respect width
        l = max(1, keep * left // (left + right))
        r = max(1, keep - l)
        return url[:l] + "…" + url[-r:]
    return url[:left] + "…" + url[-right:]
