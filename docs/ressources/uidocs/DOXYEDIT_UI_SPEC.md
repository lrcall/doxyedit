# DoxyEdit UI Spec — Locked Design System

DO NOT hardcode colors, fonts, or sizes on individual widgets. EVER.

## The Golden Rule

**All visual properties come from the Theme dataclass.** If you're writing `setStyleSheet("color: rgba(200,200,200,0.9)")` on a widget, you've already failed. Use `theme.text_primary` instead.

## Architecture

### Single Source of Truth

```
doxyedit/themes.py
  ├── Theme dataclass        ← ALL tokens defined here
  ├── generate_stylesheet()  ← Global QSS applied to QMainWindow
  └── 7 theme instances      ← Vinik24, Soot, Bone, etc.
```

Every widget in the app inherits from `generate_stylesheet()` via Qt's CSS cascade. New panels should NOT set their own colors — they get them automatically.

### When You Need Panel-Specific Styles

Use `objectName` selectors in `generate_stylesheet()`, NOT inline `setStyleSheet()` on the widget:

```python
# WRONG — inline on widget
self.setStyleSheet(f"background: {theme.bg_main}; color: {theme.text_primary};")

# RIGHT — in generate_stylesheet() using objectName
QWidget#kanban_panel { background: %(bg_deep)s; }
```

Set `self.setObjectName("kanban_panel")` in the widget's `__init__`, then add the selector to `generate_stylesheet()`.

### When Widgets Are Created Dynamically

Cards, pills, list items created at runtime (after `generate_stylesheet()` runs) inherit the global QSS IF their parent is in the widget tree. The global stylesheet cascades to children automatically.

**Do NOT** call `widget.setStyleSheet(...)` on dynamically-created widgets. Instead:
1. Give them an `objectName`
2. Add their selector to `generate_stylesheet()`
3. They'll pick up the style automatically when added to the widget tree

If you need truly dynamic styles (e.g., status-colored dots), use `setProperty()` + property selectors:

```python
# In widget code:
dot.setProperty("status", "posted")

# In generate_stylesheet():
QLabel[status="posted"] { color: %(success)s; }
QLabel[status="ready"] { color: %(warning)s; }
QLabel[status="pending"] { color: %(text_muted)s; }
```

## Token Reference

### Surfaces (backgrounds)
| Token | Purpose | Example |
|-------|---------|---------|
| `bg_deep` | Deepest: canvas, scroll areas, main grid | `#0c0b0e` |
| `bg_main` | Panel backgrounds | `#141218` |
| `bg_raised` | Toolbars, tabs, elevated cards | `#1a181e` |
| `bg_input` | Text inputs, combo boxes, subtle card bg | `#201e26` |
| `bg_hover` | Hover state on any interactive element | `#28222e` |

### Text
| Token | Purpose | Example |
|-------|---------|---------|
| `text_primary` | Main content text | `#b8b0c0` |
| `text_secondary` | Labels, hints, subtitles | `#8880a0` |
| `text_muted` | Placeholders, disabled, very dim | `#585060` |
| `text_on_accent` | Text on accent-colored backgrounds | `#0c0b0e` |

### Accent
| Token | Purpose | Example |
|-------|---------|---------|
| `accent` | Primary: selected states, active indicators | `#7868b0` |
| `accent_dim` | Subtle: hover backgrounds, soft highlights | `#483868` |
| `accent_bright` | Strong: focus rings, active buttons | `#9888d0` |

### Borders
| Token | Purpose | Example |
|-------|---------|---------|
| `border` | Standard borders | `#28222e` |
| `border_light` | Subtle separators, dividers | `#383040` |

### Selection
| Token | Purpose | Example |
|-------|---------|---------|
| `selection_bg` | Selected item background | `#483868` |
| `selection_border` | Selected item border | `#7868b0` |

### Semantic (fixed across all themes)
| Token | Purpose | Default |
|-------|---------|---------|
| `success` | Posted, complete, green indicators | `#6eaa78` |
| `warning` | Ready, pending, amber indicators | `#be955c` |
| `error` | Missing, failed, red indicators | `#9a4f50` |
| `star` | Star rating color | `#be955c` |

### Font
| Token | Purpose | Default |
|-------|---------|---------|
| `font_size` | Base size in px — everything scales from this | `12` |
| `font_family` | Font face | `Segoe UI` |

### Derived Sizes (from generate_stylesheet)
| Name | Formula | Purpose |
|------|---------|---------|
| `f` | `font_size` | Base font |
| `fs` | `max(8, f - 1)` | Small (labels, hints) |
| `fxs` | `max(7, f - 2)` | Extra small (dim) |
| `fl` | `f + 1` | Large (headers) |
| `pad` | `max(4, f // 3)` | Standard padding |
| `pad_lg` | `max(6, f // 2)` | Large padding |
| `rad` | `max(3, f // 4)` | Border radius |

## Rules

### DO
- Set `objectName` on every custom panel widget
- Add panel-specific selectors to `generate_stylesheet()`
- Use `theme.token_name` when you absolutely must compute a value at runtime
- Let Qt's CSS cascade handle children automatically
- Use `setProperty()` + property selectors for dynamic state (status colors, etc.)

### DON'T
- Call `setStyleSheet()` with hardcoded colors on ANY widget
- Set `QFont("Segoe UI", 9)` — use `theme.font_family` and `theme.font_size`
- Write `rgba(255,255,255,0.1)` anywhere — map it to a token
- Create `apply_theme()` methods that re-set inline styles — add to `generate_stylesheet()` instead
- Use different colors for the same semantic role across panels

### EXCEPTION: Overlays and Annotations
Crop handles, censor regions, note annotations use fixed high-contrast colors (orange, blue) that must be visible regardless of theme. These are the ONLY places hardcoded colors are acceptable.

## Adding a New Panel

1. Create widget class, set `self.setObjectName("my_panel")`
2. Do NOT set any stylesheet on the widget or its children
3. Add `QWidget#my_panel { background: %(bg_deep)s; }` to `generate_stylesheet()`
4. Add any child-specific selectors: `QWidget#my_panel QLabel { ... }`
5. If panel needs dynamic state colors, use `setProperty()` pattern
6. Test with at least 2 themes (one dark, one light — Soot + Bone)

## Current Violations (TODO)

The following panels were built during the v2.2 session with inline hardcoded styles and need to be migrated to the `generate_stylesheet()` approach:

- `kanban.py` — KanbanCard, KanbanColumn backgrounds, text colors
- `infopanel.py` — _TagPill, add button, notes editor, separator colors
- `filebrowser.py` — pin bar button hover, delegate badge colors
- `preview.py` — PreviewPane info label, scene background

Each of these has an `apply_theme()` method that should be replaced with `objectName` selectors in `generate_stylesheet()`.

## Related

- `doxyedit/themes.py` — Theme dataclass + generate_stylesheet()
- `docs/ressources/uidocs/SHADER_LAB_UI_GUIDE.md` — Reference: token discipline from PsyAI
- `docs/ressources/uidocs/OVERLAY_UI_LOCKED.md` — Reference: locked spec pattern
