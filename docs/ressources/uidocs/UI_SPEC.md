# Shader Lab / Overlay UI Spec

DO NOT CHANGE these values without user approval.

## Shader Lab HUD (tools/shader_lab.rpy)

- Bar height: `max(8, int(8 * _SLAB_SCALE))` — matches original PsyAI 8px at 640
- Value width: `int(40 * _SLAB_SCALE)` — room for "-0.123"
- Bar width: `_lab_pw - _SLAB_VALUE_W - _lab_margin` (fills remaining space)
- Lab margin: 20 (frame padding 12 + scrollbar 6 + 2)
- Frame padding: `(6, 6)` — uniform
- Font sizes: `_SLAB_F_XS = max(7, int(7 * scale))`, `_SLAB_F_SM = max(8, int(8 * scale))`, `_SLAB_F_LG = max(10, int(10 * scale))`
- Slider layout: label on own line, hbox(bar + value) on next line
- Bar colors: DEFAULT Ren'Py theme (pink fill, grey bg) — do NOT override with Solid()
- Value text color: `#0c8` (green)
- Label color: `#0ae` (cyan)
- Section header color: `#068`
- Panel bg: `#0a0e12dd`
- Scrollbar: 6px thin, default colors, style_prefix "_sov"

## Overlay Panel (shader_overlay.rpy)

- Lab style bar height: `max(6, int(screen_height * 0.006))`
- Tray style bar height: `max(6, int(screen_height * 0.006))`
- Bar colors: DEFAULT Ren'Py theme — do NOT override
- Value text: from theme JSON `value_color` key (default `#0c8`)
- All text: must include `font "DejaVuSans.ttf"` explicitly

## Things NOT to change without asking

- Bar height ratio
- Font sizes
- Bar color source (Ren'Py defaults)
- Padding values
- Slider layout (label above, bar+value hbox below)
- Panel background color/opacity
