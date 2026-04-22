"""Generate a baked-PNG design manifest for DoxyEdit.

Captures every major view / panel / dialog at the actual pixel layout
Qt produces, then composes them into a single manifest PNG and dumps
every theme's token values to JSON for implementation reference.

Output layout:
    design_mockups/
        tokens.json                  full Theme dataclass dump, all themes
        manifest_default.png         grid of all captures under default theme
        variants/
            <theme_id>/
                <component>.png      per-component capture
                components.json      per-component metadata (pos + token refs)

Run:
    python tools/design_manifest.py

Headless: uses offscreen QPA so the user's desktop never sees the
main window pop up during rendering.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, fields
from pathlib import Path

# Use offscreen platform so nothing pops onto the user's desktop.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Keep QSettings reads stable even when running headless
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

from PIL import Image, ImageDraw, ImageFont
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QSize, QTimer, QEventLoop

from doxyedit.themes import THEMES, THEME_GROUPS, DEFAULT_THEME
from doxyedit.window import MainWindow
from doxyedit.imaging import qimage_to_pil


OUT_DIR = REPO_ROOT / "design_mockups"
VARIANTS_DIR = OUT_DIR / "variants"

# Five representative themes spanning the range. One dark + four new-tier
# entries covering bright / medium / warm / cool.
VARIANT_THEMES = [
    "soot",      # default dark
    "candy",     # bright warm pink
    "lavender",  # medium cool purple
    "sunset",    # bright warm peach
    "wine",      # medium warm rose
]

# Window size for captures — large enough to let all panels breathe
CAPTURE_WIDTH = 1600
CAPTURE_HEIGHT = 1000


def _pump_events(ms: int = 100):
    """Let Qt process layout / paint events for ms milliseconds."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _grab_widget(widget, width: int | None = None, height: int | None = None) -> Image.Image:
    """Grab a QWidget as a PIL image. Resizes first if requested."""
    if widget is None:
        return Image.new("RGBA", (200, 60), (255, 0, 255, 255))
    if width or height:
        w = width or widget.width()
        h = height or widget.height()
        widget.resize(w, h)
    _pump_events(80)
    pix = widget.grab()
    return qimage_to_pil(pix.toImage())


def _theme_to_dict(theme) -> dict:
    d = asdict(theme)
    # Drop None / empty defaults for readability — keep actual values
    return {k: v for k, v in d.items() if v not in ("", None)}


def dump_tokens_json(path: Path):
    """Write every theme's Theme dataclass as JSON."""
    out: dict = {
        "_schema": "DoxyEdit theme tokens. Each key is a theme id; "
                   "value is the full Theme dataclass field → value map. "
                   "Token names match doxyedit.themes.Theme field names "
                   "verbatim — use them to style new widgets.",
        "_groups": [{"label": label, "theme_ids": tids} for label, tids in THEME_GROUPS],
        "themes": {tid: _theme_to_dict(theme) for tid, theme in THEMES.items()},
    }
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT)}  ({len(THEMES)} themes)")


def capture_main_window_views(win: MainWindow, theme_id: str, out_dir: Path) -> list[dict]:
    """Capture each top-level tab + key panels. Returns a metadata list."""
    out_dir.mkdir(parents=True, exist_ok=True)
    shots: list[dict] = []

    # Make sure window has laid out at the target size
    win.resize(CAPTURE_WIDTH, CAPTURE_HEIGHT)
    # Show → grab → hide (offscreen platform means nothing is visible anyway)
    win.show()
    _pump_events(250)

    def shot(name: str, widget, description: str, tokens_used: list[str]):
        if widget is None:
            print(f"  [skip] {name} (widget missing)")
            return
        try:
            img = _grab_widget(widget)
            fn = out_dir / f"{name}.png"
            img.save(fn)
            shots.append({
                "name": name,
                "file": fn.name,
                "width": img.width,
                "height": img.height,
                "theme": theme_id,
                "description": description,
                "tokens_used": tokens_used,
            })
            print(f"  [ok]   {name:24s} {img.width}x{img.height}")
        except Exception as e:
            print(f"  [err]  {name}: {e}")

    # Full window
    shot("00_main_window", win,
         "Full main window with default tab (Assets) active.",
         ["bg_deep", "bg_main", "bg_raised", "text_primary", "accent"])

    # Each primary tab
    tabs = getattr(win, "tabs", None)
    if tabs is not None:
        tab_widgets = [
            ("01_tab_assets", getattr(win, "_browse_split", None), "Assets browser + tag panel + info panel",
             ["bg_main", "text_primary", "accent", "border", "thumb_bg"]),
            ("02_tab_studio", getattr(win, "studio", None), "Studio editor (canvas + toolbar + layer panel)",
             ["bg_deep", "studio_*", "accent", "studio_icon_fg"]),
            ("03_tab_social", getattr(win, "_social_split", None), "Social composer + queue",
             ["bg_main", "accent", "composer_status_*", "post_*"]),
            ("04_tab_platforms", getattr(win, "_plat_full", None), "Platform dashboard",
             ["bg_main", "accent", "border"]),
            ("05_tab_overview", getattr(win, "_overview_split", None), "Overview (stats + health + gantt)",
             ["bg_main", "gantt_*", "statusbar_bg"]),
            ("06_tab_notes", getattr(win, "_notes_tabs", None), "Notes markdown editor tabs",
             ["bg_input", "text_primary", "border"]),
        ]
        for name, widget, desc, tokens in tab_widgets:
            if widget is None:
                continue
            # Put the tab up top so lazy-rendered content paints
            try:
                tabs.setCurrentWidget(widget)
            except Exception:
                pass
            _pump_events(150)
            shot(name, widget, desc, tokens)

    # Sub-panels — force Assets tab active so tag/info panel are laid out
    assets_tab = getattr(win, "_browse_split", None)
    if assets_tab is not None and tabs is not None:
        tabs.setCurrentWidget(assets_tab)
        _pump_events(200)
    shot("10_panel_browser", getattr(win, "browser", None),
         "Asset browser grid with thumbnail delegate.",
         ["thumb_bg", "accent", "grid_selection_alpha", "grid_badge_alpha"])
    # Resize tag_panel / info_panel to their natural width before grabbing
    tag_panel = getattr(win, "tag_panel", None)
    if tag_panel is not None and tag_panel.width() < 100:
        tag_panel.resize(280, assets_tab.height() if assets_tab else 800)
        _pump_events(120)
    shot("11_panel_tag", tag_panel,
         "Tag checklist with drag-select + color dots.",
         ["bg_raised", "tag_row_*_alpha", "text_primary", "accent"])
    info_panel = getattr(win, "_info_panel", None)
    if info_panel is not None and info_panel.width() < 100:
        info_panel.resize(300, assets_tab.height() if assets_tab else 800)
        _pump_events(120)
    shot("12_panel_info", info_panel,
         "Info panel — asset metadata, pills, notes.",
         ["bg_raised", "text_primary", "info_section_header color"])
    shot("13_panel_tray", getattr(win, "work_tray", None),
         "Work tray with named sub-trays.",
         ["bg_raised", "accent", "border"])
    # Grab any QToolBar children by iterating — left-side tool palette
    # and the tab bar toolbar both qualify.
    from PySide6.QtWidgets import QToolBar
    for idx, tb in enumerate(win.findChildren(QToolBar)):
        if tb.width() < 10 or tb.height() < 10:
            continue
        shot(f"14_toolbar_{idx}", tb,
             f"Toolbar #{idx} ({tb.objectName() or 'unnamed'}).",
             ["bg_raised", "text_primary", "accent"])
    shot("15_statusbar", win.statusBar(),
         "Status bar with progress + messages.",
         ["statusbar_bg", "statusbar_text"])
    # Main menu bar rendered as a thin capture
    mb = win.menuBar()
    if mb is not None and mb.width() > 0:
        shot("16_menubar", mb, "Application menu bar.",
             ["bg_raised", "text_primary", "accent"])

    _pump_events(80)
    win.hide()
    _pump_events(40)
    return shots


def compose_manifest(theme_id: str, out_dir: Path, theme) -> Image.Image:
    """Tile every per-component PNG into a single annotated manifest image."""
    pngs = sorted(out_dir.glob("*.png"))
    if not pngs:
        return Image.new("RGBA", (400, 100), (80, 80, 80, 255))

    tiles = []
    for p in pngs:
        try:
            img = Image.open(p)
            tiles.append((p.stem, img))
        except Exception:
            continue

    # Grid layout: 2 columns, variable rows
    COLS = 2
    GAP = 24
    LABEL_H = 36

    # Scale tiles to a reasonable max width
    MAX_W = 760
    scaled = []
    for name, img in tiles:
        if img.width > MAX_W:
            ratio = MAX_W / img.width
            new_w = MAX_W
            new_h = int(img.height * ratio)
            img = img.resize((new_w, new_h), Image.LANCZOS)
        scaled.append((name, img))

    # Compute grid dimensions
    rows = (len(scaled) + COLS - 1) // COLS
    col_w = MAX_W + GAP
    row_heights = []
    for r in range(rows):
        r_tiles = scaled[r * COLS:(r + 1) * COLS]
        if r_tiles:
            row_heights.append(max(t[1].height for t in r_tiles) + LABEL_H + GAP)
    total_h = sum(row_heights) + 120  # header
    total_w = col_w * COLS + GAP

    bg = tuple(int(theme.bg_deep.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    fg = tuple(int(theme.text_primary.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    accent_rgb = tuple(int(theme.accent.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    manifest = Image.new("RGBA", (total_w, total_h), bg)
    draw = ImageDraw.Draw(manifest)

    try:
        font_h = ImageFont.truetype("arial.ttf", 28)
        font_s = ImageFont.truetype("arial.ttf", 14)
        font_xs = ImageFont.truetype("arial.ttf", 11)
    except Exception:
        font_h = ImageFont.load_default()
        font_s = ImageFont.load_default()
        font_xs = font_s

    # Title bar
    title = f"DoxyEdit UI Manifest  -  theme: {theme.name}  ({theme_id})"
    draw.text((GAP, 16), title, fill=fg, font=font_h)
    draw.text((GAP, 54), f"bg_main {theme.bg_main}   accent {theme.accent}   "
                         f"text_primary {theme.text_primary}   border {theme.border}",
              fill=accent_rgb, font=font_s)
    draw.text((GAP, 78), f"font: {theme.font_family} @ {theme.font_size}px",
              fill=fg, font=font_s)

    # Tiles
    y = 120
    for r in range(rows):
        x = GAP
        row_slice = scaled[r * COLS:(r + 1) * COLS]
        row_h = max((t[1].height for t in row_slice), default=0) + LABEL_H
        for name, img in row_slice:
            # Component label
            draw.text((x, y), name.replace("_", " "), fill=fg, font=font_s)
            manifest.paste(img, (x, y + 20), img if img.mode == "RGBA" else None)
            # Dimension readout
            draw.text((x, y + 22 + img.height + 4),
                      f"{img.width} x {img.height}",
                      fill=tuple(max(60, c) for c in fg[:3]) + (255,),
                      font=font_xs)
            x += col_w
        y += row_h + GAP

    return manifest


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    VARIANTS_DIR.mkdir(parents=True, exist_ok=True)

    # One-off: dump every theme's tokens to JSON for implementation use
    dump_tokens_json(OUT_DIR / "tokens.json")

    app = QApplication.instance() or QApplication(sys.argv)
    # Don't autoload a project — start blank, we're just capturing chrome
    win = MainWindow(_skip_autoload=True)

    # Walk each variant theme
    for tid in VARIANT_THEMES:
        if tid not in THEMES:
            print(f"[skip] unknown theme {tid}")
            continue
        theme = THEMES[tid]
        print(f"\n=== {theme.name} ({tid}) ===")
        win._apply_theme(tid, persist=False)
        _pump_events(200)

        variant_dir = VARIANTS_DIR / tid
        variant_dir.mkdir(parents=True, exist_ok=True)
        shots = capture_main_window_views(win, tid, variant_dir)

        # Per-variant metadata sidecar
        (variant_dir / "components.json").write_text(
            json.dumps({"theme_id": tid, "theme_name": theme.name,
                         "shots": shots}, indent=2),
            encoding="utf-8")

        # Variant manifest image
        manifest = compose_manifest(tid, variant_dir, theme)
        manifest_path = OUT_DIR / f"manifest_{tid}.png"
        manifest.save(manifest_path)
        print(f"wrote {manifest_path.relative_to(REPO_ROOT)}  "
              f"({manifest.width}x{manifest.height})")

    # Master manifest — side-by-side thumbnails of each variant's manifest
    variant_manifests = [(tid, OUT_DIR / f"manifest_{tid}.png")
                         for tid in VARIANT_THEMES
                         if (OUT_DIR / f"manifest_{tid}.png").exists()]
    if variant_manifests:
        THUMB_W = 700
        thumbs = []
        for tid, path in variant_manifests:
            img = Image.open(path)
            ratio = THUMB_W / img.width
            thumbs.append((tid, img.resize(
                (THUMB_W, int(img.height * ratio)), Image.LANCZOS)))
        GAP = 20
        total_w = (THUMB_W + GAP) * len(thumbs) + GAP
        total_h = max(t[1].height for t in thumbs) + 60
        master_bg = (24, 20, 24, 255)
        master = Image.new("RGBA", (total_w, total_h), master_bg)
        draw = ImageDraw.Draw(master)
        try:
            font_h = ImageFont.truetype("arial.ttf", 20)
        except Exception:
            font_h = ImageFont.load_default()
        x = GAP
        for tid, thumb in thumbs:
            master.paste(thumb, (x, 40), thumb if thumb.mode == "RGBA" else None)
            draw.text((x, 12), f"{THEMES[tid].name} ({tid})",
                      fill=(255, 255, 255, 255), font=font_h)
            x += THUMB_W + GAP
        master_path = OUT_DIR / "manifest_ALL.png"
        master.save(master_path)
        print(f"\nwrote {master_path.relative_to(REPO_ROOT)}  "
              f"({master.width}x{master.height})")

    app.quit()
    print("\nDone.")


if __name__ == "__main__":
    main()
