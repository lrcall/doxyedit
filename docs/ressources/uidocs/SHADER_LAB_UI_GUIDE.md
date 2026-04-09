# Shader Lab UI Guide — Lessons From 4 Days of Fighting

## Quick Start: New Ren'Py Project

If you're starting fresh and want a shader tool with a tight UI, do these 6 things in order before writing any screen code:

### 1. Define your scale factor
```python
init -5 python:
    _SLAB_SCALE = config.screen_width / 640.0  # 640 = your baseline
```

### 2. Define ALL design tokens
```python
    # Sizes (scale these)
    _SLAB_BAR_H = max(8, int(8 * _SLAB_SCALE))
    _SLAB_VALUE_W = max(50, int(30 * _SLAB_SCALE))
    _SLAB_F_SM = max(8, int(8 * _SLAB_SCALE))
    _SLAB_OVERLAY_W = min(int(220 * _SLAB_SCALE), 300)

    # Spacing (NEVER scale these)
    _SLAB_PAD = 8
    _SLAB_SEP_H = 1
    _SLAB_HEADER_BOTTOM_PAD = 5
    _SLAB_PARAM_GAP = -4

    # Colors
    _SLAB_C_BTN = "#aaa"
    _SLAB_C_BTN_ACTIVE = "#0f0"
    _SLAB_C_BTN_WARN = "#f80"
    _SLAB_C_SEP = "#333"
    _SLAB_C_MUTED = "#666"
    _SLAB_C_SELECTED = "#ff0"

    # Font
    _SLAB_FONT = "DejaVuSans.ttf"
    _SLAB_KERNING = 0
```

### 3. Define styles with a shared prefix
```python
init 1 python:
    style._sov_text = Style(style.default)
    style._sov_text.font = _SLAB_FONT
    style._sov_text.size = _SLAB_F_SM
    style._sov_text.kerning = _SLAB_KERNING
    style._sov_text.color = _SLAB_C_BTN

    style._sov_button = Style(style.default)
    style._sov_button.padding = (4, 2, 4, 2)

    style._sov_button_text = Style(style._sov_text)
    style._sov_button_text.hover_color = "#fff"

    style._sov_bar = Style(style.default)
    style._sov_bar.ysize = _SLAB_BAR_H
    style._sov_bar.left_bar = Solid("#e066a3")
    style._sov_bar.right_bar = Solid("#333")
    style._sov_bar.thumb = None

    # CRITICAL: define scrollbar style or viewports render blank
    style._sov_viewport_vscrollbar = Style(style.vscrollbar)
    style._sov_viewport_vscrollbar.base_bar = Solid("#222")
    style._sov_viewport_vscrollbar.thumb = Solid("#555")
```

### 4. Build shared components as screens (single top-level container each)
```renpy
screen _sov_param_slider(key, label, bar_w):
    vbox:
        text label style "_sov_text" color _SLAB_C_MUTED
        null height _SLAB_PARAM_GAP
        hbox:
            bar value FieldValue(store, "_slab_" + key, _SHADER_REGISTRY[key]["max"],
                offset=_SHADER_REGISTRY[key]["min"], step=_SHADER_REGISTRY[key]["step"]):
                xsize bar_w
            textbutton "{:.2f}".format(getattr(store, "_slab_" + key)):
                xsize _SLAB_VALUE_W
                text_color _SLAB_C_BTN
```

### 5. Use `style_prefix` on every container, never per-element overrides
```renpy
screen my_shader_panel():
    frame:
        style_prefix "_sov"
        # Everything inside inherits _sov styles
        vbox:
            text "TITLE"  # uses _sov_text automatically
            use _sov_param_slider("my_param", "My Param", 200)
```

### 6. Use an init flag for one-time setup, NOT `on "show"`
```renpy
screen my_tool():
    if not store._my_tool_initialized:
        $ store._my_tool_state = "default"
        $ store._my_tool_initialized = True
    on "hide" action SetVariable("_my_tool_initialized", False)
```

**That's it.** Follow this order and you get a tight, consistent, scalable UI from the first commit. Everything after this is just adding content to the framework.

This document captures every hard-won UI decision from the shader lab port so the next shader tool doesn't take 4 days to get right. These aren't suggestions — they're rules derived from bugs, broken layouts, and wasted iterations.

## The Golden Rule

**Build the tray view first. Lock it. Build everything else to match.**

The tray view (pink sliders, compact layout) was designated the gold standard early but we iterated both views independently anyway. Every time we changed one, the other drifted. Lock the reference view before writing a second line of code.

## Screen Architecture

### Style System (do this FIRST)
Define all styles imperatively at `init 1` with a shared prefix:

```python
init 1 python:
    style._sov_text = Style(style.default)
    style._sov_text.font = "DejaVuSans.ttf"
    style._sov_text.size = max(8, int(8 * _SLAB_SCALE))
    style._sov_text.kerning = 0
    style._sov_text.color = "#aaa"
    # ... button, bar, frame, vbox, hbox, scrollbar
```

Then apply `style_prefix "_sov"` to every container. **Never set font/size/kerning on individual elements.** If you're writing `font "DejaVuSans.ttf"` on a text element, you've already failed.

### Design Tokens (do this SECOND)
All magic numbers go into named constants at init time:

```python
_SLAB_SCALE = config.screen_width / 640.0   # baseline scale
_SLAB_PAD = 8                                # frame padding (DON'T scale)
_SLAB_BAR_H = max(8, int(8 * _SLAB_SCALE))  # slider bar height
_SLAB_VALUE_W = max(50, int(30 * _SLAB_SCALE))  # value button width
_SLAB_C_BTN_ACTIVE = "#0f0"                  # active button color
_SLAB_C_SEP = "#333"                         # separator color
_SLAB_FONT = "DejaVuSans.ttf"
_SLAB_F_SM = max(8, int(8 * _SLAB_SCALE))
```

**CRITICAL: Never scale spacing tokens.** Spacing that's 2px at 640 becomes 8px at 2560, making layouts too loose. Keep spacing as small fixed values (2-8px). Only scale font sizes, bar heights, and widget widths.

### Shared Components (do this THIRD)
Extract every repeated pattern into a `use`-able screen:

- `_sov_param_slider(key, label, bar_w)` — one slider row
- `_sov_section_params(sections, bar_w)` — section header + slider list
- `_sov_layer_row(si, se, arrow_w)` — stack layer with arrows/toggle/delete/name
- `_sov_add_layer_buttons(sep_w)` — grid of add-layer buttons

**Every shared screen must have a single top-level vbox/hbox.** Ren'Py's `use` wraps multiple top-level children in an implicit `fixed`, which breaks layout flow.

## Resolution Independence

### What to scale
- Font sizes: `max(8, int(8 * _SLAB_SCALE))`
- Bar heights: `max(8, int(8 * _SLAB_SCALE))`
- Widget widths: `int(N * _SLAB_SCALE)`
- Frame/modal widths: `min(int(N * _SLAB_SCALE), CAP)` — always cap modals

### What NOT to scale
- Spacing/padding: keep fixed (2-8px)
- Separator heights: 1-2px always
- Arrow button sizes: derive from font size, not screen size

### Modal Dialogs
Always cap modal width: `_SLAB_OVERLAY_W = min(int(220 * _SLAB_SCALE), 300)`. Without the cap, a value input dialog becomes 880px wide at 2560x1440.

## Screen Lifecycle Gotchas

### Never use `_screen_tick` on `overlay_screens`
`config.overlay_screens` re-evaluate every frame automatically. Adding `use _screen_tick` (timer-driven ForceRedraw) doubles the redraw pressure and causes severe slider drag lag. The ATL transforms (`pause 0 / repeat`) already drive visual updates. Only use `_screen_tick` on normal `show_screen` screens that need continuous animation.

### `on "show"` fires every `restart_interaction`
It is NOT a one-time init event. Any code in `on "show"` runs every time the screen redraws, which includes:
- `renpy.restart_interaction()` calls
- Any `Function()` action that modifies variables
- Timer ticks

**Fix:** Use a flag guard:
```renpy
if not store._slab_initialized:
    $ store._slab_render_mode = "element"
    $ store._slab_stack = []
    $ store._slab_initialized = True
on "hide" action SetVariable("_slab_initialized", False)
```

### `modal True` eats all input
A modal screen captures all keyboard and mouse input. Key handlers inside the screen work, but nothing below the screen in the zorder stack can receive input. If you need keys to work on the overlay AND the lab, both screens need their own `key` statements.

### `style_prefix` propagates into `use`
Child screens inherit the parent's style prefix. But if the child's elements have explicit style overrides, those win. This is usually what you want — but watch out for scrollbars, which look for `{prefix}_viewport_vscrollbar`. You must define this style or scrollbars render blank.

## Layer List (Stack UI)

### Display Order
Forward order: index 0 at top, highest index at bottom. This is Photoshop convention — top of list = outermost layer (renders last, on top), bottom = innermost (closest to content).

### Arrow Direction
▲ moves layer to lower index (up in list = more outermost). ▼ moves to higher index (down = more innermost). The arrows move the layer in the direction they point in the visual list, NOT in array index direction.

### Group Labels
Stack groups have internal names (`constellat`, `odither`) that are too long for buttons. Use a label map:
```python
_SLAB_GROUP_LABELS = {
    "dither": "DITH", "mosaic": "MOSAC", "odither": "ODITH",
    "kawase": "KAWSE", "constellat": "CNSTL", ...
}
def _sr_group_label(group):
    return _SLAB_GROUP_LABELS.get(group, group.upper())
```
Call `_sr_group_label()` everywhere you display a group name — add-layer buttons, layer rows, HUD headers. **Never call `.upper()` directly on group names.**

## Shader Parameter Conventions

### Slider Values Must Be Integer-Snapped in the Shader
Ren'Py slider bars allow continuous dragging even with `step=1.0`. The slider shows 2.3 but the shader needs 2. **Always `floor(uniform + 0.5)` in the GLSL** for params that must be integer (groups, modes, toggles, scale factors).

### Toggle Params
Use float 0.0/1.0 with step 1.0. In shader: `bool flag = uniform > 0.5;` with `floor()` for safety: `bool flag = floor(uniform + 0.5) > 0.5;`

### Power-of-2 Scale
For scaling params (dither scale, mosaic), use exponent as the slider value:
- Slider range: 0-8, step 1
- Shader: `float bs = pow(2.0, floor(uniform + 0.5));`
- Result: 1, 2, 4, 8, 16, 32, 64, 128, 256

## Coordinate Systems (Shader Side)

### The Split Approach (hard-won)
- **`gl_FragCoord.xy`** — 1:1 with actual screen fragments. Use for dither patterns, noise grids, anything that needs pixel-perfect alignment. BUT: origin is bottom-left, and maps to drawable pixels (not virtual resolution).
- **`v_tex_coord`** — 0 to 1 normalized. Use for texture sampling. Maps correctly to the displayable's UV space regardless of resolution.
- **`u_model_size`** — virtual resolution of the displayable. NOT the same as drawable pixel count when the window is scaled.

**Never divide `gl_FragCoord` by `u_model_size`** — they're in different coordinate spaces (drawable vs virtual). This causes 120% zoom and position offset.

**The pattern that works:**
```glsl
// Cell grid from screen pixels (even cells)
vec2 cell = floor(gl_FragCoord.xy / block_size);

// Texture sample from UV space (correct position)
vec2 uv = v_tex_coord;  // scale 1
// or for scaled:
vec2 uv = (floor(v_tex_coord * u_model_size / bs) * bs + bs * 0.5) / u_model_size;
```

### `nearest True` on Transforms
Required for any pixelation/mosaic shader. Forces GL_NEAREST on the mesh FBO texture. Without it, bilinear filtering creates seam artifacts between pixel blocks. This was the mosaic seam fix — not shader math, not UV snapping.

## Scene Transitions

### Deferred Preset Loading
`show_layer_at` applies transforms to the entire master layer. During a dissolve, both old and new scene images render through the SAME shader stack. To avoid shader pop during transitions:

```python
_scene_load_preset("scene_name", defer=True)  # stash, don't apply
# ... scene transition with dissolve ...
_scene_apply_preset()  # apply after dissolve completes
```

The old shader stack stays active during the dissolve. New stack pops in after.

### Known Limitation
True per-scene shader crossfade (scene A with stack A dissolving into scene B with stack B, both visible simultaneously with their own shaders) is not possible with `show_layer_at`. Would require rendering each scene to separate FBOs. Documented workaround: Flatten outgoing scene (shaders baked in), swap stack, dissolve flattened image out over live new scene.

## Future Architecture: Self-Contained Shader Files

Currently, adding a shader requires editing 6 locations across 3 files (shader .rpy, shader_registry.rpy, shader_lab.rpy). The registry params and HUD sections should live WITH the shader, not in central files.

**Goal**: each shader .rpy file should declare everything about itself:
- `renpy.register_shader()` — the GLSL code
- `_sr_register()` calls — param defaults, ranges, groups
- `_SLAB_PARAM_SECTIONS` entry — HUD slider layout
- `_SLAB_STACK_GROUPS` entry — stack group name
- `_SLAB_STACK_TRANSFORM_MAP` entry — transform mapping
- `_SLAB_GROUP_REGISTRY_MAP` entry — param group mapping
- `_SLAB_GROUP_LABELS` entry — display name
- `_SLAB_MODES` entry — ELEM/SCREEN mode button
- `_SLAB_TRANSFORMS` entry — ELEM/SCREEN transform
- ATL updater function + transform definition

**How**: each shader file appends to shared dicts/lists at init time instead of the central files defining everything. Example:

```python
# In fx_grain.rpy — everything about grain lives here
init -5 python:
    _sr_register("fx_grain_strength", 0.1, 0.0, 0.5, 0.01, "grain", "Strength")
    _sr_register("fx_grain_size", 1.0, 1.0, 8.0, 1.0, "grain", "Size")

init -3 python:
    _SLAB_STACK_GROUPS.append("grain")
    _SLAB_STACK_TRANSFORM_MAP["grain"] = "_slab_grain_live"
    _SLAB_GROUP_REGISTRY_MAP["grain"] = ["grain"]
    _SLAB_GROUP_LABELS["grain"] = "GRAIN"
    _SLAB_MODES.append(("grain", "GRAIN"))
    _SLAB_TRANSFORMS["grain"] = "_slab_grain_live"
    _SLAB_PARAM_SECTIONS["grain"] = [("FILM GRAIN", [("fx_grain_strength", "Strength"), ("fx_grain_size", "Size")])]
```

This way, adding or removing a shader is a single file operation. No touching shader_lab.rpy or shader_registry.rpy. The `/add-shader` command would generate a complete self-contained file.

**Not done yet** — current codebase still uses the central-registry pattern. Migrate when doing the backport to PsyAI main.

## What We Tried and Failed

### Accumulation Motion Blur
Attempted 4 approaches (screenshot feedback, DynamicDisplayable, interact_callback + Flatten, timer + Flatten rebuild). All failed because Ren'Py shaders have no access to previous frame data, and screen output can't be Flatten'd from within itself. The echo trail shader (`fx_echo`) is the single-shader alternative.

### `on "show"` for Init
Fires every redraw, not once. Caused Ctrl+H to reset the entire screen state.

### `v_tex_coord * u_model_size` for Pixel Grids
Causes moiré at scale 1 and uneven pixel blocks at larger scales due to virtual/drawable resolution mismatch. Use `gl_FragCoord` for pixel grids.

### Scaling Spacing Tokens
2px spacing at 640 becomes 8px at 2560. Layouts look like a loose wireframe. Keep spacing fixed.
