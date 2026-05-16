from __future__ import annotations

import base64
import math
import os
import sys
from io import BytesIO
from typing import Optional

import httpx

from textual.widgets import Static

from .logging import get_logger


log = get_logger(__name__)

# In-process cache: url -> bytes
_IMAGE_CACHE: dict[str, bytes] = {}

# Monotonic id source for Kitty image placement ids. Lets us avoid
# accidentally re-using ids across widgets.
_NEXT_IMAGE_ID = 1


def _forced_protocol() -> str | None:
    """Test/dev hook: RIVERR_FORCE_IMAGE_PROTOCOL=kitty|iterm|none."""
    val = os.environ.get("RIVERR_FORCE_IMAGE_PROTOCOL", "").lower().strip()
    return val or None


def supports_kitty_graphics() -> bool:
    forced = _forced_protocol()
    if forced is not None:
        return forced == "kitty"
    term = (os.environ.get("TERM") or "").lower()
    term_program = (os.environ.get("TERM_PROGRAM") or "").lower()
    if "kitty" in term or "ghostty" in term:
        return True
    if "ghostty" in term_program or "kitty" in term_program:
        return True
    if os.environ.get("KITTY_WINDOW_ID"):
        return True
    return False


def supports_iterm_graphics() -> bool:
    forced = _forced_protocol()
    if forced is not None:
        return forced == "iterm"
    return os.environ.get("TERM_PROGRAM") == "iTerm.app"


def supports_inline_images() -> bool:
    forced = _forced_protocol()
    if forced == "none":
        return False
    return supports_kitty_graphics() or supports_iterm_graphics()


def image_placeholder(alt: str, src: str) -> str:
    if alt:
        return f"[image: {alt}]"
    return f"[image: {src}]"


def get_cached(url: str) -> Optional[bytes]:
    return _IMAGE_CACHE.get(url)


def cache_image(url: str, data: bytes) -> None:
    _IMAGE_CACHE[url] = data


async def fetch_image(
    url: str,
    transport: httpx.BaseTransport | None = None,
) -> Optional[bytes]:
    if url in _IMAGE_CACHE:
        return _IMAGE_CACHE[url]
    try:
        from .fetch import fetch_url_bytes
        status, data, _ = await fetch_url_bytes(url, transport=transport)
        if status < 400 and data:
            _IMAGE_CACHE[url] = data
            log.debug("fetched %s bytes=%d", url, len(data))
            return data
        log.warning("fetch failed %s status=%s", url, status)
    except Exception as e:
        log.warning("fetch raised %s: %r", url, e)
        return None
    return None


def _cell_px_height() -> int:
    env = os.environ.get("RIVERR_CELL_PX_HEIGHT")
    if env is not None:
        try:
            return max(4, int(env))
        except ValueError:
            return 20
    try:
        from . import settings as settings_mod
        val = settings_mod.get("display.cell_px_height", 20)
        return max(4, int(val))
    except Exception:
        return 20


def _estimate_cells_tall(data: bytes, max_cells: int = 24) -> int:
    """Estimate how many terminal rows the image will occupy. Uses Pillow
    if available; falls back to a sensible default."""
    try:
        from PIL import Image as PILImage
        with PILImage.open(BytesIO(data)) as img:
            _, px_h = img.size
    except Exception:
        return min(max_cells, 12)
    cells = max(1, math.ceil(px_h / _cell_px_height()))
    return min(max_cells, cells)


def _image_dims(data: bytes) -> tuple[int, int] | None:
    try:
        from PIL import Image as PILImage
        with PILImage.open(BytesIO(data)) as img:
            return img.size
    except Exception:
        return None


def _kitty_encode(
    data: bytes,
    image_id: int,
    cols: int | None = None,
    rows: int | None = None,
) -> str:
    """Build the Kitty graphics escape sequence (a=T transmit-and-display).

    Same chunked base64 protocol as cli.cmd_image_test. The first chunk
    carries the format/placement controls; subsequent chunks just stream
    the rest of the payload with `m=` continuation flag.
    """
    b64 = base64.standard_b64encode(data).decode("ascii")
    chunks = [b64[i : i + 4096] for i in range(0, len(b64), 4096)]
    if not chunks:
        return ""
    parts: list[str] = []
    n = len(chunks)
    for i, chunk in enumerate(chunks):
        m = 1 if i < n - 1 else 0
        if i == 0:
            ctrl = [f"a=T", f"f=100", f"i={image_id}", f"m={m}"]
            if cols and cols > 0:
                ctrl.append(f"c={cols}")
            if rows and rows > 0:
                ctrl.append(f"r={rows}")
            parts.append(f"\x1b_G{','.join(ctrl)};{chunk}\x1b\\")
        else:
            parts.append(f"\x1b_Gm={m};{chunk}\x1b\\")
    return "".join(parts)


def _kitty_delete(image_id: int) -> str:
    """Delete an image placement by id (a=d, d=i)."""
    return f"\x1b_Ga=d,d=i,i={image_id};\x1b\\"


class KittyImage(Static):
    """A Textual widget that paints an image via the Kitty graphics
    protocol by writing escape sequences directly to the terminal,
    bypassing Textual's render loop.

    Why bypass: Textual takes whatever a widget renders, runs it through
    Rich's renderer, and emits cells. Arbitrary escape sequences in
    rendered text get eaten / re-encoded. Instead we render an invisible
    placeholder that just reserves N cells of vertical space, then move
    the cursor over our region and write the Kitty escape ourselves.
    """

    DEFAULT_CSS = """
    KittyImage { height: auto; width: 1fr; }
    """

    def __init__(self, data: bytes, max_cells: int = 24) -> None:
        global _NEXT_IMAGE_ID
        super().__init__("")
        self._image_data = data
        self._cells_tall = _estimate_cells_tall(data, max_cells=max_cells)
        self._image_id = _NEXT_IMAGE_ID
        _NEXT_IMAGE_ID += 1
        self._max_cells = max_cells
        dims = _image_dims(data)
        self._px_size = dims or (0, 0)
        # Pad with newlines so Textual reserves _cells_tall rows for us.
        # Static renders this as blank lines; we paint the image on top.
        self._set_placeholder(self._cells_tall)

    def _set_placeholder(self, cells: int) -> None:
        # `update` keeps width=auto from filling; an explicit space + N-1
        # newlines reserves `cells` lines of height.
        self.update("\n" * max(0, cells - 1) + " ")
        self.styles.height = cells

    @property
    def image_id(self) -> int:
        return self._image_id

    @property
    def cells_tall(self) -> int:
        return self._cells_tall

    def _container_cols(self) -> int:
        try:
            w = self.size.width
        except Exception:
            w = 0
        if not w:
            try:
                w = self.app.size.width
            except Exception:
                w = 80
        return max(4, int(w))

    def _emit_kitty_escape(self) -> None:
        """Write the Kitty graphics escape directly to the terminal.

        Positions the cursor over this widget's region (using ANSI CUP),
        emits the chunked Kitty escape, then restores the cursor. Wrapped
        in DECSC/DECRC (`\\x1b7`/`\\x1b8`) so Textual's next paint cycle
        finds the cursor where it left it.
        """
        try:
            region = self.region
        except Exception:
            return
        if region.width <= 0 or region.height <= 0:
            return
        cols = max(1, region.width)
        rows = max(1, min(region.height, self._cells_tall))
        # ANSI is 1-based; region.x/y are 0-based.
        row1 = region.y + 1
        col1 = region.x + 1
        esc = _kitty_encode(
            self._image_data,
            image_id=self._image_id,
            cols=cols,
            rows=rows,
        )
        if not esc:
            return
        out = sys.__stdout__ or sys.stdout
        try:
            # Save cursor, jump, paint, restore cursor.
            out.write(f"\x1b7\x1b[{row1};{col1}H{esc}\x1b8")
            out.flush()
            log.debug(
                "painted image id=%d at row=%d col=%d cols=%d rows=%d bytes=%d",
                self._image_id, row1, col1, cols, rows, len(self._image_data),
            )
        except Exception as e:
            log.debug("emit_kitty_escape failed: %r", e)

    def _emit_delete(self) -> None:
        out = sys.__stdout__ or sys.stdout
        try:
            out.write(_kitty_delete(self._image_id))
            out.flush()
        except Exception:
            pass

    # Textual lifecycle hooks ------------------------------------------------

    def on_show(self) -> None:
        # First paint: wait until layout has assigned a region.
        self.call_after_refresh(self._emit_kitty_escape)

    def on_resize(self, event) -> None:  # noqa: ANN001
        self.call_after_refresh(self._emit_kitty_escape)

    def on_hide(self) -> None:
        self._emit_delete()

    def on_unmount(self) -> None:
        self._emit_delete()


def make_image_widget(data: bytes):
    """Build an image widget from raw bytes, or return None when this
    terminal can't render inline images. Returns a `KittyImage` on
    Kitty/Ghostty (or when RIVERR_FORCE_IMAGE_PROTOCOL=kitty).

    TODO: iTerm and sixel paths are out of scope here; they currently
    fall through to None (caller uses the text placeholder).
    """
    if not data:
        return None
    if supports_kitty_graphics():
        try:
            w = KittyImage(data)
            log.debug("made KittyImage cells=%d px=%r", w.cells_tall, w._px_size)
            return w
        except Exception as e:
            log.debug("KittyImage construction failed: %r", e)
            return None
    return None
