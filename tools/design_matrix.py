"""5 design philosophies x 5 screens = 25 mockups.

Each philosophy defines its own visual DNA (palette, type, density,
corner radii, chrome weight). Each screen (Assets / Studio / Social /
Dashboard / Timeline) is rendered under all five philosophies so the
comparison is apples-to-apples.

Output:
    design_mockups/matrix/
        brutalist/       {assets,studio,social,dashboard,timeline}.png
        bento/           ...
        terminal/        ...
        zen/             ...
        editorial/       ...
        matrix.png       5x5 master sheet
        matrix.json      philosophy manifests + token refs
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)


OUT_DIR = REPO_ROOT / "design_mockups" / "matrix"
W, H = 1440, 900


# ---------------------------------------------------------------------------
# Philosophy presets
# ---------------------------------------------------------------------------

@dataclass
class Philosophy:
    key: str
    title: str
    thesis: str
    bg_deep: str
    bg_main: str
    bg_raised: str
    bg_input: str
    accent: str
    accent_dim: str
    text_primary: str
    text_secondary: str
    text_muted: str
    border: str
    corner: int          # default corner radius
    font_family: str     # preferred font file name
    font_family_alt: str # label/mono font (if any)
    font_scale: float    # global font multiplier
    density: str         # "tight" | "normal" | "airy"
    case_labels: str     # "upper" | "title" | "lower"
    border_weight: int
    shadow_depth: int    # fake shadow offset, 0 = flat
    uppercase_headers: bool = True


PHILOSOPHIES: list[Philosophy] = [
    Philosophy(
        key="brutalist",
        title="Brutalist",
        thesis="Raw. High-contrast. Monospace. No rounding. Labels shout. "
               "Information density maxed. Chrome is a feature, not a cost.",
        bg_deep="#0a0a0a", bg_main="#141414", bg_raised="#1e1e1e", bg_input="#080808",
        accent="#ff5500", accent_dim="#802200",
        text_primary="#f8f8f8", text_secondary="#c0c0c0", text_muted="#707070",
        border="#ff5500",
        corner=0,
        font_family="consola.ttf", font_family_alt="consolab.ttf",
        font_scale=1.0, density="tight", case_labels="upper",
        border_weight=3, shadow_depth=0,
    ),
    Philosophy(
        key="bento",
        title="Bento Card",
        thesis="Soft pastel surfaces. Heavy rounding. Asymmetric card grid. "
               "Apple-widget mood. Everything floats on pillows.",
        bg_deep="#f4efea", bg_main="#fbf7f3", bg_raised="#ffffff", bg_input="#faf5ef",
        accent="#ff7a9c", accent_dim="#f8c0ce",
        text_primary="#201828", text_secondary="#5c4a5c", text_muted="#a098a8",
        border="#ebe2e8",
        corner=22,
        font_family="seguisb.ttf", font_family_alt="seguibl.ttf",
        font_scale=1.1, density="airy", case_labels="title",
        border_weight=1, shadow_depth=6,
        uppercase_headers=False,
    ),
    Philosophy(
        key="terminal",
        title="Terminal Power",
        thesis="Phosphor-green on black. Keyboard-first. Vim modal hints. "
               "ASCII dividers. Mouse is optional. Status lines everywhere.",
        bg_deep="#000000", bg_main="#020a02", bg_raised="#061506", bg_input="#000400",
        accent="#00ff66", accent_dim="#006622",
        text_primary="#c8ffc8", text_secondary="#6ecc6e", text_muted="#406640",
        border="#00ff66",
        corner=0,
        font_family="consola.ttf", font_family_alt="consolab.ttf",
        font_scale=0.95, density="tight", case_labels="lower",
        border_weight=1, shadow_depth=0,
    ),
    Philosophy(
        key="zen",
        title="Zen Minimal",
        thesis="Huge whitespace. Thin hairlines. Type small. One focal point. "
               "No toolbars. Discoverability hidden, elegance obvious.",
        bg_deep="#fafafa", bg_main="#ffffff", bg_raised="#ffffff", bg_input="#f6f6f6",
        accent="#222222", accent_dim="#aaaaaa",
        text_primary="#0a0a0a", text_secondary="#555555", text_muted="#a8a8a8",
        border="#ececec",
        corner=3,
        font_family="segoeui.ttf", font_family_alt="segoeuil.ttf",
        font_scale=0.95, density="airy", case_labels="title",
        border_weight=1, shadow_depth=0,
        uppercase_headers=False,
    ),
    Philosophy(
        key="editorial",
        title="Editorial Magazine",
        thesis="Print-spread inspired. Serif display type. Photo-forward. "
               "Big hierarchy between headline and body. Accent is ink-red.",
        bg_deep="#1a1614", bg_main="#22201c", bg_raised="#2c2924", bg_input="#1a1714",
        accent="#d4361f", accent_dim="#8a2818",
        text_primary="#f4ecd8", text_secondary="#c8b890", text_muted="#8c7c60",
        border="#44392c",
        corner=2,
        font_family="georgia.ttf", font_family_alt="georgiab.ttf",
        font_scale=1.05, density="normal", case_labels="title",
        border_weight=1, shadow_depth=0,
        uppercase_headers=False,
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def hx(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def font(ph: Philosophy, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    target = ph.font_family_alt if bold else ph.font_family
    size = max(8, int(size * ph.font_scale))
    for candidate in (target, ph.font_family, "arial.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def lbl(text: str, ph: Philosophy) -> str:
    if ph.case_labels == "upper":
        return text.upper()
    if ph.case_labels == "lower":
        return text.lower()
    return text


def rect(draw, box, fill=None, outline=None, width=1, radius=0):
    """Rounded rectangle with fall-back."""
    x1, y1, x2, y2 = box
    fill_c = hx(fill) + (255,) if fill else None
    out_c = hx(outline) + (255,) if outline else None
    if radius <= 0:
        draw.rectangle(box, fill=fill_c, outline=out_c, width=width)
    else:
        draw.rounded_rectangle(box, fill=fill_c, outline=out_c,
                                 width=width, radius=radius)


def text(draw, xy, t, ph, size=14, bold=False, color=None):
    color_c = hx(color or ph.text_primary) + (255,)
    draw.text(xy, t, fill=color_c, font=font(ph, size, bold=bold))


def header_strip(draw, ph: Philosophy, title: str, subtitle: str):
    rect(draw, (0, 0, W, 80), fill=ph.bg_raised, radius=0)
    rect(draw, (0, 78, W, 80), fill=ph.accent, radius=0)
    title_f = font(ph, 24, bold=True)
    draw.text((28, 12), lbl(title, ph), fill=hx(ph.text_primary) + (255,), font=title_f)
    draw.text((28, 44), subtitle, fill=hx(ph.text_secondary) + (255,), font=font(ph, 14))


def shadow_behind(img: Image.Image, box, depth: int, opacity: int = 60):
    if depth <= 0:
        return
    x1, y1, x2, y2 = box
    shadow = Image.new("RGBA", (x2 - x1 + depth * 2, y2 - y1 + depth * 2),
                        (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((depth, depth, x2 - x1 + depth, y2 - y1 + depth),
                           fill=(0, 0, 0, opacity), radius=22)
    img.alpha_composite(shadow, (x1 - depth, y1 - depth))


# ---------------------------------------------------------------------------
# Screen renderers
# ---------------------------------------------------------------------------

def new_img(ph: Philosophy) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (W, H), hx(ph.bg_deep) + (255,))
    return img, ImageDraw.Draw(img)


def screen_assets(ph: Philosophy) -> Image.Image:
    img, d = new_img(ph)
    header_strip(d, ph, "Assets", "Browse, tag, and stage your library.")

    # Left filter rail - width depends on density
    rail_w = 220 if ph.density == "airy" else 190
    rect(d, (0, 80, rail_w, H), fill=ph.bg_main, outline=ph.border,
         width=ph.border_weight, radius=0)
    text(d, (18, 104), lbl("Filters", ph), ph, 14, bold=True, color=ph.accent)
    for i, tag in enumerate(["sfw", "nsfw", "color", "sketch", "final",
                              "furry", "boku", "jenni_01"]):
        bx = (16, 128 + i * 34, rail_w - 16, 128 + i * 34 + 28)
        rect(d, bx, fill=ph.bg_input, outline=ph.border,
             width=1, radius=ph.corner)
        text(d, (28, 134 + i * 34), lbl(tag, ph), ph, 13)

    # Main grid
    grid_x = rail_w + (24 if ph.density == "airy" else 12)
    grid_y = 104
    THUMB = {"tight": 150, "normal": 170, "airy": 190}[ph.density]
    gap = {"tight": 6, "normal": 14, "airy": 22}[ph.density]
    cols = (W - grid_x - 320) // (THUMB + gap)
    rows = (H - grid_y - 30) // (THUMB + gap)
    for i in range(cols * rows):
        cc, rr = i % cols, i // cols
        tx = grid_x + cc * (THUMB + gap)
        ty = grid_y + rr * (THUMB + gap)
        if ty + THUMB > H - 20:
            break
        if ph.shadow_depth:
            shadow_behind(img, (tx, ty, tx + THUMB, ty + THUMB),
                           ph.shadow_depth)
        rect(d, (tx, ty, tx + THUMB, ty + THUMB),
             fill=ph.bg_raised, outline=ph.border,
             width=ph.border_weight, radius=ph.corner)
        # Status dot
        d.ellipse((tx + THUMB - 18, ty + 8, tx + THUMB - 6, ty + 20),
                    fill=hx(ph.accent) + (255,))

    # Right inspector
    insp_x = W - 300
    rect(d, (insp_x, 80, W, H), fill=ph.bg_main, outline=ph.border,
         width=ph.border_weight, radius=0)
    text(d, (insp_x + 20, 104), lbl("Inspector", ph), ph, 14, bold=True,
         color=ph.accent)
    for i, (k, v) in enumerate([("Name", "comfy_44199.png"),
                                   ("Format", "PNG"), ("Size", "977 KB"),
                                   ("Tags", "boku sfw"),
                                   ("Platform", "kickstarter")]):
        y = 140 + i * 40
        text(d, (insp_x + 20, y), lbl(k, ph), ph, 12, color=ph.text_secondary)
        text(d, (insp_x + 20, y + 16), v, ph, 13, bold=True)
    return img


def screen_studio(ph: Philosophy) -> Image.Image:
    img, d = new_img(ph)
    header_strip(d, ph, "Studio", "Crop, annotate, overlay, export.")

    # Left tool rail
    rect(d, (0, 80, 72, H), fill=ph.bg_main, outline=ph.border,
         width=ph.border_weight, radius=0)
    icons = ["Sel", "T", "Sh", "Ar", "Cn", "Cr", "Pk", "N", "Wm"]
    for i, g in enumerate(icons):
        cy = 100 + i * 56
        rect(d, (12, cy, 60, cy + 48), fill=ph.bg_raised,
             outline=ph.border, width=ph.border_weight,
             radius=ph.corner)
        text(d, (22, cy + 14), lbl(g, ph), ph, 12, bold=True,
             color=ph.accent)

    # Top quickbar
    rect(d, (80, 90, W - 320, 128), fill=ph.bg_raised,
         outline=ph.border, width=ph.border_weight, radius=ph.corner)
    for i, t in enumerate(["Select", "Censor", "Crop", "Free crop",
                            "Note", "Arrow", "Shape", "Delete",
                            "Watermark", "Text", "Export"]):
        text(d, (96 + i * 95, 100), lbl(t, ph), ph, 12,
             color=ph.text_secondary)

    # Canvas
    cx1, cy1, cx2, cy2 = 96, 140, W - 336, H - 40
    rect(d, (cx1, cy1, cx2, cy2), fill=ph.bg_deep,
         outline=ph.border, width=ph.border_weight, radius=ph.corner)
    # Subject stand-in
    subj = (cx1 + (cx2 - cx1) // 4, cy1 + (cy2 - cy1) // 6,
            cx2 - (cx2 - cx1) // 4, cy2 - (cy2 - cy1) // 6)
    rect(d, subj, fill=ph.bg_raised, outline=ph.accent,
         width=ph.border_weight + 1, radius=ph.corner)
    text(d, (subj[0] + 16, subj[1] + 16),
         lbl("<< canvas subject >>", ph), ph, 14,
         color=ph.text_muted)
    # Crop handles
    for (cx, cy) in [(subj[0], subj[1]), (subj[2], subj[1]),
                       (subj[0], subj[3]), (subj[2], subj[3])]:
        d.rectangle((cx - 6, cy - 6, cx + 6, cy + 6),
                       fill=hx(ph.accent) + (255,))

    # Right layers
    lx = W - 316
    rect(d, (lx, 90, W - 16, H - 40), fill=ph.bg_main,
         outline=ph.border, width=ph.border_weight, radius=ph.corner)
    text(d, (lx + 16, 106), lbl("Layers", ph), ph, 14, bold=True,
         color=ph.accent)
    for i, n in enumerate(["Base", "Censor", "Overlay", "Logo",
                              "Text 'Kickstarter'", "Shape rect", "Note 1"]):
        y = 140 + i * 34
        rect(d, (lx + 14, y, W - 30, y + 28),
             fill=ph.bg_raised, outline=ph.border,
             width=1, radius=ph.corner)
        d.ellipse((lx + 24, y + 8, lx + 36, y + 20),
                    fill=hx(ph.accent) + (255,))
        text(d, (lx + 46, y + 6), n, ph, 13)
    return img


def screen_social(ph: Philosophy) -> Image.Image:
    img, d = new_img(ph)
    header_strip(d, ph, "Social", "Compose, queue, sync across 12 platforms.")

    # Left column: platforms list
    rect(d, (0, 80, 260, H), fill=ph.bg_main, outline=ph.border,
         width=ph.border_weight, radius=0)
    text(d, (20, 104), lbl("Platforms", ph), ph, 14, bold=True,
         color=ph.accent)
    for i, (p, s) in enumerate([("X / Twitter", "posted"),
                                  ("Patreon", "queued"),
                                  ("Bluesky", "draft"),
                                  ("Telegram", "posted"),
                                  ("Discord", "failed"),
                                  ("TikTok", "draft"),
                                  ("Instagram", "queued"),
                                  ("Threads", "draft"),
                                  ("Reddit", "posted")]):
        y = 140 + i * 48
        rect(d, (14, y, 246, y + 40), fill=ph.bg_raised,
             outline=ph.border, width=1, radius=ph.corner)
        text(d, (28, y + 8), p, ph, 13, bold=True)
        text(d, (28, y + 22), lbl(s, ph), ph, 11, color=ph.text_muted)
        d.ellipse((222, y + 14, 236, y + 28),
                    fill=hx(ph.accent) + (255,))

    # Middle: composer
    cx = 276
    rect(d, (cx, 100, W - 316, H - 30), fill=ph.bg_raised,
         outline=ph.border, width=ph.border_weight, radius=ph.corner)
    text(d, (cx + 20, 116), lbl("Compose", ph), ph, 14, bold=True,
         color=ph.accent)
    # Attachment thumb
    rect(d, (cx + 20, 148, cx + 260, 388),
         fill=ph.bg_deep, outline=ph.border,
         width=ph.border_weight, radius=ph.corner)
    text(d, (cx + 36, 164),
         lbl("<< asset preview >>", ph), ph, 12, color=ph.text_muted)
    # Caption
    rect(d, (cx + 280, 148, W - 332, 320),
         fill=ph.bg_input, outline=ph.border, width=1, radius=ph.corner)
    text(d, (cx + 296, 164),
         "New Kickstarter hero this week. "
         "Support via the link in bio. #doxy #boku",
         ph, 13)
    # Scheduling bar
    rect(d, (cx + 280, 336, W - 332, 388),
         fill=ph.bg_input, outline=ph.border, width=1, radius=ph.corner)
    text(d, (cx + 296, 352),
         lbl("Schedule: Apr 27 09:00  |  Platforms: 5 selected", ph),
         ph, 13, bold=True)
    # Queue button row
    rect(d, (cx + 20, 410, cx + 180, 452),
         fill=ph.accent, outline=ph.accent,
         width=ph.border_weight, radius=ph.corner)
    text(d, (cx + 48, 420), lbl("Queue post", ph), ph, 14, bold=True,
         color=ph.bg_deep)

    # Right: upcoming feed
    rx = W - 300
    rect(d, (rx, 80, W, H), fill=ph.bg_main, outline=ph.border,
         width=ph.border_weight, radius=0)
    text(d, (rx + 20, 104), lbl("Upcoming", ph), ph, 14, bold=True,
         color=ph.accent)
    for i, (w, d2) in enumerate([("Today 09:00", "Kickstarter hero"),
                                    ("Tomorrow 14:00", "Patreon weekly"),
                                    ("Apr 27 21:00", "Bluesky sketch"),
                                    ("Apr 29 10:00", "Twitter gif"),
                                    ("Apr 30 18:00", "Telegram dump")]):
        y = 140 + i * 62
        rect(d, (rx + 14, y, W - 14, y + 52),
             fill=ph.bg_raised, outline=ph.border,
             width=1, radius=ph.corner)
        text(d, (rx + 24, y + 6), w, ph, 11, color=ph.text_muted)
        text(d, (rx + 24, y + 22), d2, ph, 13, bold=True)
    return img


def screen_dashboard(ph: Philosophy) -> Image.Image:
    img, d = new_img(ph)
    header_strip(d, ph, "Dashboard", "Where the project stands, right now.")
    # Big single hero stat + 8 widgets
    # Hero
    hx1, hy1 = 32, 104
    hx2, hy2 = W - 32, 260
    if ph.shadow_depth:
        shadow_behind(img, (hx1, hy1, hx2, hy2), ph.shadow_depth)
    rect(d, (hx1, hy1, hx2, hy2), fill=ph.bg_raised,
         outline=ph.border, width=ph.border_weight, radius=ph.corner)
    text(d, (hx1 + 28, hy1 + 18),
         lbl("62% Kickstarter ready", ph), ph, 36, bold=True,
         color=ph.accent)
    text(d, (hx1 + 28, hy1 + 70),
         lbl("8 days to ship  -  24 of 38 assets finalised", ph), ph,
         15, color=ph.text_secondary)
    # Mini progress
    bar_x, bar_y, bar_w, bar_h = hx1 + 28, hy1 + 108, hx2 - hx1 - 56, 18
    rect(d, (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
         fill=ph.bg_input, outline=ph.border, width=1, radius=ph.corner)
    rect(d, (bar_x, bar_y, bar_x + int(bar_w * 0.62), bar_y + bar_h),
         fill=ph.accent, outline=None, radius=ph.corner)

    # Widget grid 4x2
    cols = 4
    rows = 2
    gx0 = 32
    gy0 = 280
    gap = 14
    gw = (W - 64 - gap * (cols - 1)) // cols
    gh = (H - gy0 - 40 - gap * (rows - 1)) // rows
    widgets = [
        ("Queued today", "3", ph.accent),
        ("Draft", "11", ph.text_secondary),
        ("Failed", "1", "#d05050"),
        ("Posted this week", "14", ph.text_primary),
        ("Assets imported", "34", ph.text_primary),
        ("New tags", "6", ph.text_primary),
        ("Platforms healthy", "6/7", ph.text_primary),
        ("Storage", "12.4 GB", ph.text_primary),
    ]
    for i, (label_, val, col) in enumerate(widgets):
        cc, rr = i % cols, i // cols
        wx = gx0 + cc * (gw + gap)
        wy = gy0 + rr * (gh + gap)
        if ph.shadow_depth:
            shadow_behind(img, (wx, wy, wx + gw, wy + gh),
                           ph.shadow_depth)
        rect(d, (wx, wy, wx + gw, wy + gh),
             fill=ph.bg_raised, outline=ph.border,
             width=ph.border_weight, radius=ph.corner)
        text(d, (wx + 20, wy + 16), lbl(label_, ph), ph, 12,
             color=ph.text_secondary)
        text(d, (wx + 20, wy + 40), val, ph, 42, bold=True, color=col)
    return img


def screen_timeline(ph: Philosophy) -> Image.Image:
    img, d = new_img(ph)
    header_strip(d, ph, "Timeline",
                  "Campaigns as threads. Assets as beads. Scrub to travel.")

    # Campaign selector row
    row_y = 96
    for i, c in enumerate(["Kickstarter", "Steam", "Patreon", "Merch", "Socials"]):
        x = 32 + i * 180
        active = i == 0
        rect(d, (x, row_y, x + 160, row_y + 36),
             fill=ph.accent if active else ph.bg_input,
             outline=ph.border, width=ph.border_weight, radius=ph.corner)
        text(d, (x + 14, row_y + 8), lbl(c, ph), ph, 13, bold=True,
             color=ph.bg_deep if active else ph.text_primary)

    # Timeline rail
    ty = 160
    th = 320
    rect(d, (0, ty, W, ty + th), fill=ph.bg_main, outline=ph.border,
         width=0, radius=0)
    # Day ticks (weekly labels)
    for i in range(12):
        x = 60 + i * (W - 120) // 11
        d.line((x, ty + 18, x, ty + th - 40),
                 fill=hx(ph.border) + (255,), width=1)
        text(d, (x + 4, ty + 8), f"w{i + 1}", ph, 10,
             color=ph.text_muted)

    # Threads
    names = ["Kickstarter", "Steam", "Patreon", "Merch"]
    colors = [ph.accent, ph.accent, ph.accent_dim, ph.text_secondary]
    import random
    random.seed(7)
    for row, (n, c) in enumerate(zip(names, colors)):
        yr = ty + 56 + row * 56
        text(d, (16, yr - 4), lbl(n, ph), ph, 12, bold=True,
             color=ph.text_secondary)
        d.line((110, yr + 10, W - 30, yr + 10),
                 fill=hx(c) + (255,), width=3)
        stops = random.sample(range(0, 11), 5)
        for s in stops:
            bx = 110 + s * (W - 150) // 10
            d.ellipse((bx - 9, yr + 1, bx + 9, yr + 19),
                        fill=hx(c) + (255,),
                        outline=hx(ph.bg_deep) + (255,),
                        width=2)
    # Today marker
    tx = 110 + 5 * (W - 150) // 10
    d.line((tx, ty + 26, tx, ty + th - 50),
             fill=hx(ph.accent) + (255,), width=2)
    text(d, (tx + 6, ty + 26), lbl("Today", ph), ph, 12, bold=True,
         color=ph.accent)

    # Detail below
    dy = ty + th + 16
    rect(d, (32, dy, W // 2 - 12, H - 20),
         fill=ph.bg_raised, outline=ph.border,
         width=ph.border_weight, radius=ph.corner)
    text(d, (48, dy + 16),
         lbl("Kickstarter - Week 3 Hero", ph), ph, 20, bold=True,
         color=ph.accent)
    text(d, (48, dy + 52),
         "hero_final_kickstarter.psd  -  1920x1080  -  READY", ph, 13,
         color=ph.text_secondary)
    rect(d, (48, dy + 82, W // 2 - 28, H - 40),
         fill=ph.bg_deep, outline=ph.border, width=1, radius=ph.corner)
    text(d, (60, dy + 98),
         lbl("<< asset preview >>", ph), ph, 12, color=ph.text_muted)

    rect(d, (W // 2 + 4, dy, W - 32, H - 20),
         fill=ph.bg_raised, outline=ph.border,
         width=ph.border_weight, radius=ph.corner)
    text(d, (W // 2 + 20, dy + 16),
         lbl("Activity", ph), ph, 16, bold=True, color=ph.accent)
    events = [
        "09:14  auto-tagged  boku kickstarter hero",
        "10:02  crop defined for Kickstarter",
        "11:48  queued to OneUp  Apr 27 09:00",
        "12:17  note: swap hair highlight",
        "13:40  exported /dist/hero_kickstarter.png",
    ]
    for i, e in enumerate(events):
        text(d, (W // 2 + 24, dy + 58 + i * 28),
             lbl(e, ph), ph, 12, color=ph.text_secondary)
    return img


SCREEN_RENDERERS = [
    ("assets", "Assets", screen_assets),
    ("studio", "Studio", screen_studio),
    ("social", "Social", screen_social),
    ("dashboard", "Dashboard", screen_dashboard),
    ("timeline", "Timeline", screen_timeline),
]


# ---------------------------------------------------------------------------
# Master 5x5 sheet
# ---------------------------------------------------------------------------

def build_matrix_sheet() -> Image.Image:
    # Each tile ~320 wide
    TILE_W = 340
    TILE_H = int(TILE_W * H / W)
    gap = 14
    label_h = 48
    top_h = 120
    cols = len(SCREEN_RENDERERS)
    rows = len(PHILOSOPHIES)
    sheet_w = 180 + cols * (TILE_W + gap) + gap
    sheet_h = top_h + rows * (TILE_H + gap) + gap
    out = Image.new("RGBA", (sheet_w, sheet_h), (16, 16, 20, 255))
    d = ImageDraw.Draw(out)
    # Dummy philosophy for the sheet header (use zen, clean)
    hdr = PHILOSOPHIES[3]
    d.text((28, 16),
           "DoxyEdit  -  5 philosophies x 5 screens  =  25 mockups",
           fill=(255, 255, 255, 255),
           font=ImageFont.truetype("arialbd.ttf", 32))
    d.text((28, 60),
           "Each row is a different design philosophy. Each column is "
           "the same screen rendered under that philosophy.",
           fill=(200, 200, 200, 255),
           font=ImageFont.truetype("arial.ttf", 16))
    # Column headers
    for col, (_, scr_title, _) in enumerate(SCREEN_RENDERERS):
        x = 180 + col * (TILE_W + gap)
        d.text((x + 12, top_h - 28), scr_title,
               fill=(220, 220, 220, 255),
               font=ImageFont.truetype("arialbd.ttf", 18))
    # Rows
    for row, ph in enumerate(PHILOSOPHIES):
        y = top_h + row * (TILE_H + gap)
        # Row label
        d.text((18, y + 8), ph.title,
               fill=(220, 220, 220, 255),
               font=ImageFont.truetype("arialbd.ttf", 20))
        d.text((18, y + 34), ph.thesis[:140],
               fill=(160, 160, 160, 255),
               font=ImageFont.truetype("arial.ttf", 11))
        for col, (key, _, renderer) in enumerate(SCREEN_RENDERERS):
            img = renderer(ph).resize((TILE_W, TILE_H), Image.LANCZOS)
            out.paste(img, (180 + col * (TILE_W + gap), y), img)
    return out


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {"philosophies": [], "grid_size": [W, H]}
    for ph in PHILOSOPHIES:
        ph_dir = OUT_DIR / ph.key
        ph_dir.mkdir(parents=True, exist_ok=True)
        ph_info = {"key": ph.key, "title": ph.title, "thesis": ph.thesis,
                    "palette": {"bg_deep": ph.bg_deep, "bg_main": ph.bg_main,
                                  "bg_raised": ph.bg_raised, "accent": ph.accent,
                                  "text_primary": ph.text_primary,
                                  "border": ph.border},
                    "corner": ph.corner, "font_family": ph.font_family,
                    "density": ph.density, "case_labels": ph.case_labels,
                    "screens": []}
        for key, title, renderer in SCREEN_RENDERERS:
            img = renderer(ph)
            out_path = ph_dir / f"{key}.png"
            img.save(out_path)
            ph_info["screens"].append({"key": key, "title": title,
                                          "file": str(out_path.relative_to(REPO_ROOT)),
                                          "size": [img.width, img.height]})
            print(f"wrote {out_path.relative_to(REPO_ROOT)}")
        manifest["philosophies"].append(ph_info)
    sheet = build_matrix_sheet()
    sheet_path = OUT_DIR / "matrix.png"
    sheet.save(sheet_path)
    print(f"\nwrote {sheet_path.relative_to(REPO_ROOT)}  "
          f"({sheet.width}x{sheet.height})")
    (OUT_DIR / "matrix.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {(OUT_DIR / 'matrix.json').relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
