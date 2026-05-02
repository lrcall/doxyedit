---
tags: [themes, appearance, vinik24, fonts, ui]
description: Available themes, font size controls, and the Vinik24 color palette.
---

# Themes & Appearance

> [!note] Updated for v2.5
> The original 7 themes (Vinik 24 / Warm Charcoal / Soot / Bone /
> Milk Glass / Forest / Grey) have grown to 21+: Neon, Ember,
> Midnight, Dawn, Citrus, Candy, Slate, Moss, Ocean, Lavender,
> Sunset, Aurora, Gold (and more). The full canonical list is in
> `doxyedit/themes.py` (each definition starts with `name="..."`),
> reachable via View > Theme. The descriptions below cover the
> original 7; new themes follow the same token vocabulary so the
> contrast and accessibility properties carry over.

DoxyEdit ships with 21+ built-in themes. The active theme applies to
every widget — the main window, dialogs, tray, splitters, scrollbars,
progress bar, and the preview window. The Windows title bar color
also matches the theme.

---

## Built-in Themes

| Theme | Style |
|-------|-------|
| **Soot** | Cool dark purple (default since v1.9) |
| **Vinik 24** | Dark purple / teal — the original signature theme |
| **Warm Charcoal** | Warm dark tones |
| **Bone** | Light warm beige |
| **Milk Glass** | Light cool grey |
| **Forest** | Dark green |
| **Dark** | Classic IDE dark |

Switch themes via **View > Theme**. The selected theme persists across sessions.

---

## Changing the Theme

**View > Theme** → select from the submenu. Takes effect immediately with no restart needed.

---

## Font Size

Font size applies globally to the UI, thumbnails, and the tag panel.

| Shortcut | Action |
|----------|--------|
| Ctrl+= | Increase font size |
| Ctrl+- | Decrease font size |
| Ctrl+0 | Reset font size to default |

Range: 8px to 24px. Persists across sessions.

The thumbnail filename text, tag panel labels, and tag buttons all scale with font size.

---

## Thumbnail Zoom

Thumbnail size is independent of font size:

- **Ctrl+Scroll** over the grid — zoom thumbnails from 80px to 320px
- No rebuild needed — instant resize
- Zoom level persists in the project file

---

## Thumbnail Quality

**View > Thumb Quality** — sets the internal generation resolution (128px to 1024px). Higher values produce sharper thumbnails at large zoom levels at the cost of cache space and generation time.

---

## Hover Preview Size

**View > Hover Size** — sets the hover popup size as a fixed pixel value (e.g., 400px). The size is consistent regardless of thumbnail zoom level.

---

## Scrollbar Theming

Scrollbar handles use the theme's accent color and brighten on hover. This applies to all scrollbars in the application including the grid, tag panel, tray, and preview window.

---

## Windows Title Bar Color

DoxyEdit sets the Windows title bar color to match the active theme using the DWM API. This applies to both the main window and the preview window.

---

## Tokenized Design System

The theme system uses a tokenized approach: font size, padding, and border radius all scale together. Changing the font size adjusts the overall density of the UI consistently.

---

## Vinik24 Palette Reference

The Vinik 24 theme (and the Obsidian CSS snippet in this vault) uses this exact palette:

| Token | Hex | Usage |
|-------|-----|-------|
| `--deep-bg` | `#332c50` | App background |
| `--bg-raised` | `#46394a` | Sidebar, raised surfaces |
| `--bg-card` | `#614e6e` | Cards, inline code background |
| `--accent` | `#8d5f8d` | Buttons, highlights, borders |
| `--accent-bright` | `#c97db8` | H1, links hover, primary accent |
| `--text-primary` | `#e8c0e0` | Main body text |
| `--text-secondary` | `#b899b8` | H3, italic, secondary text |
| `--text-muted` | `#8677a0` | Muted labels, placeholders |
| `--green` | `#3d6b5a` | Completed checkboxes |
| `--olive` | `#93a167` | Tip callout titles |
| `--gold` | `#d4a96a` | Bold text, search highlight |
| `--orange` | `#e87b55` | Warning callouts |
| `--red` | `#c85a5a` | Danger, error states |
| `--blue` | `#5a8ec8` | Info callouts |
| `--cyan` | `#6db5c8` | Links |
| `--border` | `#614e6e` | Table and panel borders |

---

## Related

- [[Home]] — quick reference
- [[Interface Overview]] — full UI layout
- [[Getting Started]] — first launch defaults
