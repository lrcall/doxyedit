"""Generate 5 UI REDESIGN mockups for DoxyEdit.

These are not theme swatches — they are alternative information
architectures / layouts / visual treatments rendered as annotated
schematics. Use them to pick a direction before committing any code.

Each mockup is a ~1600x1000 PNG annotated with:
    - Region labels (left rail, main content, inspector, ...)
    - Component callouts
    - Token hooks (which Theme field would drive each surface)
    - A one-sentence design thesis at the top

A combined review sheet stacks all 5 plus a thesis summary.

Output:
    design_mockups/redesigns/
        01_dashboard_first.png
        02_gallery_centric.png
        03_command_palette.png
        04_three_column_pro.png
        05_timeline_first.png
        review_sheet.png
        redesigns.json              design thesis + region manifest
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

from doxyedit.themes import THEMES, DEFAULT_THEME  # noqa: E402


OUT_DIR = REPO_ROOT / "design_mockups" / "redesigns"
W, H = 1920, 1200

# Render against the current default theme so mockups look like they
# belong to the same family as the live app
BASE = THEMES[DEFAULT_THEME]


def hx(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def font(size: int, bold: bool = False):
    try:
        name = "arialbd.ttf" if bold else "arial.ttf"
        return ImageFont.truetype(name, size)
    except Exception:
        return ImageFont.load_default()


def new_canvas(bg: str = None) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (W, H), hx(bg or BASE.bg_deep) + (255,))
    return img, ImageDraw.Draw(img)


def header(draw, title: str, thesis: str, accent: str = None):
    draw.rectangle([(0, 0), (W, 90)], fill=hx(BASE.bg_raised) + (255,))
    draw.rectangle([(0, 88), (W, 90)], fill=hx(accent or BASE.accent_bright) + (255,))
    draw.text((32, 14), title, fill=hx(BASE.text_primary) + (255,), font=font(32, bold=True))
    draw.text((32, 52), thesis,
              fill=hx(BASE.text_secondary) + (255,), font=font(16))


def region(draw, x, y, w, h, fill: str, border: str = None,
           label: str = "", label_color: str = None, corner: int = 6,
           *, font_size: int = 14, footnote: str = ""):
    """Fill a rect with optional border + top-left label + bottom-left footnote."""
    draw.rounded_rectangle([(x, y), (x + w, y + h)],
                             fill=hx(fill) + (255,),
                             outline=hx(border or BASE.border) + (255,),
                             width=1, radius=corner)
    if label:
        draw.text((x + 8, y + 6), label,
                  fill=hx(label_color or BASE.text_primary) + (255,),
                  font=font(font_size, bold=True))
    if footnote:
        draw.text((x + 8, y + h - font_size - 8), footnote,
                  fill=hx(BASE.text_muted) + (255,), font=font(11))


def pill(draw, x, y, w, h, text: str, fill: str, text_color: str = None,
         border: str = None):
    draw.rounded_rectangle([(x, y), (x + w, y + h)],
                             fill=hx(fill) + (255,),
                             outline=hx(border) + (255,) if border else None,
                             width=1 if border else 0,
                             radius=h // 2)
    draw.text((x + 10, y + (h - 16) // 2), text,
              fill=hx(text_color or BASE.text_on_accent) + (255,),
              font=font(12, bold=True))


def token_tag(draw, x, y, token: str, color: str = None):
    """Render a small 'TOKEN: theme.name' pill as an implementation hint."""
    t = f"theme.{token}"
    w = 6 + len(t) * 6 + 8
    h = 16
    draw.rounded_rectangle([(x, y), (x + w, y + h)],
                             fill=hx(BASE.bg_input) + (230,),
                             outline=hx(color or BASE.accent_dim) + (255,),
                             width=1, radius=h // 2)
    draw.text((x + 4, y + 1), t,
              fill=hx(color or BASE.accent_bright) + (255,), font=font(10))


def dashed_arrow(draw, x1, y1, x2, y2, color: str = None, label: str = ""):
    color_rgb = hx(color or BASE.accent) + (255,)
    # Simple dashed line
    import math
    dx, dy = x2 - x1, y2 - y1
    dist = max(1, math.hypot(dx, dy))
    step = 8
    nx, ny = dx / dist, dy / dist
    t = 0
    while t < dist:
        sx = x1 + nx * t
        sy = y1 + ny * t
        ex = x1 + nx * min(t + 5, dist)
        ey = y1 + ny * min(t + 5, dist)
        draw.line([(sx, sy), (ex, ey)], fill=color_rgb, width=2)
        t += step
    # Arrowhead
    hx1 = x2 - nx * 12 + ny * 6
    hy1 = y2 - ny * 12 - nx * 6
    hx2 = x2 - nx * 12 - ny * 6
    hy2 = y2 - ny * 12 + nx * 6
    draw.polygon([(x2, y2), (hx1, hy1), (hx2, hy2)], fill=color_rgb)
    if label:
        draw.text(((x1 + x2) / 2 + 6, (y1 + y2) / 2 - 6), label,
                  fill=color_rgb, font=font(11, bold=True))


# ---------------------------------------------------------------------------
# Redesign 01 — Dashboard First
# ---------------------------------------------------------------------------

def render_01_dashboard_first() -> tuple[Image.Image, dict]:
    img, d = new_canvas()
    header(d,
           "Redesign 01  -  Dashboard First",
           "Collapse all tabs into an icon rail. Assets tab becomes a "
           "widget dashboard (recent, queued, alerts, stats, schedule). "
           "Traditional views still accessible via rail, but the default "
           "entrypoint is a synthesis screen, not a file grid.")

    # Left rail (icons only)
    RAIL = 72
    region(d, 0, 90, RAIL, H - 90, BASE.bg_main, label="",
           footnote="icon rail")
    # Stubs for icons
    for i, glyph in enumerate(["A", "S", "T", "P", "O", "N", "C"]):
        cy = 120 + i * 64
        pill(d, 12, cy, 48, 48, glyph, BASE.accent_dim, BASE.text_primary)
    # Settings at bottom
    pill(d, 12, H - 80, 48, 48, "*", BASE.bg_raised, BASE.text_muted)

    # Top strip: search + quick-action
    top_y = 110
    region(d, RAIL + 16, top_y, W - RAIL - 32, 56, BASE.bg_raised,
           label="command / search bar", label_color=BASE.text_secondary)
    pill(d, RAIL + 40, top_y + 12, 700, 32, "Search assets, tags, platforms, people...",
         BASE.bg_input, BASE.text_muted, BASE.border)
    for i, action in enumerate(["+ Queue post", "+ New crop", "+ Tag", "Sync"]):
        pill(d, RAIL + 780 + i * 130, top_y + 12, 120, 32, action,
             BASE.accent, BASE.text_on_accent)

    # Dashboard grid (4x3 widgets)
    grid_y = 186
    cols, rows = 4, 3
    gap = 16
    gw = (W - RAIL - 32 - gap * (cols - 1)) // cols
    gh = (H - grid_y - 32 - gap * (rows - 1)) // rows
    widgets = [
        ("Recently Imported", BASE.bg_raised, "34 assets this week",
         f"theme.bg_raised  theme.accent_bright"),
        ("Scheduled Posts", BASE.bg_raised, "12 queued - 3 today",
         "timeline / gantt_grid"),
        ("Platform Status", BASE.bg_raised, "6 healthy  /  1 error",
         "post_posted / post_failed"),
        ("Alerts", BASE.warning, "2 missing crops  /  1 auth expired",
         "theme.warning"),
        ("Starred", BASE.bg_raised, "88 starred across 4 campaigns",
         "theme.star"),
        ("Top Tags (week)", BASE.bg_raised, "boku, jenni_01, steam",
         "tag_row_active_alpha"),
        ("Campaign: Kickstarter", BASE.bg_raised, "62% ready  -  ends in 8d",
         "gantt_today, accent"),
        ("Campaign: Steam", BASE.bg_raised, "12% ready  -  kickoff Apr 30",
         "gantt_bar_pen_width"),
        ("Oncall Health", BASE.bg_raised, "OneUp OK  -  Playwright OK",
         "success"),
        ("Recent Exports", BASE.bg_raised, "24 PNGs in /dist today",
         "thumb_bg"),
        ("Storage", BASE.bg_raised, "12.4 GB of assets  -  1.8 GB PSDs",
         "text_muted"),
        ("Activity Feed", BASE.bg_raised, "Auto-tagged 41 files at 09:14",
         "text_secondary"),
    ]
    for idx, (title, c, stat, tokens) in enumerate(widgets):
        cc, rr = idx % cols, idx // cols
        wx = RAIL + 16 + cc * (gw + gap)
        wy = grid_y + rr * (gh + gap)
        region(d, wx, wy, gw, gh, c,
               label=title, footnote=stat, font_size=14)
        token_tag(d, wx + 8, wy + gh - 40, tokens.split()[0])
    d.text((RAIL + 16, H - 22), "Traditional tab views still reachable from the left rail.",
           fill=hx(BASE.text_muted) + (255,), font=font(11))
    return img, {
        "title": "Dashboard First",
        "thesis": "Entrypoint is synthesis, not a file grid.",
        "regions": ["icon_rail", "command_bar", "dashboard_widgets"],
        "wins": ["daily-use surface", "alerts surface bugs early",
                  "campaign visibility"],
        "costs": ["new top-level concept (widgets)", "kills familiarity"],
    }


# ---------------------------------------------------------------------------
# Redesign 02 — Gallery-Centric
# ---------------------------------------------------------------------------

def render_02_gallery_centric() -> tuple[Image.Image, dict]:
    img, d = new_canvas()
    header(d,
           "Redesign 02  -  Gallery-Centric",
           "The asset grid fills the viewport. Tag, Info, and Tray panels "
           "become floating summons toggled from a compact top bar. Studio "
           "opens as a modal overlay over the gallery. No tabs at all.")

    # Thin top bar (single strip)
    top = 110
    region(d, 0, 90, W, top - 90, BASE.bg_raised,
           label="top bar — project name | search | summons: tag/info/tray/studio",
           label_color=BASE.text_secondary)
    pill(d, W - 1000, 98, 240, 22, "doxyart.doxyproj.json", BASE.bg_input,
         BASE.text_primary, BASE.border)
    for i, s in enumerate(["Tags", "Info", "Tray", "Studio", "Filters"]):
        pill(d, W - 740 + i * 140, 98, 120, 22, s,
             BASE.accent_dim, BASE.text_primary, BASE.border)

    # HUGE gallery taking whole viewport
    region(d, 0, top, W, H - top, BASE.bg_deep,
           label="asset gallery (occupies full viewport)",
           label_color=BASE.text_secondary)

    # Draw a thumbnail grid
    THUMB = 180
    pad = 14
    gx0, gy0 = 24, top + 60
    cols = (W - gx0 - 24) // (THUMB + pad)
    for i in range(cols * 5):
        cc, rr = i % cols, i // cols
        tx = gx0 + cc * (THUMB + pad)
        ty = gy0 + rr * (THUMB + pad)
        region(d, tx, ty, THUMB, THUMB, BASE.thumb_bg, BASE.border)
        # Status dot
        d.ellipse([(tx + THUMB - 18, ty + 6), (tx + THUMB - 6, ty + 18)],
                   fill=hx([BASE.post_draft, BASE.post_queued,
                            BASE.post_posted, BASE.post_failed][i % 4]) + (255,))
    # Floating info panel as example of summons
    region(d, W - 360, top + 40, 320, 420, BASE.bg_raised, BASE.accent_bright,
           label="(floating) INFO panel - summoned",
           label_color=BASE.accent_bright, footnote="Esc or click-outside to dismiss")
    pill(d, W - 340, top + 90, 80, 22, "boku", BASE.accent_dim, BASE.text_primary)
    pill(d, W - 250, top + 90, 80, 22, "sfw", BASE.accent_dim, BASE.text_primary)
    pill(d, W - 160, top + 90, 80, 22, "sketch", BASE.accent_dim, BASE.text_primary)
    d.text((W - 340, top + 130), "kickstarter", fill=hx(BASE.text_primary) + (255,), font=font(14))
    d.text((W - 340, top + 150), "1080 x 1920  -  3.2 MB", fill=hx(BASE.text_muted) + (255,), font=font(12))
    token_tag(d, W - 340, top + 190, "bg_raised")
    token_tag(d, W - 340, top + 214, "accent_bright")

    dashed_arrow(d, W - 990, 108, W - 220, top + 40, BASE.accent,
                 "click 'Info' to summon")
    return img, {
        "title": "Gallery-Centric",
        "thesis": "Art first; tools are floats.",
        "regions": ["top_bar", "asset_grid", "floating_summons"],
        "wins": ["visual work-focus", "tabs gone", "more assets on screen"],
        "costs": ["summons discoverability", "modal Studio is a shift"],
    }


# ---------------------------------------------------------------------------
# Redesign 03 — Command Palette
# ---------------------------------------------------------------------------

def render_03_command_palette() -> tuple[Image.Image, dict]:
    img, d = new_canvas()
    header(d,
           "Redesign 03  -  Command Palette",
           "VS Code / Alfred style. Minimal chrome. Primary interaction "
           "is keyboard-first via a global command palette (Ctrl+Shift+P). "
           "Every action, view, asset, tag, post is a palette entry.")

    # Thin left rail as breadcrumb
    region(d, 0, 90, W, 40, BASE.bg_raised,
           label="breadcrumb: Assets > Furry > Marty > ComfyUI_44199.png",
           label_color=BASE.text_secondary)

    # Main content: split two-panes with a palette floating
    region(d, 0, 130, W // 2, H - 130, BASE.bg_main,
           label="viewport A  (e.g. asset list)",
           label_color=BASE.text_secondary)
    region(d, W // 2, 130, W // 2, H - 130, BASE.bg_deep,
           label="viewport B  (e.g. asset preview or studio)",
           label_color=BASE.text_secondary)
    # Small indicator that panes can split / swap
    pill(d, W // 2 - 30, 140, 28, 28, "|", BASE.accent, BASE.text_on_accent)

    # The Palette - centered card that dominates
    PX, PY, PW, PH = W // 2 - 400, 220, 800, 520
    region(d, PX, PY, PW, PH, BASE.bg_raised, BASE.accent_bright, corner=14,
           label="command palette (Ctrl+Shift+P)",
           label_color=BASE.accent_bright)
    # Search input
    pill(d, PX + 20, PY + 44, PW - 40, 44, "> queue post...",
         BASE.bg_input, BASE.text_primary, BASE.border)
    # Result rows
    rows = [
        ("Queue Post for Kickstarter", "post  -  Ctrl+Q"),
        ("Queue Post for Patreon", "post"),
        ("Quick Post Everywhere", "post  -  Shift+Q"),
        ("Goto: ComfyUI_44199.png", "asset"),
        ("Tag as: boku", "tag"),
        ("Open Studio for selected", "view  -  S"),
        ("Export All Platforms", "export  -  Shift+E"),
        ("Switch Theme: Lavender", "theme"),
        ("Show Scheduled Posts", "view"),
    ]
    for i, (main, kind) in enumerate(rows):
        ry = PY + 110 + i * 44
        if i == 0:
            d.rectangle([(PX + 12, ry - 4), (PX + PW - 12, ry + 36)],
                          fill=hx(BASE.selection_bg) + (255,))
        d.text((PX + 32, ry + 4), main,
               fill=hx(BASE.text_primary) + (255,), font=font(15, bold=i == 0))
        d.text((PX + PW - 220, ry + 6), kind,
               fill=hx(BASE.text_muted) + (255,), font=font(12))
    # Footer
    d.text((PX + 20, PY + PH - 28), "Enter to run  -  Tab to expand  -  Esc to dismiss",
           fill=hx(BASE.text_muted) + (255,), font=font(11))
    token_tag(d, PX + PW - 260, PY + 14, "accent_bright")
    token_tag(d, PX + PW - 150, PY + 14, "bg_raised")
    return img, {
        "title": "Command Palette",
        "thesis": "Keyboard over chrome.",
        "regions": ["breadcrumb", "viewport_A", "viewport_B", "palette"],
        "wins": ["power users ship fast", "low chrome",
                  "infinite extensibility via commands"],
        "costs": ["poor onboarding for mouse-first users",
                  "requires teaching every action name"],
    }


# ---------------------------------------------------------------------------
# Redesign 04 — Three-Column Pro
# ---------------------------------------------------------------------------

def render_04_three_column_pro() -> tuple[Image.Image, dict]:
    img, d = new_canvas()
    header(d,
           "Redesign 04  -  Three-Column Pro",
           "Adobe Bridge / Lightroom shape. Left: filters + folders + "
           "collections. Center: viewer (grid or detail). Right: "
           "inspector with stacked collapsible panels. All current tabs "
           "become stackable inspector panels you choose to show.")

    COL_L = 280
    COL_R = 360
    center_w = W - COL_L - COL_R

    # Left — filters/folders/collections
    region(d, 0, 90, COL_L, H - 90, BASE.bg_raised,
           label="left - filters / folders / collections",
           label_color=BASE.text_secondary)
    headers = [("FILTERS", ["sfw", "nsfw", "color", "sketch", "final"]),
                ("FOLDERS", ["Furry", "Boku", "Jenni_01", "Peach", "Yacky"]),
                ("COLLECTIONS", ["Kickstarter Pack", "Steam Screens", "Patreon Weekly"])]
    y = 130
    for title, items in headers:
        d.text((14, y), title, fill=hx(BASE.accent_bright) + (255,), font=font(12, bold=True))
        y += 26
        for it in items:
            region(d, 14, y, COL_L - 28, 28, BASE.bg_input, BASE.border,
                   label=it, label_color=BASE.text_primary, font_size=13)
            y += 32
        y += 18

    # Center — viewer (big)
    region(d, COL_L, 90, center_w, H - 90, BASE.bg_deep,
           label="viewer (grid OR detail; user toggles)",
           label_color=BASE.text_secondary)
    # Draw some thumbnails
    THUMB = 160
    pad = 12
    cx0, cy0 = COL_L + 24, 150
    cols = (center_w - 48) // (THUMB + pad)
    for i in range(cols * 4):
        cc, rr = i % cols, i // cols
        tx = cx0 + cc * (THUMB + pad)
        ty = cy0 + rr * (THUMB + pad)
        region(d, tx, ty, THUMB, THUMB, BASE.thumb_bg, BASE.border)

    # Right — stacked inspector
    rx = W - COL_R
    region(d, rx, 90, COL_R, H - 90, BASE.bg_raised,
           label="right - stacked inspector panels",
           label_color=BASE.text_secondary)
    panels = [
        ("METADATA", 120, BASE.bg_main),
        ("TAGS", 100, BASE.bg_main),
        ("PLATFORMS", 140, BASE.bg_main),
        ("HISTORY", 120, BASE.bg_main),
        ("NOTES", 160, BASE.bg_main),
    ]
    py = 130
    for title, ph, c in panels:
        region(d, rx + 10, py, COL_R - 20, ph, c, BASE.border,
               label=f"> {title}", label_color=BASE.accent_bright,
               font_size=13)
        token_tag(d, rx + 20, py + ph - 26, "bg_main")
        py += ph + 10

    # Drag bar hint
    d.line([(COL_L - 2, 90), (COL_L - 2, H)], fill=hx(BASE.accent_dim) + (255,), width=2)
    d.line([(rx + 2, 90), (rx + 2, H)], fill=hx(BASE.accent_dim) + (255,), width=2)
    d.text((COL_L + 8, H - 26),
           "Drag splitters to hide either column. Right panels are collapsible and reorderable.",
           fill=hx(BASE.text_muted) + (255,), font=font(11))
    return img, {
        "title": "Three-Column Pro",
        "thesis": "Familiar to anyone who used Lightroom or Bridge.",
        "regions": ["left_filters_folders", "center_viewer",
                     "right_stacked_inspectors"],
        "wins": ["deep filter UX", "no context switching for metadata",
                  "fits pros muscle memory"],
        "costs": ["right column can feel overloaded",
                  "current tab abstraction goes away"],
    }


# ---------------------------------------------------------------------------
# Redesign 05 — Timeline First
# ---------------------------------------------------------------------------

def render_05_timeline_first() -> tuple[Image.Image, dict]:
    img, d = new_canvas()
    header(d,
           "Redesign 05  -  Timeline First",
           "Every view hangs off a master timeline across the middle of "
           "the window. Assets appear as beads on campaign threads. "
           "Social posts are scheduled stops. Scrub the timeline to "
           "travel in time; panels update in place.")

    # Top — campaign tabs
    region(d, 0, 90, W, 46, BASE.bg_raised,
           label="campaigns (threads): Kickstarter | Steam | Patreon | Merch | Socials-only",
           label_color=BASE.text_secondary)
    for i, name in enumerate(["Kickstarter", "Steam", "Patreon", "Merch", "Socials"]):
        pill(d, 200 + i * 160, 102, 140, 24, name,
             BASE.accent if i == 0 else BASE.bg_input,
             BASE.text_on_accent if i == 0 else BASE.text_secondary, BASE.border)

    # Middle: huge timeline band
    T_Y = 160
    T_H = 320
    region(d, 0, T_Y, W, T_H, BASE.bg_main,
           label="master timeline — scrub anywhere; view below follows",
           label_color=BASE.text_secondary)

    # Day ticks
    for i in range(60):
        x = 30 + i * 32
        if i % 7 == 0:
            d.line([(x, T_Y + 40), (x, T_Y + T_H - 20)],
                     fill=hx(BASE.border) + (255,), width=1)
            d.text((x + 2, T_Y + 28), f"w{i//7+1}", fill=hx(BASE.text_muted) + (255,), font=font(10))
        else:
            d.line([(x, T_Y + 48), (x, T_Y + 56)],
                     fill=hx(BASE.border_light) + (255,), width=1)

    # Threads (campaign rows)
    threads = [
        ("Kickstarter", BASE.accent, [8, 12, 16, 22, 28, 34]),
        ("Steam", BASE.accent_bright, [10, 18, 26, 40]),
        ("Patreon", BASE.gantt_today or BASE.accent, [6, 13, 20, 27, 34, 41]),
        ("Merch", BASE.warning, [14, 24, 44]),
    ]
    for row, (name, c, stops) in enumerate(threads):
        ty = T_Y + 80 + row * 52
        d.text((12, ty + 4), name,
               fill=hx(BASE.text_secondary) + (255,), font=font(12, bold=True))
        d.line([(120, ty + 12), (W - 20, ty + 12)],
                 fill=hx(c) + (255,), width=3)
        for s in stops:
            x = 30 + s * 32
            d.ellipse([(x - 10, ty + 2), (x + 10, ty + 22)],
                       fill=hx(c) + (255,),
                       outline=hx(BASE.bg_deep) + (255,), width=2)

    # "Today" marker
    today_x = 30 + 22 * 32
    d.line([(today_x, T_Y + 20), (today_x, T_Y + T_H - 8)],
             fill=hx(BASE.error) + (255,), width=2)
    d.text((today_x + 4, T_Y + 22), "TODAY",
           fill=hx(BASE.error) + (255,), font=font(11, bold=True))

    # Below timeline — detail pane
    D_Y = T_Y + T_H + 16
    D_H = H - D_Y - 20
    region(d, 0, D_Y, int(W * 0.58), D_H, BASE.bg_raised,
           label="inspector — the bead you clicked (asset, post, or campaign milestone)",
           label_color=BASE.text_secondary)
    d.text((24, D_Y + 40),
           "Clicked bead: 'Kickstarter - Week 3 hero'  -  Apr 27",
           fill=hx(BASE.text_primary) + (255,), font=font(18, bold=True))
    d.text((24, D_Y + 68),
           "Asset: hero_final_kickstarter.psd  -  1920x1080",
           fill=hx(BASE.text_secondary) + (255,), font=font(13))
    pill(d, 24, D_Y + 100, 100, 26, "READY", BASE.success, BASE.text_on_accent)
    pill(d, 134, D_Y + 100, 100, 26, "QUEUED", BASE.post_queued, BASE.text_on_accent)
    region(d, 24, D_Y + 140, int(W * 0.58) - 48, D_H - 160, BASE.thumb_bg, BASE.border,
           label="asset preview", label_color=BASE.text_muted)

    # Right of detail: activity / notes
    region(d, int(W * 0.58) + 8, D_Y, W - int(W * 0.58) - 28, D_H,
           BASE.bg_raised, label="activity / notes for this bead",
           label_color=BASE.text_secondary)
    for i, note in enumerate([
            "09:14 - auto-tagged (boku, kickstarter, hero)",
            "10:02 - crop defined for Kickstarter",
            "11:48 - queued to OneUp  ->  Apr 27 09:00",
            "- draft email copy -",
    ]):
        d.text((int(W * 0.58) + 28, D_Y + 40 + i * 28), note,
               fill=hx(BASE.text_secondary) + (255,), font=font(12))
    return img, {
        "title": "Timeline First",
        "thesis": "Every asset exists at a point in a campaign.",
        "regions": ["campaign_tabs", "timeline_band",
                     "inspector", "activity_notes"],
        "wins": ["time context first", "scheduling is the default",
                  "campaigns feel alive"],
        "costs": ["weak for ad-hoc browsing",
                  "assets without a campaign feel orphaned"],
    }


# ---------------------------------------------------------------------------
# Master review sheet
# ---------------------------------------------------------------------------

def build_review_sheet(variants: list[tuple[str, Image.Image, dict]]):
    """Stack every variant top-to-bottom with a thesis strip between."""
    THUMB_W = 1500
    tiles = []
    for fn, img, meta in variants:
        ratio = THUMB_W / img.width
        t = img.resize((THUMB_W, int(img.height * ratio)), Image.LANCZOS)
        tiles.append((fn, t, meta))
    strip_h = 140
    total_h = sum(t[1].height + strip_h + 12 for t in tiles) + 200
    total_w = THUMB_W + 80
    bg = hx(BASE.bg_deep) + (255,)
    out = Image.new("RGBA", (total_w, total_h), bg)
    d = ImageDraw.Draw(out)
    d.text((32, 18),
           "DoxyEdit  -  Five UI Redesign Mockups",
           fill=hx(BASE.text_primary) + (255,), font=font(40, bold=True))
    d.text((32, 70),
           "Schematic only. Real theme tokens wired in so each surface "
           "shows which field drives it. Pick one direction before any "
           "code lands.",
           fill=hx(BASE.text_secondary) + (255,), font=font(18))
    y = 140
    for fn, img, meta in tiles:
        # Thesis strip
        d.rectangle([(32, y), (32 + THUMB_W, y + strip_h - 12)],
                      fill=hx(BASE.bg_raised) + (255,))
        d.text((48, y + 10),
               f"{meta['title']}",
               fill=hx(BASE.accent_bright) + (255,), font=font(28, bold=True))
        d.text((48, y + 46),
               meta["thesis"],
               fill=hx(BASE.text_primary) + (255,), font=font(16))
        d.text((48, y + 74),
               "WINS:  " + "  |  ".join(meta["wins"]),
               fill=hx(BASE.text_secondary) + (255,), font=font(13))
        d.text((48, y + 98),
               "COSTS:  " + "  |  ".join(meta["costs"]),
               fill=hx(BASE.text_muted) + (255,), font=font(13))
        y += strip_h
        # Mockup
        out.paste(img, (40, y), img if img.mode == "RGBA" else None)
        y += img.height + 12
    return out


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    variants = [
        ("01_dashboard_first", *render_01_dashboard_first()),
        ("02_gallery_centric", *render_02_gallery_centric()),
        ("03_command_palette", *render_03_command_palette()),
        ("04_three_column_pro", *render_04_three_column_pro()),
        ("05_timeline_first", *render_05_timeline_first()),
    ]
    metas = {}
    for fn, img, meta in variants:
        path = OUT_DIR / f"{fn}.png"
        img.save(path)
        metas[fn] = meta
        print(f"wrote {path.relative_to(REPO_ROOT)}  ({img.width}x{img.height})")
    # Review sheet
    sheet = build_review_sheet(variants)
    sheet_path = OUT_DIR / "review_sheet.png"
    sheet.save(sheet_path)
    print(f"wrote {sheet_path.relative_to(REPO_ROOT)}  "
          f"({sheet.width}x{sheet.height})")
    # Meta JSON
    (OUT_DIR / "redesigns.json").write_text(
        json.dumps({"variants": metas,
                     "base_theme": DEFAULT_THEME,
                     "canvas_size": [W, H]}, indent=2),
        encoding="utf-8")
    print(f"wrote {(OUT_DIR / 'redesigns.json').relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
