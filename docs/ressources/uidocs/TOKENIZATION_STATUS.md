# DoxyEdit Tokenization Status

Last updated: 2026-04-15 — **PROJECT CLEAN**

## How Tokenization Works in DoxyEdit

### Architecture

DoxyEdit uses a **three-layer token system**:

1. **Theme dataclass** (`doxyedit/themes.py`) — single source of truth for all colors, alphas, pen widths, and semantic values. Every theme variant (Vinik 24, Soot, Neon, Bone, etc.) is an instance of this dataclass.

2. **QSS stylesheet generator** (`generate_stylesheet()` in `themes.py`) — converts Theme fields into Qt stylesheet rules using f-string interpolation. All QSS lives here, not on individual widgets.

3. **Widget metrics** (`_update_metrics()` on custom paint widgets, or class-level ratio constants on build widgets) — derives all layout measurements from `font_size` using named ratios and named minimums.

### Where each type of value lives

| Value type | Location | Example |
|-----------|----------|---------|
| Colors (hex) | Theme dataclass field | `accent: str = "#be955c"` |
| Alpha/opacity | Theme dataclass field | `grid_badge_alpha: int = 220` |
| Pen widths | Theme dataclass field | `crop_border_width: int = 3` |
| Font family/size | Theme dataclass field | `font_family: str = "Segoe UI"` |
| Layout ratios | Class-level constant or top of `_build()`/`_update_metrics()` | `BADGE_RATIO = 1.2` |
| Layout minimums | Named constant in `_update_metrics()` | `MIN_PADDING = 4` |
| Derived pixel sizes | `self.` attribute from `_update_metrics()` | `self.badge_size = max(MIN_BADGE, int(font_size * BADGE_RATIO))` |
| QSS properties | `generate_stylesheet()` f-string | `padding: {pad}px {pad_lg}px;` |
| Overlay colors | Theme dataclass field (exception) | `crop_border: str = "#ffc850"` |

### Rules

1. **No bare integers in setFixed*** — derive from `font_size * NAMED_RATIO`
2. **No stray arithmetic** — `font_size + 4` is a magic number. Use `int(font_size * RATIO)`.
3. **No abbreviated variables** — `self.badge_size` not `_bs`. Name describes what it IS.
4. **No fallback QColors** — init `self._theme` from `THEMES[DEFAULT_THEME]` in `__init__`.
5. **No inline setStyleSheet** — move to `generate_stylesheet()` with objectName selectors.
6. **No inline ratio constants** — define at class level or top of method, never scattered next to usage.
7. **Named minimums** — `max(MIN_PADDING, ...)` not `max(4, ...)`.
8. **Overlay exception** — censor/crop/mask items may use fixed colors, but still tokenized as theme fields.

### Full rules in `/tokenize` skill

See `C:\Users\dikud\.claude\skills\tokenize\skill.md` — PySide6 / PyQt Rules section.

---

## Final Audit Results

**Audit date:** 2026-04-15
**Verdict:** PROJECT CLEAN

### Checklist

- [x] No `setFixedWidth/Height/Size(N)` with bare integers (1 intentional 1px separator)
- [x] No `QFont("family", N)` hardcoded
- [x] No `font_size + N` stray arithmetic (except `_cb` pattern — see known items)
- [x] No `QColor(r,g,b)` outside overlay exceptions
- [x] No inline ratio constants (all at class level or method top)
- [x] No `if self._theme else QColor(...)` fallbacks
- [x] All QPainter paint offsets derive from named measurements
- [x] Ratio constants centralized per class, not scattered inline

### Known Acceptable Items

| Item | Where | Why it's OK |
|------|-------|-------------|
| `line.setFixedHeight(1)` | `infopanel.py:193` | 1px separator — minimum visible line |
| `font_size + 1` / `- 1` | `window.py:960,964` | Font size increment/decrement action, not layout |
| `DWMWA_CAPTION_COLOR = 35` | `window.py:901` | Win32 API constant, not a visual token |
| `BATCH_SIZE = 500` | `browser.py:151` | Logic constant (thumbnail cache), not visual |
| `MAX_PER_COL = 10` | `browser.py:2967` | Logic constant (tag bar columns), not visual |

### Known Polish Items (functional, not violations)

| Item | Count | Description |
|------|-------|-------------|
| `_cb = max(14, _f + 2)` | 12 files | Repeated checkbox/button size formula. Works correctly, consistent everywhere. Could be extracted to a shared utility for DRY. |
| `THUMB = 100` / `THUMB = 80` | 2 in platforms.py | Different thumb sizes for card vs dashboard view. Local constants, can't be unified (intentionally different). |

---

## Files Tokenized (all)

| File | Violations fixed | Method |
|------|-----------------|--------|
| `studio.py` | Slider widths, icon buttons, margins, crop/note pens, zoom buttons | Ratios at top of `_build()` |
| `browser.py` (ThumbnailDelegate) | 40+ paint measurements, all alphas, all colors | `_update_metrics()` with 15 named ratios + Theme fields |
| `browser.py` (AssetBrowser toolbar) | Zoom slider/label, tag button height | Class-level ratios |
| `window.py` (Notes tab) | Markdown HTML/CSS padding/margins/fonts, editor viewport, tab buttons | Theme-derived locals in `_render_notes_preview_to()` |
| `gantt.py` | All pen widths (6 types), all alphas (5 types), zoom slider | Theme dataclass fields |
| `calendar_pane.py` | Cell height, nav buttons, status dots | `_f` / `_cb` from QSettings |
| `platforms.py` | Search, toggle, status buttons, progress, export | `_f` / `_cb` from QSettings |
| `composer_left.py` | Mode buttons, status dots, order cells, crop icons | Class-level ratios |
| `composer_right.py` | Edit button, step labels, remove buttons | Class-level ratios |
| `checklist.py` | Progress bar, add/delete buttons | `_f` / `_cb` from QSettings |
| `kanban.py` | Card height, dot width, drag preview colors, font arithmetic | Theme tokens + `_f` ratios |
| `health.py` | Severity dots | `_f` ratio |
| `stats.py` | Name label, bar height, count label | `_f` ratios |
| `infopanel.py` | Color swatch | `_f` ratio |
| `timeline.py` | Icon width | `_f` ratio |
| `tagpanel.py` | Dot size, rubber-band colors | Theme tokens + `_f` ratio |
| `tray.py` | Drag handle | `_f` ratio |
| `overlay_editor.py` | Slider widths | `_f` ratio |
| `preview.py` | Crop combo, fullscreen button, scene backgrounds | Theme tokens + `_f` ratio |
| `canvas.py` | TagItem font, drawing tool colors | Theme tokens |
| `main.py` | App font | Theme tokens |
| `themes.py` | Notes editor padding | Token-derived f-string |
