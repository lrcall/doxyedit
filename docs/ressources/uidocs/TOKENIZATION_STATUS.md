# DoxyEdit Tokenization Status

Last updated: 2026-04-15

## How Tokenization Works in DoxyEdit

### Architecture

DoxyEdit uses a **three-layer token system**:

1. **Theme dataclass** (`doxyedit/themes.py`) — single source of truth for all colors, alphas, pen widths, and semantic values. Every theme variant (Vinik 24, Soot, Neon, Bone, etc.) is an instance of this dataclass.

2. **QSS stylesheet generator** (`generate_stylesheet()` in `themes.py`) — converts Theme fields into Qt stylesheet rules using f-string interpolation. All QSS lives here, not on individual widgets.

3. **Widget metrics** (`_update_metrics()` on custom paint widgets) — derives all layout measurements from `font_size` using named ratios and named minimums. Called from both `__init__` and `set_theme()`.

### Where each type of value lives

| Value type | Location | Example |
|-----------|----------|---------|
| Colors (hex) | Theme dataclass field | `accent: str = "#be955c"` |
| Alpha/opacity | Theme dataclass field | `grid_badge_alpha: int = 220` |
| Pen widths | Theme dataclass field | `crop_border_width: int = 3` |
| Font family/size | Theme dataclass field | `font_family: str = "Segoe UI"` |
| Layout ratios | Named constant in `_update_metrics()` | `BADGE_RATIO = 1.2` |
| Layout minimums | Named constant in `_update_metrics()` | `MIN_PADDING = 4` |
| Derived pixel sizes | `self.` attribute from `_update_metrics()` | `self.badge_size = max(MIN_BADGE, int(font_size * BADGE_RATIO))` |
| QSS properties | `generate_stylesheet()` f-string | `padding: {pad}px {pad_lg}px;` |
| Overlay colors | Theme dataclass field (exception) | `crop_border: str = "#ffc850"` |

### Rules

1. **No stray arithmetic on font_size** — `font_size + 4` is a magic number. Use `int(font_size * RATIO)` with a named ratio.
2. **No abbreviated variable names** — `self.badge_size` not `_bs`. The name must explain what it IS.
3. **No fallback QColors** — init `self._theme` from `THEMES[DEFAULT_THEME]` in `__init__`. Never write `if theme else QColor(...)`.
4. **No inline setStyleSheet** — move to `generate_stylesheet()` with objectName selectors.
5. **Named minimums** — `max(MIN_PADDING, ...)` not `max(4, ...)`.
6. **Overlay exception** — censor rects, crop masks (fixed black overlays) may use hardcoded colors, but they still get tokenized as theme fields that don't vary per theme.

### Full rules in `/tokenize` skill

See `C:\Users\dikud\.claude\skills\tokenize\skill.md` — PySide6 / PyQt Rules section.

---

## Tokenization Status by File

### Fully Tokenized (0 violations)

| File | What was tokenized |
|------|--------------------|
| `studio.py` | All slider widths, icon button widths, margins, crop/note pen colors+widths, annotation colors, zoom factor. `_build()` uses `_dt.font_size`-derived locals. |
| `browser.py` (ThumbnailDelegate) | All paint measurements via `_update_metrics()` with 15 named ratios. All alphas from Theme fields. All colors from theme. Zero `QColor()` fallbacks. |
| `window.py` (Notes tab) | Markdown preview HTML/CSS — all padding, margins, line-heights, border-radii, font-family derived from `theme.font_size`. Editor viewport margins. Tab button sizes. |
| `main.py` | App font from `theme.font_family` + `theme.font_size` |
| `canvas.py` (EditableTextItem) | Font from theme tokens |
| `composer_left.py` (status dots) | Colors from `theme.success/warning/error`, font from `theme.font_size` |

### Partially Tokenized

| File | Done | Remaining violations |
|------|------|---------------------|
| `browser.py` (toolbar) | Tag button height ratio | `setFixedWidth(110)` zoom slider, `setFixedWidth(34)` zoom label |
| `preview.py` | Crop/note pens tokenized, dock button added, scene bg uses theme | `setFixedWidth(200)` crop combo, `setFixedWidth(28)` fullscreen btn, `QColor("#111")` 2x scene bg fallback |
| `composer_left.py` | Status dots + context menu tokenized | `setFixedHeight(22)` mode buttons, `setFixedWidth(14)` dot, `setFixedSize(48,48)` cell, `setFixedWidth(16)` icon |

### Not Yet Tokenized

| File | Violation count | Key violations |
|------|----------------|----------------|
| `calendar_pane.py` | 4 setFixed | Cell height 48, dot 6x6, nav buttons 28x28 |
| `composer_right.py` | 3 setFixed | Edit btn 40w, step label 48w, remove btn 24w |
| `checklist.py` | 3 setFixed | Progress bar 6h, add btn 60w, delete btn 20x20 |
| `kanban.py` | 2 setFixed + 2 QColor + stray arithmetic | Card height 56, dot 18w, drag preview colors, `font_size + 1` |
| `health.py` | 2 setFixed | Severity dots 12w |
| `gantt.py` | 1 setFixed + 10 QPen widths + 5 setAlpha | Zoom slider 120w, all pen widths inline, campaign/milestone alphas |
| `platforms.py` | 5 setFixed | Search 150w, toggle 80w, status 24x20, progress 200w |
| `stats.py` | 3 setFixed | Name label 180w, bar 12h, count label 90w |
| `infopanel.py` | 2 setFixed | Color swatch 20x20, separator line 1h |
| `timeline.py` | 1 setFixed | Icon 20w |
| `tagpanel.py` | 1 setFixed + 3 QColor | Dot 12x12, rubber-band selection colors |
| `tray.py` | 1 setFixed | Drag handle 16w |
| `overlay_editor.py` | 2 setFixed | Opacity/scale sliders 100w |
| `filebrowser.py` | 5 setAlpha | Hover/badge alpha values inline |

### Cross-file violations (not file-specific)

| Category | Count | Notes |
|----------|-------|-------|
| `setAlpha(N)` inline | ~13 | Should reference `theme.grid_*_alpha` fields |
| `QPen(color, N)` inline width | ~18 | Mostly in gantt.py, should use theme fields |
| `QColor(r,g,b)` non-exception | ~8 | canvas.py, kanban.py, tagpanel.py, preview.py |

---

## Priority Order for Remaining Work

1. **gantt.py** — highest violation count (16), most visible panel
2. **calendar_pane.py** — 4 violations, small file, quick win
3. **platforms.py** — 5 violations, user-facing panel
4. **tagpanel.py** — 4 violations including QColor
5. **composer_right.py** — 3 violations
6. **stats.py** — 3 violations
7. **checklist.py** — 3 violations
8. **kanban.py** — 4 violations including QColor + stray arithmetic
9. **Everything else** — 1-2 violations each, cleanup pass
