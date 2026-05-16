from __future__ import annotations

import base64
import io
import os
import re
import sys

import pytest
from PIL import Image as PILImage

from riverr.core import images as imgmod


def _small_png_bytes(w: int = 8, h: int = 8, color: tuple = (255, 0, 0)) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def test_images_make_image_widget_with_kitty(monkeypatch):
    monkeypatch.setenv("RIVERR_FORCE_IMAGE_PROTOCOL", "kitty")
    data = _small_png_bytes()
    w = imgmod.make_image_widget(data)
    assert w is not None
    assert isinstance(w, imgmod.KittyImage)


def test_images_make_image_widget_unsupported(monkeypatch):
    monkeypatch.setenv("RIVERR_FORCE_IMAGE_PROTOCOL", "none")
    data = _small_png_bytes()
    assert imgmod.make_image_widget(data) is None


def test_images_make_image_widget_empty(monkeypatch):
    monkeypatch.setenv("RIVERR_FORCE_IMAGE_PROTOCOL", "kitty")
    assert imgmod.make_image_widget(b"") is None


def test_images_kitty_encode_roundtrip():
    data = _small_png_bytes()
    esc = imgmod._kitty_encode(data, image_id=42, cols=10, rows=5)
    # First chunk header carries the placement controls.
    assert "\x1b_Ga=T,f=100,i=42,m=" in esc
    assert "c=10" in esc
    assert "r=5" in esc
    # Pull out every payload between ; and \x1b\\ and decode.
    chunks = re.findall(r";([A-Za-z0-9+/=]+)\x1b\\", esc)
    assert chunks, "expected at least one base64 payload chunk"
    b64 = "".join(chunks)
    assert base64.standard_b64decode(b64) == data


def test_images_cells_tall_estimate(monkeypatch):
    monkeypatch.delenv("RIVERR_CELL_PX_HEIGHT", raising=False)
    # 100px tall / 20px per cell = 5 cells.
    data = _small_png_bytes(w=10, h=100)
    assert imgmod._estimate_cells_tall(data) == 5
    # Override cell height.
    monkeypatch.setenv("RIVERR_CELL_PX_HEIGHT", "10")
    assert imgmod._estimate_cells_tall(data) == 10
    # Cap at max_cells.
    monkeypatch.delenv("RIVERR_CELL_PX_HEIGHT")
    big = _small_png_bytes(w=10, h=10_000)
    assert imgmod._estimate_cells_tall(big, max_cells=24) == 24


def test_images_kitty_widget_reserves_height(monkeypatch):
    monkeypatch.setenv("RIVERR_FORCE_IMAGE_PROTOCOL", "kitty")
    monkeypatch.setenv("RIVERR_CELL_PX_HEIGHT", "20")
    data = _small_png_bytes(w=40, h=80)  # 80/20 = 4 cells
    w = imgmod.KittyImage(data)
    assert w.cells_tall == 4
    # Height style should be set to cells_tall.
    assert int(w.styles.height.value) == 4


@pytest.mark.asyncio
async def test_images_kitty_widget_emits_escape(monkeypatch, capsys):
    monkeypatch.setenv("RIVERR_FORCE_IMAGE_PROTOCOL", "kitty")
    from textual.app import App, ComposeResult
    from textual.containers import VerticalScroll

    data = _small_png_bytes(w=16, h=16)
    captured: list[str] = []

    # The widget writes to sys.__stdout__ directly to bypass Textual's
    # render loop. Patch it so we can observe what gets emitted.
    class _Sink:
        def write(self, s):
            captured.append(s)
            return len(s)

        def flush(self):
            pass

    monkeypatch.setattr(sys, "__stdout__", _Sink())

    class _ProbeApp(App):
        def compose(self) -> ComposeResult:
            with VerticalScroll():
                yield imgmod.make_image_widget(data)

    app = _ProbeApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()

    blob = "".join(captured)
    assert "\x1b_Ga=T,f=100" in blob, f"expected Kitty header in emitted bytes; got {blob[:200]!r}"
    # At least one emit must round-trip to the original image bytes. The
    # widget may fire on both on_show and on_resize, so split per emit
    # (each starts with the save-cursor sequence \x1b7) and decode each.
    matched = False
    for emit in blob.split("\x1b7"):
        chunks = re.findall(r";([A-Za-z0-9+/=]+)\x1b\\", emit)
        payload = "".join(c for c in chunks if len(c) > 4)
        if not payload:
            continue
        try:
            if base64.standard_b64decode(payload) == data:
                matched = True
                break
        except Exception:
            continue
    assert matched, "no emitted Kitty escape payload decoded back to the input image bytes"
