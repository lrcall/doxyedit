# Overlay UI — Locked Specification

DO NOT CHANGE without explicit user approval.

## Architecture

- **Styles defined once** in `shader_overlay.rpy` `init 1 python:` block
- **`style_prefix "_sov"`** on both panel frames — all children inherit
- **Shared screens** (`_sov_param_slider`, `_sov_section_params`, `_sov_layer_row`, `_sov_add_layer_buttons`) — single top-level vbox each, used by both views
- **`side_spacing`** on lab viewport for scrollbar clearance
- **No per-element font/size/kerning overrides** — only color overrides where element differs from base

## Style Family (`_sov_*`)

| Style | Inherits | Key properties |
|-------|----------|---------------|
| `_sov_frame` | `frame` | bg: `_SLAB_C_PANEL_BG`, padding: `(SCROLLBAR_W*2, PAD, PAD, PAD)` |
| `_sov_vbox` | `vbox` | spacing: `_SLAB_SPACING` (0) |
| `_sov_text` | `text` | font: `_SLAB_FONT`, size: `F_SM*0.8`, kerning: 0, color: `_SLAB_C_LABEL`, line_spacing: 0, line_leading: 0 |
| `_sov_header_text` | `_sov_text` | kerning: 1, color: `_SLAB_C_SECTION`, line_spacing: `_SLAB_HEADER_LINE_SPACING` |
| `_sov_button` | `button` | padding: 0, margin: 0, bg: None |
| `_sov_button_text` | `button_text` | font: `_SLAB_FONT`, size: `F_SM*0.8`, kerning: 0, color: `_SLAB_C_BTN`, hover: `_SLAB_C_BTN_HOVER` |
| `_sov_bar` | `bar` | ysize: `_SLAB_TRAY_BAR_H` |
| `_sov_hbox` | `hbox` | spacing: `_SLAB_HSPACE` |
| `_sov_viewport_vscrollbar` | `vscrollbar` | xsize: `_SLAB_SCROLLBAR_W`, base_bar: `gui/bar/right.png`, thumb: `gui/bar/left.png` |

## Token Values (locked)

### Spacing
| Token | Value | Purpose |
|-------|-------|---------|
| `_SLAB_SPACING` | 0 | Main vbox spacing |
| `_SLAB_LINE_SPACING` | 0 | Text line_spacing |
| `_SLAB_HEADER_LINE_SPACING` | 0 | Header text line_spacing |
| `_SLAB_HEADER_BOTTOM_PAD` | 5 | null height after headers |
| `_SLAB_PARAM_GAP` | -4 | Spacing inside param slider vbox (label to bar) |
| `_SLAB_HSPACE` | scaled `max(2, 2*scale)` | Horizontal between inline elements |
| `_SLAB_HSPACE_BAR` | 4 (fixed) | Gap between bar and value in hbox |
| `_SLAB_HSPACE_LAYER` | 0 | Layer row hbox (arrows handle gaps) |
| `_SLAB_HSPACE_HEADER` | scaled `max(4, 4*scale)` | Between header buttons |

### Frame
| Token | Value | Purpose |
|-------|-------|---------|
| `_SLAB_PAD` | 2 | Frame padding (top, bottom, right) |
| Left padding | `_SLAB_SCROLLBAR_W * 2` (12) | Left inset |
| Right padding | `_SLAB_PAD` (2) | Right inset |
| `_SLAB_SCROLLBAR_W` | 6 | Scrollbar width |
| `_SLAB_SCROLLBAR_PAD` | 4 | side_spacing on viewport |

### Sizing
| Token | Value at 4x | Purpose |
|-------|-------------|---------|
| `_SLAB_TRAY_BAR_H` | `max(14, screen_h*0.014)` ~20px | Bar height |
| `_SLAB_VALUE_W` | `max(50, 30*scale)` = 120px | Value text width (fixed, not panel-relative) |
| `_SLAB_TRAY_FONT_SCALE` | 0.8 | Font multiplier for overlay |
| `_SLAB_ARROW_W_RATIO` | 2.5 | Arrow button width = font_size * this |

### Colors
| Token | Hex | Element |
|-------|-----|---------|
| `_SLAB_C_PANEL_BG` | `#0a0e12f0` | Panel background |
| `_SLAB_C_LABEL` | `#0ae` | Param labels |
| `_SLAB_C_VALUE` | `#0c8` | Value numbers (green) |
| `_SLAB_C_TITLE` | `#0ae` | Page title |
| `_SLAB_C_SECTION` | `#068` | Section headers |
| `_SLAB_C_BTN` | `#8cf` | Default buttons |
| `_SLAB_C_BTN_HOVER` | `#fff` | All hover |
| `_SLAB_C_BTN_ACTIVE` | `#0f0` | ON/enabled |
| `_SLAB_C_BTN_DANGER` | `#f44` | OFF/delete/close |
| `_SLAB_C_BTN_WARN` | `#fa0` | Arrows |
| `_SLAB_C_SELECTED` | `#ff0` | Selected layer |
| `_SLAB_C_DISABLED` | `#222` | Greyed arrows |
| `_SLAB_C_INACTIVE` | `#555` | Inactive text |
| `_SLAB_C_SEP` | `#035` | Separator lines |
| Bar fill | `gui/bar/left.png` | Pink (Ren'Py default) |
| Bar bg | `gui/bar/right.png` | Grey (Ren'Py default) |
| Scrollbar thumb | `gui/bar/left.png` | Matches bar fill |
| Scrollbar base | `gui/bar/right.png` | Matches bar bg |

### Font
| Token | Value |
|-------|-------|
| `_SLAB_FONT` | `"DejaVuSans.ttf"` |
| `_SLAB_KERNING` | 0 |
| `_SLAB_KERNING_TITLE` | 1 |

## Content width formula

```
_content_w = _pw - (_SLAB_SCROLLBAR_W * 2) - _SLAB_PAD
_bar_w = _content_w - _SLAB_VALUE_W - _SLAB_HSPACE_BAR
```

No panel-width-relative values. All fixed from tokens.

## What to push to shader lab

The shader lab (`tools/shader_lab.rpy`) HUD panel needs:
1. `style_prefix "_sov"` on its frame
2. Remove all per-element `text_font`, `text_size`, `text_kerning`, `text_color`, `text_hover_color`
3. Use `side_spacing` on its viewport
4. Use shared `_sov_param_slider` / `_sov_section_params` for its param sliders
5. Match the content width formula
6. Keep its own header (SHADER LAB title, mode selector, exit button) — those are lab-specific
