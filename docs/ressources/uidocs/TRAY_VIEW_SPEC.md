# Tray View GUI Specification

Complete visual specification for the shader overlay tray view (the view with pink bars).
This is the primary in-game shader editor. All values documented as-built.

## Identity

- **View name**: Tray
- **Purpose**: Compact paged shader parameter editor, one shader group at a time
- **Trigger**: F1 opens overlay, F2 cycles between Lab/Tray views
- **Close**: ✕ button cycles back to Lab view; F1 closes overlay entirely

## Layout Structure

```
┌─────────────────────────────┐
│ ◀  CRT  ▶  OVR  ✕          │  ← Header row
│ Active: ON                  │  ← Toggle row
│ Barrel                      │  ← Param label
│ ████████████░░░░ 0.000      │  ← Bar + value
│ Phosphor                    │
│ ██░░░░░░░░░░░░░ 0.050      │
│ ...                         │
└─────────────────────────────┘
```

## Current Token Values (at 2560x1440, _SLAB_SCALE = 4.0)

### Panel Frame
| Property | Token | Value at 2560 |
|----------|-------|--------------|
| Width | `_sov_panel_width` (draggable) | 17% of screen = ~435px |
| Height | `config.screen_height` | 1440 (full height) |
| Background | `_SLAB_C_PANEL_BG` | `#0a0e12f0` (dark, 94% opacity) |
| Padding | `_SLAB_PAD` | 2px |
| Anchor | hardcoded | `xalign 1.0 yalign 0.0` (top-right) |

### VBox Spacing
| Property | Token | Value |
|----------|-------|-------|
| Main vbox spacing | `_SLAB_SPACING` | -2 (negative, overlapping) |
| Text line_spacing | `_SLAB_LINE_SPACING` | -4 (tighter than font default) |

### Font
| Property | Token | Value |
|----------|-------|-------|
| Font family | `_SLAB_FONT` | `"DejaVuSans.ttf"` |
| Body kerning | `_SLAB_KERNING` | 0 |
| Title kerning | `_SLAB_KERNING_TITLE` | 1 |

### Font Sizes (tray applies 0.8x scale)
| Size | Base token | Tray formula | Value at 2560 |
|------|-----------|-------------|--------------|
| XS | `_SLAB_F_XS` (28) | `max(7, 28 * 0.8)` | 22 |
| SM | `_SLAB_F_SM` (32) | `max(7, 32 * 0.8)` | 25 |
| LG | `_SLAB_F_LG` (40) | `max(8, 40 * 0.8)` | 32 |

### Colors
| Element | Token | Hex |
|---------|-------|-----|
| Page title (CRT, DITH, etc.) | `_SLAB_C_TITLE` | `#0ae` |
| Param labels | `_SLAB_C_LABEL` | `#0ae` |
| Param values | `_SLAB_C_VALUE` | `#0c8` (green) |
| Bar fill | Ren'Py default | Pink (from gui/bar/ images) |
| Bar background | Ren'Py default | Grey (from gui/bar/ images) |
| Active/ON button | `_SLAB_C_BTN_ACTIVE` | `#0f0` |
| OFF/danger button | `_SLAB_C_BTN_DANGER` | `#f44` |
| Hover (all) | `_SLAB_C_BTN_HOVER` | `#fff` |
| Inactive text | `_SLAB_C_INACTIVE` | `#555` |
| Disabled controls | `_SLAB_C_DISABLED` | `#222` |

### Header Row
| Element | Font | Size | Color | Action |
|---------|------|------|-------|--------|
| ◀ arrow | Image `arrow_right_24.png` | 24px | cyan/white hover | `_sov_tray_prev` |
| Page name | `_SLAB_FONT` | `_f_sm` | `_SLAB_C_TITLE` | — |
| ▶ arrow | Image `arrow_left_24.png` | 24px | cyan/white hover | `_sov_tray_next` |
| OVR/EDIT | `_SLAB_FONT` | `_f_xs` | danger/active | `_sov_toggle_override` |
| ✕ | `_SLAB_FONT` | `_f_sm` | `_SLAB_C_BTN_DANGER` | `_sov_cycle_theme` (back to lab) |

**Note**: Arrow images are currently swapped (right.png = prev, left.png = next) to fix direction issue.

### Active Toggle Row
| Element | Font | Size | Color |
|---------|------|------|-------|
| "Active:" label | `_SLAB_FONT` | `_f_sm` | `_SLAB_C_LABEL` |
| ON/OFF button | `_SLAB_FONT` | `_f_sm` | active/danger |

Both elements `yalign 0.5` in hbox, `spacing _SLAB_HSPACE`.

### Param Slider Row (per parameter)
```
label text (one line)
[bar██████░░░░░] [0.000] (hbox, one line)
```

| Element | Property | Token/Value |
|---------|----------|-------------|
| Label | font | `_SLAB_FONT` |
| Label | size | `_f_sm` |
| Label | color | `_SLAB_C_LABEL` |
| Label | line_spacing | `_SLAB_LINE_SPACING` |
| Bar | height | `_SLAB_TRAY_BAR_H` = `max(14, screen_h * 0.014)` = ~20px |
| Bar | width | `_pw - _t_val_w - _t_margin` (fills remaining space) |
| Bar | colors | Ren'Py default (pink fill, grey bg) |
| Value text | font | `_SLAB_FONT` |
| Value text | size | `_f_sm` |
| Value text | color | `_SLAB_C_VALUE` |
| Value text | width | `max(40, _pw * 0.15)` |
| Hbox spacing | | `_SLAB_HSPACE_BAR` = `max(4, 4 * scale)` = 16px |

### Hardcoded Values Still in Tray (NOT tokenized)
| Line | Value | What it is |
|------|-------|-----------|
| 456 | `0.8` | Font scale multiplier (should be `_SLAB_TRAY_FONT_SCALE`) |
| 460 | `16` | Tray margin (should derive from `_SLAB_PAD` + `_SLAB_SCROLLBAR_W` + `_SLAB_SCROLLBAR_PAD`) |
| 464 | `_th.get("panel_padding", 4)` | Still reads from JSON theme, should use `_SLAB_PAD` |
| 534 | `null height 2` | Hardcoded gap after Active toggle |
| 483, 493 | `"images/ui/arrow_right_24.png"` | Hardcoded path, should use `_SLAB_ARROW_R` / `_SLAB_ARROW_L` |

### What Works
- Pink bars (Ren'Py default gui theme)
- Green value text
- Cyan labels
- Arrow navigation between shader groups
- OVR/EDIT mode toggle
- ✕ cycles back to lab view
- Active ON/OFF toggle per shader layer
- Bars are draggable, values display live
- Panel resizable via drag handle
- Full-height background with 94% opacity

### What Needs Work
- Arrows still facing wrong direction (workaround: swapped file references)
- Font scale `0.8` not from token
- Tray margin `16` not from token
- `null height 2` hardcoded
- No scrollbar on tray (content clips if many params)
- No save/load presets in tray view
- Value text not clickable for manual entry (lab view has this)
- Section titles not shown (tray skips them, goes straight to params)
