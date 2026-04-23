"""Skia bundling smoke test — Day 12 milestone for the Option D path.

Run this AFTER building the Nuitka onefile exe to confirm skia-python
survives the bundling. Expected output:

    [OK] skia importable
    [OK] CanvasSkia instantiable
    [OK] Surface allocable
    [OK] Font loaded
    [OK] DropShadow filter built
    [OK] PNG encode
    [OK] all 9 shape kinds render
    bundle OK — size delta: +45 MB

Usage (after building dist/DoxyEdit.exe):
    py tools/skia_build_smoke.py
    # Or run inside the bundled Python by invoking the exe with an
    # entry-point that calls this module (see --run-skia-smoke flag
    # proposed below).

Exit code 0 on success, non-zero on any failure. Wire into CI once
the build has a dedicated step.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def check(name: str, fn):
    try:
        fn()
        print(f"[OK] {name}")
    except Exception as e:
        print(f"[FAIL] {name}: {e}")
        sys.exit(1)


def _import_skia():
    import skia  # noqa: F401


def _import_canvas_skia():
    # Allow running from repo root without installing.
    here = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(here))
    from doxyedit.canvas_skia import CanvasSkia, skia_available
    if not skia_available():
        raise RuntimeError("skia_available() returned False")


def _alloc_surface():
    import skia
    info = skia.ImageInfo.Make(
        256, 256,
        skia.ColorType.kRGBA_8888_ColorType,
        skia.AlphaType.kPremul_AlphaType,
    )
    s = skia.Surface.MakeRaster(info)
    if s is None:
        raise RuntimeError("MakeRaster returned None")
    c = s.getCanvas()
    c.clear(skia.ColorWHITE)
    paint = skia.Paint()
    paint.setColor(skia.ColorRED)
    c.drawRect(skia.Rect.MakeXYWH(10, 10, 100, 50), paint)
    img = s.makeImageSnapshot()
    if img is None:
        raise RuntimeError("makeImageSnapshot returned None")


def _load_font():
    import skia
    typeface = skia.Typeface("Consolas")
    if typeface is None:
        raise RuntimeError("no typeface")
    font = skia.Font(typeface, 14)
    if font.getSize() < 1:
        raise RuntimeError("font size wrong")


def _drop_shadow():
    import skia
    f = skia.ImageFilters.DropShadow(2, 2, 3, 3,
                                      skia.Color(0, 0, 0, 200), None)
    if f is None:
        raise RuntimeError("DropShadow returned None")


def _png_encode():
    import skia
    info = skia.ImageInfo.Make(
        16, 16,
        skia.ColorType.kRGBA_8888_ColorType,
        skia.AlphaType.kPremul_AlphaType,
    )
    s = skia.Surface.MakeRaster(info)
    c = s.getCanvas()
    c.clear(skia.ColorBLACK)
    img = s.makeImageSnapshot()
    data = img.encodeToData(skia.EncodedImageFormat.kPNG, 100)
    if data is None or len(bytes(data)) < 50:
        raise RuntimeError("encode produced tiny or empty bytes")


def _all_shape_kinds():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from doxyedit.canvas_skia import CanvasSkia
    from doxyedit.models import CanvasOverlay
    c = CanvasSkia()
    kinds = ("rect", "ellipse", "star", "polygon", "burst",
             "speech_bubble", "thought_bubble", "gradient_linear",
             "gradient_radial")
    for k in kinds:
        c.add_overlay(CanvasOverlay(
            type="shape", shape_kind=k, shape_w=60, shape_h=40,
            x=10, y=10,
            fill_color="#ff0000", stroke_color="#000000",
            stroke_width=2,
            gradient_start_color="#000000",
            gradient_end_color="#ffffff",
        ))
    c._render_to_skia()


def main() -> int:
    check("skia importable", _import_skia)
    check("CanvasSkia instantiable", _import_canvas_skia)
    check("Surface allocable", _alloc_surface)
    check("Font loaded", _load_font)
    check("DropShadow filter built", _drop_shadow)
    check("PNG encode", _png_encode)
    check("all 9 shape kinds render", _all_shape_kinds)
    # Bundle size check — only meaningful when run against the onefile
    # exe's embedded Python, not a dev Python install. Skip silently
    # otherwise.
    exe_path = os.environ.get("NUITKA_ONEFILE_PARENT", "")
    if exe_path and Path(exe_path).exists():
        size_mb = Path(exe_path).stat().st_size / (1024 * 1024)
        print(f"bundle size: {size_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
