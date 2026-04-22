"""5 different UI PROTOCOLS (not themes, not colors — interaction models).

Each protocol answers the question: 'how do you interact with the software?'
The current DoxyEdit uses PROTOCOL 0 (tabs + panels + menus + keyboard
shortcuts). These 5 are radically different interaction paradigms, not
styling exercises.

PROTOCOL 1. Spatial Canvas       - assets as floating objects on infinite 2D board
PROTOCOL 2. Conversational       - natural language chat, no traditional UI
PROTOCOL 3. Spreadsheet Database - every asset is a row, edit cells inline
PROTOCOL 4. Node Graph           - pipelines as wire-connected nodes
PROTOCOL 5. Card Stack / Triage  - one asset fills screen, gesture to act

Each image annotates the interaction mechanics (gestures, keystrokes,
affordances) so you can judge FEEL, not look.
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

OUT_DIR = REPO_ROOT / "design_mockups" / "protocols"
W, H = 1920, 1200


def hx(h): h = h.lstrip("#"); return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
def fnt(sz, bold=False):
    for f in ("arialbd.ttf" if bold else "arial.ttf", "arial.ttf"):
        try: return ImageFont.truetype(f, sz)
        except: pass
    return ImageFont.load_default()

def header(d, title, thesis, mechanic, fg, acc, sub):
    d.rectangle([(0, 0), (W, 110)], fill=(20, 20, 24, 255))
    d.rectangle([(0, 108), (W, 110)], fill=hx(acc) + (255,))
    d.text((32, 14), title, fill=fg, font=fnt(34, bold=True))
    d.text((32, 56), thesis, fill=sub, font=fnt(17))
    d.text((32, 82), "Mechanic: " + mechanic, fill=hx(acc) + (255,),
           font=fnt(14, bold=True))


# ---------------------------------------------------------------------------
# PROTOCOL 1 - Spatial Canvas (Miro / tldraw / Figma board)
# ---------------------------------------------------------------------------

def protocol_1_spatial():
    img = Image.new("RGBA", (W, H), (30, 34, 40, 255))
    d = ImageDraw.Draw(img)
    header(d, "Protocol 1  -  Spatial Canvas",
           "No tabs, no panels. An infinite 2D board. Assets are objects "
           "you drag, group, lasso, and zoom. Tags are drawn regions. "
           "Relationships live in space, not in a tree.",
           "pan with middle-mouse  -  zoom with wheel  -  lasso with drag  "
           "-  drop assets from Explorer anywhere",
           fg=(240, 240, 240, 255), acc="#4bd5a8", sub=(170, 180, 190, 255))

    # Draw a subtle infinite-canvas dot grid
    for x in range(0, W, 48):
        for y in range(120, H, 48):
            d.ellipse((x - 1, y - 1, x + 1, y + 1), fill=(60, 64, 72, 255))

    # Drawn regions (tags) - semi-transparent colored zones
    regions = [
        (180, 180, 820, 560, "#4bd5a8", "KICKSTARTER"),
        (920, 210, 1620, 520, "#ec7a8c", "BOKU"),
        (260, 640, 900, 1020, "#f0b84a", "SKETCH / WIP"),
        (1040, 620, 1720, 1040, "#7a9bf5", "PATREON QUEUE"),
    ]
    for x1, y1, x2, y2, c, label in regions:
        fill = hx(c) + (40,)
        stroke = hx(c) + (180,)
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.rounded_rectangle((x1, y1, x2, y2), fill=fill, outline=stroke,
                               width=2, radius=22)
        img.alpha_composite(overlay)
        d.text((x1 + 16, y1 + 12), label, fill=hx(c) + (255,),
               font=fnt(18, bold=True))

    # Assets as floating cards with connections
    random.seed(11)
    assets = []
    for _ in range(22):
        cx = random.randint(230, W - 230)
        cy = random.randint(170, H - 90)
        # Snap into a region roughly
        sz = random.choice([90, 110, 130])
        assets.append((cx, cy, sz))
    for cx, cy, sz in assets:
        rect = (cx - sz, cy - sz // 2, cx + sz, cy + sz // 2)
        # Shadow
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        sd.rounded_rectangle((rect[0] + 4, rect[1] + 6, rect[2] + 4, rect[3] + 6),
                               fill=(0, 0, 0, 100), radius=8)
        img.alpha_composite(sh)
        d.rounded_rectangle(rect, fill=(50, 56, 68, 255),
                              outline=(90, 100, 118, 255), width=1, radius=8)
        # Fake thumbnail band
        d.rounded_rectangle((rect[0] + 6, rect[1] + 6, rect[2] - 6, rect[3] - 16),
                              fill=(70, 80, 94, 255), radius=6)
        d.text((rect[0] + 8, rect[3] - 14), "asset",
               fill=(170, 180, 200, 255), font=fnt(10))

    # Draw a few connection lines (arrows) between assets
    for i in range(6):
        a = random.choice(assets)
        b = random.choice(assets)
        if a == b: continue
        d.line([(a[0], a[1]), (b[0], b[1])],
               fill=(100, 210, 170, 180), width=2)

    # Selection rectangle
    d.rectangle((460, 340, 720, 470), outline=(75, 213, 168, 255), width=2)
    d.text((460, 320), "lasso selection (3 items)  -  drag to tag zone to tag all",
           fill=(180, 230, 210, 255), font=fnt(13, bold=True))

    # Floating mini-HUD bottom-left
    d.rounded_rectangle((32, H - 90, 540, H - 32), fill=(20, 24, 30, 230),
                          outline=(75, 213, 168, 255), width=1, radius=10)
    d.text((48, H - 80), "zoom 68%   view: all   assets 827 / 2413",
           fill=(220, 230, 240, 255), font=fnt(13, bold=True))
    d.text((48, H - 60), "Ctrl+F find  -  Ctrl+G group  -  Ctrl+T make tag region",
           fill=(130, 180, 170, 255), font=fnt(11))
    d.text((48, H - 42), "drop .psd / .png / .jpg on canvas to import",
           fill=(130, 140, 160, 255), font=fnt(11))

    # Minimap top-right
    mx1, my1, mx2, my2 = W - 360, 138, W - 40, 340
    d.rounded_rectangle((mx1, my1, mx2, my2),
                          fill=(20, 24, 30, 255),
                          outline=(90, 100, 118, 255), width=1, radius=10)
    d.text((mx1 + 12, my1 + 8), "minimap", fill=(150, 170, 180, 255),
           font=fnt(11, bold=True))
    d.rectangle((mx1 + 60, my1 + 40, mx1 + 230, my1 + 140),
                  outline=(75, 213, 168, 255), width=2)

    save(img, "01_spatial_canvas")


# ---------------------------------------------------------------------------
# PROTOCOL 2 - Conversational (chat AI)
# ---------------------------------------------------------------------------

def protocol_2_chat():
    img = Image.new("RGBA", (W, H), (18, 18, 22, 255))
    d = ImageDraw.Draw(img)
    header(d, "Protocol 2  -  Conversational",
           "No toolbars, no panels. You talk to the software. It answers "
           "with thumbnails, tables, confirmations, and follow-up questions. "
           "Everything - tagging, scheduling, exporting - happens in prose.",
           "type your intent  -  review returned matches  -  confirm or refine",
           fg=(235, 235, 240, 255), acc="#8ab4ff", sub=(170, 180, 195, 255))

    # Chat container centered, narrow column
    CW = 880
    CX = (W - CW) // 2
    cy = 148
    d.rectangle((CX, cy, CX + CW, H - 120), fill=(24, 24, 30, 255),
                  outline=(50, 54, 66, 255), width=1)

    def bubble(y, side, text_lines, variant="normal", thumbs=0):
        bubble_w = 620
        if side == "user":
            bx = CX + CW - 32 - bubble_w
            color = (70, 100, 200, 230)
            fg = (255, 255, 255, 255)
        else:
            bx = CX + 32
            color = (38, 42, 54, 230)
            fg = (220, 225, 235, 255)
        line_h = 22
        pad = 14
        th = pad * 2 + line_h * len(text_lines) + (thumbs and 140 or 0)
        d.rounded_rectangle((bx, y, bx + bubble_w, y + th),
                              fill=color, radius=14)
        for i, t in enumerate(text_lines):
            d.text((bx + pad, y + pad + i * line_h), t,
                   fill=fg, font=fnt(14))
        # Thumbnail row
        if thumbs:
            ty = y + pad + line_h * len(text_lines) + 10
            for i in range(thumbs):
                tx = bx + pad + i * 110
                d.rounded_rectangle((tx, ty, tx + 96, ty + 110),
                                      fill=(90, 100, 120, 255),
                                      outline=(138, 180, 255, 255), width=1,
                                      radius=8)
                d.text((tx + 6, ty + 112), f"m{i + 1}.png",
                       fill=(160, 170, 190, 255), font=fnt(10))
        return y + th + 16

    cy = bubble(cy + 20, "user",
                ["can you show me every boku asset tagged 'final' this week"])
    cy = bubble(cy, "ai",
                ["Found 5 assets matching boku + final + this week:",
                 "(most recent first)"], thumbs=5)
    cy = bubble(cy, "user",
                ["queue the first 3 for kickstarter tomorrow morning"])
    cy = bubble(cy, "ai",
                ["OK - queued 3 posts for kickstarter, Apr 23 09:00.",
                 "Drafts saved. Say 'review drafts' to tweak copy."])
    cy = bubble(cy, "user",
                ["show drafts"])

    # Input box at bottom
    d.rounded_rectangle((CX + 32, H - 156, CX + CW - 32, H - 136 + 40),
                          fill=(34, 38, 48, 255), outline=(100, 140, 220, 255),
                          width=1, radius=18)
    d.text((CX + 48, H - 148), "> _", fill=(138, 180, 255, 255),
           font=fnt(15, bold=True))
    d.text((CX + 70, H - 148),
           "tag all mary sketches as 'draft' and send to the review tray",
           fill=(190, 200, 210, 255), font=fnt(14))

    # Sidebar hints
    d.text((32, 148), "suggestions",
           fill=(100, 150, 220, 255), font=fnt(13, bold=True))
    for i, h in enumerate(["queue patreon weekly",
                              "show failed posts",
                              "export kickstarter pack",
                              "tag recently imported",
                              "alerts today",
                              "switch to marty"]):
        d.rounded_rectangle((32, 172 + i * 40, 280, 172 + i * 40 + 28),
                              fill=(30, 34, 44, 255), outline=(60, 70, 84, 255),
                              width=1, radius=14)
        d.text((44, 178 + i * 40), h, fill=(180, 190, 210, 255), font=fnt(12))
    d.text((W - 32 - 120, H - 140), "Esc to hide",
           fill=(120, 130, 150, 255), font=fnt(11))

    save(img, "02_conversational")


# ---------------------------------------------------------------------------
# PROTOCOL 3 - Spreadsheet Database (Airtable / Notion table)
# ---------------------------------------------------------------------------

def protocol_3_spreadsheet():
    img = Image.new("RGBA", (W, H), (245, 245, 246, 255))
    d = ImageDraw.Draw(img)
    header(d, "Protocol 3  -  Spreadsheet Database",
           "Every asset is a row. Every attribute is a column. Click any "
           "cell to edit inline. Filter, sort, group, pivot. Bulk select "
           "fifty rows and change one column for all of them at once.",
           "arrow keys move cells  -  Tab next column  -  Enter commit  "
           "-  Ctrl+Shift+F filter  -  Ctrl+G group by column",
           fg=(20, 20, 28, 255), acc="#2a70ff", sub=(90, 100, 120, 255))

    # Filter / view bar
    d.rectangle((0, 110, W, 160), fill=(255, 255, 255, 255))
    d.line((0, 160, W, 160), fill=(220, 220, 226, 255), width=1)
    d.text((32, 124), "VIEW:", fill=(100, 110, 130, 255), font=fnt(11, bold=True))
    for i, v in enumerate(["All", "Boku / Final", "Scheduled this week",
                            "Failed", "Starred"]):
        sel = i == 0
        d.rounded_rectangle((86 + i * 140, 120, 86 + i * 140 + 128, 148),
                              fill=(42, 112, 255, 255) if sel else (242, 244, 248, 255),
                              outline=(42, 112, 255, 255) if sel else (220, 220, 230, 255),
                              width=1, radius=14)
        d.text((96 + i * 140, 126), v,
               fill=(255, 255, 255, 255) if sel else (60, 70, 90, 255),
               font=fnt(12, bold=sel))
    d.text((W - 360, 128), "+ New view   |   827 rows (12 selected)",
           fill=(80, 90, 110, 255), font=fnt(12, bold=True))

    # Column headers
    col_y = 170
    cols = [
        ("thumb", 72, None),
        ("name", 260, "str"),
        ("tags", 230, "multi"),
        ("platforms", 220, "multi"),
        ("status", 130, "select"),
        ("scheduled", 170, "date"),
        ("starred", 100, "int"),
        ("w x h", 120, "dim"),
        ("notes", 280, "str"),
        ("last posted", 140, "date"),
    ]
    x = 32
    for name, w, _ in cols:
        d.rectangle((x, col_y, x + w, col_y + 34),
                      fill=(248, 249, 252, 255),
                      outline=(220, 222, 228, 255), width=1)
        d.text((x + 10, col_y + 8), name,
               fill=(70, 80, 100, 255), font=fnt(12, bold=True))
        d.text((x + w - 16, col_y + 10), "v", fill=(160, 170, 190, 255),
               font=fnt(10))
        x += w

    # Rows
    rows = [
        ("img", "boku_hero_kickstarter_v3.psd", ["boku", "final", "hero"],
         ["kickstarter", "patreon"], "posted", "Apr 21 09:00", 3, "1920x1080",
         "strong engagement", "Apr 21"),
        ("img", "marty_sketch_001.png", ["marty", "wip"],
         [], "draft", "-", 1, "1200x1600", "needs linework", "-"),
        ("img", "jenni01_promo_512.jpg", ["jenni_01", "final"],
         ["bluesky"], "queued", "Apr 23 14:30", 2, "512x512",
         "auto-cropped", "-"),
        ("img", "peach_fanart_color.png", ["peach", "color"],
         ["twitter"], "failed", "Apr 22 10:00", 0, "2000x2000",
         "auth expired; retry", "-"),
        ("img", "yacky_merch_mug.psd", ["yacky", "merch"],
         ["kickstarter"], "posted", "Apr 20 08:00", 5, "4000x4000",
         "mug print master", "Apr 20"),
        ("img", "marty_final_01.psd", ["marty", "final"],
         ["patreon"], "queued", "Apr 25 10:00", 2, "1920x1080",
         "+ bubble text", "-"),
        ("img", "boku_study_pose_03.png", ["boku", "sketch"],
         [], "draft", "-", 0, "1024x768", "unsure - flag", "-"),
        ("img", "philomaus_tier_1.png", ["philomaus"],
         ["patreon"], "posted", "Apr 18 11:00", 4, "1500x2000",
         "tier card final", "Apr 18"),
        ("img", "rarity_gift_art.psd", ["rarity"],
         ["twitter", "bluesky"], "queued", "Apr 24 09:00", 1, "1920x1920",
         "waiting lines", "-"),
        ("img", "squids_wip_05.png", ["squids", "wip"],
         [], "draft", "-", 0, "1800x1200", "-", "-"),
        ("img", "design_logo_rough.psd", ["design"],
         [], "draft", "-", 0, "512x512", "iteration 3", "-"),
        ("img", "hardblush_cover.psd", ["hardblush", "final"],
         ["patreon", "twitter"], "posted", "Apr 17 08:00", 5, "3000x4000",
         "monthly cover", "Apr 17"),
        ("img", "sailor_moon_remix.png", ["sailor_moon"],
         [], "ignored", "-", 0, "1024x1024", "skip for now", "-"),
        ("img", "elf_inktober_10.png", ["elf", "sketch"],
         [], "draft", "-", 1, "2048x2048", "possibly print", "-"),
    ]
    y = col_y + 36
    for ri, r in enumerate(rows):
        row_h = 50
        bg = (255, 255, 255, 255)
        if ri in (1, 5):  # selected rows
            bg = (220, 235, 255, 255)
        x = 32
        d.rectangle((x, y, x + sum(c[1] for c in cols), y + row_h), fill=bg,
                      outline=(232, 232, 240, 255), width=1)
        # thumb
        d.rounded_rectangle((x + 8, y + 6, x + 64, y + row_h - 6),
                              fill=(200, 206, 216, 255),
                              outline=(170, 180, 200, 255), radius=4)
        x += cols[0][1]
        # name
        d.text((x + 12, y + 14), r[1],
               fill=(20, 24, 34, 255), font=fnt(13, bold=True))
        x += cols[1][1]
        # tags
        for i, t in enumerate(r[2][:3]):
            d.rounded_rectangle((x + 8 + i * 68, y + 14,
                                    x + 8 + i * 68 + 60, y + 34),
                                  fill=(238, 242, 250, 255),
                                  outline=(160, 180, 220, 255), width=1, radius=10)
            d.text((x + 14 + i * 68, y + 16), t[:7],
                   fill=(40, 70, 140, 255), font=fnt(11, bold=True))
        x += cols[2][1]
        # platforms
        for i, p in enumerate(r[3][:2]):
            d.rounded_rectangle((x + 8 + i * 100, y + 14,
                                    x + 8 + i * 100 + 94, y + 34),
                                  fill=(255, 240, 230, 255),
                                  outline=(220, 150, 90, 255), width=1,
                                  radius=10)
            d.text((x + 14 + i * 100, y + 16), p[:9],
                   fill=(150, 80, 20, 255), font=fnt(11, bold=True))
        x += cols[3][1]
        # status
        color = {"posted": (60, 160, 100, 255),
                   "queued": (240, 160, 40, 255),
                   "draft": (140, 150, 170, 255),
                   "failed": (220, 80, 80, 255),
                   "ignored": (180, 180, 180, 255)}[r[4]]
        d.rounded_rectangle((x + 10, y + 14, x + 114, y + 34),
                              fill=color, radius=10)
        d.text((x + 28, y + 16), r[4].upper(),
               fill=(255, 255, 255, 255), font=fnt(11, bold=True))
        x += cols[4][1]
        # scheduled
        d.text((x + 10, y + 14), r[5],
               fill=(20, 24, 34, 255), font=fnt(12))
        x += cols[5][1]
        # starred
        stars = "*" * r[6] if r[6] else "-"
        d.text((x + 10, y + 14), stars,
               fill=(220, 170, 40, 255), font=fnt(15, bold=True))
        x += cols[6][1]
        # dim
        d.text((x + 10, y + 14), r[7],
               fill=(60, 70, 90, 255), font=fnt(12))
        x += cols[7][1]
        # notes
        d.text((x + 10, y + 14), r[8][:34],
               fill=(40, 50, 70, 255), font=fnt(12))
        x += cols[8][1]
        # last posted
        d.text((x + 10, y + 14), r[9],
               fill=(60, 70, 90, 255), font=fnt(12))
        y += row_h

    # Active cell highlight
    d.rectangle((32 + sum(c[1] for c in cols[:4]) + 10,
                   col_y + 36 + 50 + 14,
                   32 + sum(c[1] for c in cols[:4]) + 114,
                   col_y + 36 + 50 + 34),
                  outline=(42, 112, 255, 255), width=3)
    d.text((32 + sum(c[1] for c in cols[:4]) - 18,
            col_y + 36 + 50 - 18),
           "<- active cell (click, type, Tab)",
           fill=(42, 112, 255, 255), font=fnt(11, bold=True))

    save(img, "03_spreadsheet_db")


# ---------------------------------------------------------------------------
# PROTOCOL 4 - Node Graph (Blender / Houdini / Unreal blueprint)
# ---------------------------------------------------------------------------

def protocol_4_node_graph():
    img = Image.new("RGBA", (W, H), (36, 38, 46, 255))
    d = ImageDraw.Draw(img)
    header(d, "Protocol 4  -  Node Graph",
           "Assets are source nodes. Crops, filters, censors, overlays, and "
           "exports are transform nodes. Platforms are sink nodes. Drag wires "
           "to build a pipeline. 'Run' the graph and every leaf ships.",
           "left-click drag wire  -  middle-mouse pan  -  F to frame selection  "
           "-  double-click node to edit its params  -  Ctrl+R to run",
           fg=(235, 235, 240, 255), acc="#ff9f40", sub=(170, 180, 195, 255))

    # Dot grid for the graph backdrop
    for x in range(0, W, 40):
        for y in range(120, H, 40):
            d.ellipse((x - 1, y - 1, x + 1, y + 1), fill=(56, 58, 68, 255))

    def node(x, y, w, h, title, subtitle, body_rows, accent, inputs=1, outputs=1):
        # Header
        d.rounded_rectangle((x, y, x + w, y + h),
                              fill=(50, 54, 66, 255),
                              outline=(90, 96, 114, 255), width=1, radius=6)
        d.rectangle((x, y, x + w, y + 34),
                      fill=hx(accent) + (255,))
        d.rounded_rectangle((x, y, x + w, y + 34), fill=hx(accent) + (255,),
                              radius=6)
        d.text((x + 12, y + 8), title,
               fill=(255, 255, 255, 255), font=fnt(14, bold=True))
        d.text((x + w - 80, y + 12), subtitle,
               fill=(255, 255, 255, 200), font=fnt(11))
        # Body rows
        for i, txt in enumerate(body_rows):
            d.text((x + 14, y + 44 + i * 20), txt,
                   fill=(220, 225, 235, 255), font=fnt(12))
        # Input sockets (left)
        for i in range(inputs):
            sy = y + h // 2 + (i - (inputs - 1) / 2) * 20
            d.ellipse((x - 8, sy - 7, x + 6, sy + 7),
                        fill=hx(accent) + (255,),
                        outline=(240, 240, 240, 255), width=2)
        # Output sockets (right)
        for i in range(outputs):
            sy = y + h // 2 + (i - (outputs - 1) / 2) * 20
            d.ellipse((x + w - 6, sy - 7, x + w + 8, sy + 7),
                        fill=hx(accent) + (255,),
                        outline=(240, 240, 240, 255), width=2)
        return [(x - 1, y + h // 2 + (i - (inputs - 1) / 2) * 20) for i in range(inputs)], \
               [(x + w + 1, y + h // 2 + (i - (outputs - 1) / 2) * 20) for i in range(outputs)]

    # Asset source column
    asset_nodes = []
    for i, name in enumerate(["boku_hero.psd", "marty_final.psd", "peach_sketch.psd"]):
        ix, ox = node(140, 200 + i * 170, 240, 130, "ASSET",
                         "psd", [name, "1920 x 1080", "tags: boku, final"],
                         accent="#4fc3f7", inputs=0, outputs=1)
        asset_nodes.append(ox[0])

    # Transform nodes
    crop_ins, crop_outs = node(520, 260, 230, 130, "CROP",
                                    "1920x1080 -> 1080x1080",
                                    ["format: square", "ratio: 1:1",
                                      "align: center"],
                                    accent="#9cd34c", inputs=1, outputs=1)
    censor_ins, censor_outs = node(520, 440, 230, 130, "CENSOR",
                                       "blackout",
                                       ["style: blackout", "regions: 2",
                                         "alpha: 220"],
                                       accent="#ec7a8c", inputs=1, outputs=1)
    overlay_ins, overlay_outs = node(520, 620, 230, 130, "OVERLAY",
                                         "watermark",
                                         ["logo: /brand/logo.png",
                                           "position: br",
                                           "opacity: 60"],
                                         accent="#e8b050", inputs=1, outputs=1)

    # Merge
    merge_ins, merge_outs = node(820, 440, 200, 130, "COMBINE",
                                      "stack -> png",
                                      ["layers: 3", "format: png",
                                        "quality: 95"],
                                      accent="#bb7bff", inputs=3, outputs=1)

    # Platform sink nodes (right column)
    kick_ins, _ = node(1150, 260, 260, 110, "KICKSTARTER",
                           "post",
                           ["caption: hero_post_01.md",
                             "scheduled: Apr 25 09:00"],
                           accent="#ff9f40", inputs=1, outputs=0)
    patreon_ins, _ = node(1150, 410, 260, 110, "PATREON",
                               "post",
                               ["caption: patreon_weekly.md",
                                 "scheduled: now"],
                               accent="#ff9f40", inputs=1, outputs=0)
    twitter_ins, _ = node(1150, 560, 260, 110, "X / TWITTER",
                               "post",
                               ["caption: twitter_hero.md",
                                 "auto thread: yes"],
                               accent="#ff9f40", inputs=1, outputs=0)
    fs_ins, _ = node(1150, 710, 260, 110, "FILESYSTEM",
                           "export folder",
                           ["path: /dist/kickstarter",
                             "format: png"],
                           accent="#ff9f40", inputs=1, outputs=0)

    # Wires
    def wire(a, b, color):
        # Bezier-ish curve — approximate with a polyline
        points = []
        for t in range(40):
            u = t / 39
            # Cubic bezier approximation
            mx1 = (a[0] + b[0]) / 2
            px = (1 - u) ** 3 * a[0] + 3 * (1 - u) ** 2 * u * mx1 + \
                 3 * (1 - u) * u ** 2 * mx1 + u ** 3 * b[0]
            py = (1 - u) ** 3 * a[1] + 3 * (1 - u) ** 2 * u * a[1] + \
                 3 * (1 - u) * u ** 2 * b[1] + u ** 3 * b[1]
            points.append((px, py))
        for i in range(len(points) - 1):
            d.line([points[i], points[i + 1]],
                     fill=hx(color) + (230,), width=3)

    # Connect: asset -> crop -> combine -> kickstarter & twitter
    wire(asset_nodes[0], crop_ins[0], "#4fc3f7")
    wire(asset_nodes[1], censor_ins[0], "#4fc3f7")
    wire(asset_nodes[2], overlay_ins[0], "#4fc3f7")
    wire(crop_outs[0], merge_ins[0], "#9cd34c")
    wire(censor_outs[0], merge_ins[1], "#ec7a8c")
    wire(overlay_outs[0], merge_ins[2], "#e8b050")
    wire(merge_outs[0], kick_ins[0], "#bb7bff")
    wire(merge_outs[0], patreon_ins[0], "#bb7bff")
    wire(merge_outs[0], twitter_ins[0], "#bb7bff")
    wire(merge_outs[0], fs_ins[0], "#bb7bff")

    # Floating 'run' button
    d.rounded_rectangle((W - 280, 140, W - 40, 196),
                          fill=(255, 150, 64, 255), radius=12)
    d.text((W - 240, 154), "RUN PIPELINE",
           fill=(24, 24, 30, 255), font=fnt(18, bold=True))
    d.text((W - 260, 180), "Ctrl+R",
           fill=(40, 30, 20, 220), font=fnt(12, bold=True))

    # Output preview
    d.rounded_rectangle((140, 900, 1410, H - 40),
                          fill=(26, 28, 36, 255),
                          outline=(80, 86, 102, 255), width=1, radius=8)
    d.text((160, 918), "run console",
           fill=(255, 150, 64, 255), font=fnt(13, bold=True))
    msgs = ["[OK]  boku_hero.psd -> crop -> combine -> kickstarter  (1.2s)",
            "[OK]  marty_final.psd -> censor -> combine -> patreon  (0.9s)",
            "[OK]  peach_sketch.psd -> overlay -> combine -> twitter  (0.7s)",
            "[OK]  combine -> /dist/kickstarter/hero.png  (0.3s)",
            "[  ]  waiting: user confirm before posting -> 'approve' or Esc"]
    for i, m in enumerate(msgs):
        d.text((170, 948 + i * 28), m,
               fill=(150, 230, 180, 255) if m.startswith("[OK]")
               else (240, 200, 130, 255),
               font=fnt(13, bold=True))

    save(img, "04_node_graph")


# ---------------------------------------------------------------------------
# PROTOCOL 5 - Card Stack (Tinder / Superhuman triage)
# ---------------------------------------------------------------------------

def protocol_5_card_stack():
    img = Image.new("RGBA", (W, H), (22, 22, 28, 255))
    d = ImageDraw.Draw(img)
    header(d, "Protocol 5  -  Card Stack / Triage",
           "One asset fills the screen. Swipe / press keys to act. Burn "
           "through a 500-asset import in 5 minutes. No grids, no menus. "
           "Blazing-fast sorting for people with no patience for panels.",
           "A = keep  -  D = skip  -  W = queue  -  S = ignore  -  "
           "T = tag  -  number keys for stars  -  Space to star-toggle",
           fg=(240, 240, 245, 255), acc="#ff457a", sub=(180, 185, 195, 255))

    # Current card (big, centered) + 3 peeking behind
    CARD_W = 820
    CARD_H = 900
    cx = (W - CARD_W) // 2
    cy = 168
    # Behind cards (stacked offset)
    for i, off in enumerate([(28, 16), (14, 8)]):
        dx, dy = off
        d.rounded_rectangle((cx + dx, cy + dy, cx + CARD_W + dx,
                               cy + CARD_H + dy),
                              fill=(40, 42, 54, 255),
                              outline=(60, 66, 80, 255), width=1, radius=22)

    # Front card
    d.rounded_rectangle((cx, cy, cx + CARD_W, cy + CARD_H),
                          fill=(56, 60, 74, 255),
                          outline=(120, 130, 150, 255), width=2, radius=22)
    # Fake asset area
    d.rounded_rectangle((cx + 18, cy + 18, cx + CARD_W - 18, cy + CARD_H - 200),
                          fill=(80, 88, 104, 255),
                          outline=(100, 110, 128, 255), width=1, radius=16)
    d.text((cx + 48, cy + 58),
           "<< asset preview >>",
           fill=(180, 190, 210, 255), font=fnt(16))

    # Asset metadata bar at card bottom
    mx = cx + 36
    my = cy + CARD_H - 176
    d.text((mx, my), "comfy_44199.png  -  Boku  -  1920x1920",
           fill=(255, 255, 255, 255), font=fnt(22, bold=True))
    d.text((mx, my + 32), "Imported Apr 22 15:14  -  boku, wip, color",
           fill=(180, 190, 210, 255), font=fnt(14))

    # Action zones around the card
    # Left zone - skip (red)
    d.polygon([(cx - 200, cy + 300), (cx - 40, cy + 300),
                 (cx - 40, cy + 600), (cx - 200, cy + 600)],
                fill=(80, 30, 34, 220))
    d.text((cx - 174, cy + 420), "SKIP",
           fill=(255, 100, 120, 255), font=fnt(32, bold=True))
    d.text((cx - 164, cy + 462), "D or <-",
           fill=(255, 160, 170, 255), font=fnt(14))
    # Right zone - keep (green)
    d.polygon([(cx + CARD_W + 40, cy + 300),
                 (cx + CARD_W + 200, cy + 300),
                 (cx + CARD_W + 200, cy + 600),
                 (cx + CARD_W + 40, cy + 600)],
                fill=(20, 80, 48, 220))
    d.text((cx + CARD_W + 60, cy + 420), "KEEP",
           fill=(120, 255, 180, 255), font=fnt(32, bold=True))
    d.text((cx + CARD_W + 70, cy + 462), "A or ->",
           fill=(170, 255, 200, 255), font=fnt(14))
    # Up zone - queue
    d.polygon([(cx + 100, cy - 90), (cx + CARD_W - 100, cy - 90),
                 (cx + CARD_W - 100, cy - 10), (cx + 100, cy - 10)],
                fill=(80, 50, 20, 220))
    d.text((cx + CARD_W // 2 - 80, cy - 70), "QUEUE",
           fill=(255, 220, 100, 255), font=fnt(24, bold=True))
    d.text((cx + CARD_W // 2 - 66, cy - 40), "W or up-arrow",
           fill=(255, 240, 160, 255), font=fnt(12))
    # Down zone - ignore
    d.polygon([(cx + 100, cy + CARD_H + 10),
                 (cx + CARD_W - 100, cy + CARD_H + 10),
                 (cx + CARD_W - 100, cy + CARD_H + 80),
                 (cx + 100, cy + CARD_H + 80)],
                fill=(60, 60, 60, 220))
    d.text((cx + CARD_W // 2 - 60, cy + CARD_H + 30), "IGNORE",
           fill=(200, 200, 200, 255), font=fnt(20, bold=True))

    # Progress bar bottom
    d.text((cx, H - 50), "47 / 212  -  avg 0.8s / card  -  streak: 11 kept",
           fill=(200, 210, 225, 255), font=fnt(14, bold=True))
    d.rectangle((cx, H - 28, cx + CARD_W, H - 20),
                  fill=(40, 44, 54, 255))
    pct = 47 / 212
    d.rectangle((cx, H - 28, cx + int(CARD_W * pct), H - 20),
                  fill=(255, 69, 122, 255))

    # Hotkey HUD top-right
    d.rounded_rectangle((W - 360, 140, W - 32, 420),
                          fill=(30, 32, 44, 255),
                          outline=(80, 86, 100, 255), width=1, radius=12)
    d.text((W - 342, 152), "KEYS",
           fill=(255, 69, 122, 255), font=fnt(14, bold=True))
    keys = [("A / ->", "keep"), ("D / <-", "skip"), ("W / Up", "queue"),
            ("S / Dn", "ignore"), ("T", "tag menu"), ("1-5", "set stars"),
            ("Space", "toggle star"), ("Z", "undo last"),
            ("/", "search / jump"), ("Esc", "exit triage")]
    for i, (k, v) in enumerate(keys):
        d.text((W - 340, 182 + i * 22), k.ljust(10) + v,
               fill=(220, 225, 235, 255), font=fnt(13, bold=False))

    save(img, "05_card_stack")


# ---------------------------------------------------------------------------
# Save + master
# ---------------------------------------------------------------------------

def save(img: Image.Image, name: str):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.png"
    img.save(path)
    print(f"wrote {path.relative_to(REPO_ROOT)}  ({img.width}x{img.height})")


def master_sheet():
    files = sorted(OUT_DIR.glob("*.png"))
    # Filter out the master itself if re-run
    files = [f for f in files if f.name != "master.png"]
    if not files:
        return
    THUMB_W = 1400
    tiles = []
    for p in files:
        i = Image.open(p)
        ratio = THUMB_W / i.width
        tiles.append((p.stem, i.resize((THUMB_W, int(i.height * ratio)),
                                         Image.LANCZOS)))
    gap = 20
    total_h = sum(t[1].height + gap + 20 for t in tiles) + 180
    total_w = THUMB_W + 60
    out = Image.new("RGBA", (total_w, total_h), (18, 18, 22, 255))
    d = ImageDraw.Draw(out)
    d.text((30, 18), "DoxyEdit  -  5 UI Protocols (interaction paradigms)",
           fill=(255, 255, 255, 255), font=fnt(40, bold=True))
    d.text((30, 68),
           "These are not color variants. Each row is a fundamentally "
           "different way to use the software.",
           fill=(180, 185, 200, 255), font=fnt(18))
    y = 140
    for name, img in tiles:
        d.text((30, y + 4), name.replace("_", " "),
               fill=(255, 180, 100, 255), font=fnt(22, bold=True))
        out.paste(img, (30, y + 36), img)
        y += img.height + 60
    out.save(OUT_DIR / "master.png")
    print(f"wrote {(OUT_DIR / 'master.png').relative_to(REPO_ROOT)}  "
          f"({out.width}x{out.height})")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    protocol_1_spatial()
    protocol_2_chat()
    protocol_3_spreadsheet()
    protocol_4_node_graph()
    protocol_5_card_stack()
    master_sheet()


if __name__ == "__main__":
    main()
