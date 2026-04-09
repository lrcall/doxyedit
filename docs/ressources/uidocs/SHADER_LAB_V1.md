# Shader Lab v1.0 — Official Release Lock

**Locked: 2026-04-08**

## What This Covers

This document locks the shader lab system as v1.0. All features below are considered stable and should not be removed or restructured without deliberate versioning.

## Views

| View | Theme Key | Access | Purpose |
|------|-----------|--------|---------|
| Tray | `tray` | Backtick (`) | Per-shader editing with pager, per-shader presets |
| Solo/Lab | `lab` | SOLO button from Tray | Full stack management: layers, reorder, add/remove, stack presets |
| Shader Lab | — | F1 | Standalone modal shader test scene (ELEM/SCREEN/STACK modes) |

## Shader Inventory (24 shaders)

### Post-Process (read tex0, modify, output)
| ID | Label | Group | Params |
|----|-------|-------|--------|
| CRT | CRT | crt + pulse | 14 (barrel, phosphor, scanline, border, RGB offset, convergence) |
| CLUM | CLUM | clum | 9 (mask type, curve, offset, brightness, sharpness, scale) |
| DITH | DITH | dither | 10 (mode, palette, levels, mosaic, brightness, contrast, gamma) |
| MOSAC | MOSAC | mosaic | 1 (block size) |
| ODITH | ODITH | odither | 3 (scale, groups, bayer 4x4) |
| BWDTH | BWDTH | bwdith | 2 (scale, bias) |
| KAWSE | KAWSE | kawase | 2 (offset, passes) |
| COLOR | COLOR | clradj | 13 (hue, sat, lum, colorize, bright, contrast, depth, invert, tint RGB, tint strength, tint mode) |
| EDGE | EDGE | edge | 5 (strength, threshold, mix, invert, blend mode) |
| GRAIN | GRAIN | grain | 3 (strength, size, lum response) |
| ECHO | ECHO | echo | 8 (echoes, distance, angle, decay, tint RGB, animate) |
| GLTCH | GLTCH | glitch | 11 (chance, speed, density, strength, shake, chroma, noise, flash, scan drop, warp, flip) |
| VHS | VHS | vhs | 4 (color mult, black mult, offset, blur) |
| WAVE | WAVE | wave | 3 (amplitude, frequency, speed) |
| FISHE | FISHE | fisheye | 7 (radius, drift amount/speed/zoom/phase, center XY) |
| BLUR | BLUR | blur | 2 (strength, mask radius) |
| SHINE | SHINE | shine | 7 (progress, size, angle, alpha, color RGB) |
| HIT | HIT | hit | 9 (effect, shake, flash speed, wind amp/speed/pivot, color RGB) |
| PXDLV | PXDLV | pxdslv | 5 (progress, strength, pixels, alpha threshold, square px) |
| G2A | G2A | alpha (g2a) | 7 (opacity, invert, blend mode, mix, tint RGB) |
| L2A | L2A | alpha (l2a) | 7 (opacity, invert, blend mode, mix, tint RGB) |

### Generative (ignore tex0, generate output)
| ID | Label | Group |
|----|-------|-------|
| CNSTL | CNSTL | constellat | 3 (speed, scale, bright) |
| RGRID | RGRID | retrogrd | 5 (speed, horizon, color RGB) |

### Reveal/Mask
| ID | Label | Notes |
|----|-------|-------|
| REVL | REVL | Full dither reveal (two-texture Model) |
| RVL2 | RVL2 | Reveal chain (two-texture, no dither) |
| RVL3 | RVGRD | UV gradient reveal (single-texture, chain-friendly) |
| RVL_V | RVL_V | Vertical gradient reveal (stackable) |
| RVL_R | RVL_R | Radial gradient reveal (stackable) |
| RVL_N | RVL_N | Noise reveal (stackable) |

## Blend Modes (shared by Edge, G2A, L2A)

0=Replace, 1=Multiply, 2=Screen, 3=Overlay, 4=Add, 5=Subtract, 6=Soft Light, 7=Difference

## Tween System

Animates any `_slab_*` param over time via `config.periodic_callbacks`.

**Modes** (10): linear, pingpong, pulse, throb, jiggle, ramp, step, bounce, flicker, drift

**Easings** (12): linear, ease, ease_in, ease_out, quad, cubic, quart, quint, expo, circ, back, elastic

**UI**: `~` button on each slider opens tween editor. Min/Max/Speed bars with clickable numericals. Mode + Easing chip selectors.

## UI Tokens

All tokens defined once in `shader_lab.rpy` init, read by both overlay and shader lab:

| Token | Value | Purpose |
|-------|-------|---------|
| `_SLAB_SCALE` | `screen_width / 640.0` | Base scale factor |
| `_SLAB_F_CHIP` | `max(6, 6*scale)` | Compact chip buttons (mode/easing) |
| `_SLAB_F_SM` | `max(8, 8*scale)` | Small text (labels, params) |
| `_SLAB_C_CHIP` | `#567` | Chip button text color |
| `_SLAB_C_VALUE` | token | Numerical value color |
| `_SLAB_C_DIMMER` | `#00000044` | Modal dimmer (subtle) |
| `_SLAB_C_MODAL_BG` | `#0a0e12` | Modal background (full opacity) |
| `_SLAB_MODAL_YALIGN` | `0.27` | Modal popup Y position |
| `_SLAB_TWEEN_YALIGN` | `0.45` | Tween editor Y position |
| `_SLAB_TITLE_H` | `max(1, F_LG - 10)` | Title bar height |
| `_SLAB_CLOSE_RPAD` | `max(8, 8*scale)` | Close button right padding |
| `_SLAB_ARROW_PAD` | `max(4, 4*scale)` | Nav arrow padding |
| `_SLAB_RULE_PAD` | `2` | Separator rule padding |
| `_SLAB_TWEEN_BTN_W` | `max(10, 10*scale)` | Tween button width budget |
| `_SLAB_TRAY_BAR_H` | `max(14, h*0.014)` | Tray/overlay bar height |

## Keybinds

| Key | Action | Defined In |
|-----|--------|-----------|
| ` (backtick) | Toggle overlay | script.rpy underlay |
| F1 | Toggle shader lab | script.rpy underlay |
| F2 | Cycle overlay theme | shader_overlay.rpy |
| F3 | Toggle EDIT/OVR | shader_overlay.rpy |
| F5 | Cycle tick preset | shader_lab_config.rpy |
| F7 | Cycle vignette blend | shader_lab.rpy |
| F8 | Cycle vignette source | shader_lab.rpy |
| F12 | Screenshot (timestamped) | shader_lab.rpy |
| H | Toggle shader lab HUD | shader_lab.rpy |

## Known Limitations

- **Accumulation motion blur**: Not possible — Ren'Py has no frame buffer feedback. Echo trail is the alternative.
- **Scene transition crossfade**: `show_layer_at` is one stack for the whole master layer. Deferred preset swap is the workaround.
- **B&W dither artifacts at scale 1**: gl_FragCoord/FBO mismatch. Workaround: scale >= 2.
- **Constellation drawing issues**: Intermittent when placed as innermost stack layer.
- **Middle-click slider sticking**: `hide_windows` interrupts bar drag state. Known, not fixed.
- **Shader lab / overlay state isolation**: Shader lab snapshots/restores overlay state on open/close to prevent cross-contamination.
