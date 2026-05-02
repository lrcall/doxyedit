# Studio Panel UI Redesign Plan

Scope: fix the overloaded, single-row Studio toolbar. The canvas, scene
code, and tool semantics stay the same. This is a layout and widget
re-host job, not a feature rewrite.

> [!note] Status as of v2.5: largely landed
> The v2.5 Studio overhaul shipped most of the items described in this
> document — left toolbar with grouped tools, top action bar with
> commit verbs at the right edge, sidebar with collapsible sections,
> layer panel with thumbnails. The plan's diagnosis section still
> reads as accurate context; the detailed tier-by-tier proposal is
> retained for reference + as the template for future redesigns.
> The last unshipped pieces (focus-mode polish, Tier-3 layer masks /
> blend modes / pen tool) live in `docs/BACKLOG.md`.

---

## 1. Diagnosis

The present toolbar packs three unrelated concerns into one horizontal
`QHBoxLayout`:

1. **Tools** (Select, Censor, Crop, Note, Pick, Arrow, Shape, Watermark,
   Text, Delete) - should be permanently reachable.
2. **Tool options** (censor style, crop preset, shape kind, opacity,
   scale, align, template) - should track the active tool or selection.
3. **View toggles** (Grid, thirds, Rulers, Notes, Base, Map, Focus,
   Flip) - should live out of the way, toggled rarely.
4. **Canvas config** (swatches, grid spacing spinbox) - not tool state.
5. **Commit actions** (Export Preview, Export Platform, Export All,
   Queue) - terminal verbs, belong at an edge, not inline.

Plus a second row (Pos, Font, Size, B/I, colors, OL, Kern, LH, Rot, W,
Save Template) which is text-only but is **always visible** whether text
is active or not.

Observed failures in the screenshot:

- **Clipping.** "Watermark" shows "aterma". "Export Preview" shows "ort
  Prev". "Queue This" shows "ueue Th...". A toolbar that hides verbs
  from the user on a standard-width window is broken by definition.
- **Density wall.** ~40 interactive targets in one row. No visual
  hierarchy, no whitespace between groups, only thin pipe separators.
  Fitts's law penalty is severe: every target is small and every
  target is adjacent to three unrelated ones.
- **Dead weight.** Six of the eight swatch slots are empty and dashed.
  They still eat horizontal space.
- **Modal mismatch.** The text-properties row is always shown but
  disabled. That's the worst of both worlds: it costs vertical canvas
  space and communicates nothing when inactive.
- **Layer panel squeeze.** Because the toolbar forces the window wide,
  users push the splitter right to gain canvas area, collapsing the
  layer list into a useless sliver. The layer panel should not be
  competing with the toolbar for horizontal budget.
- **No responsive strategy.** The `QHBoxLayout` does not wrap, overflow,
  or collapse. At <1600 px width the UI is unusable.

Root cause: the toolbar is a flat bag. Every new feature has added one
more button to the same row. There is no container with a budget, so
nothing gets pruned.

---

## 2. Target Architecture

Five distinct containers, each with one job. Borrowed directly from
Photoshop / Affinity Photo / Figma conventions because those apps
solved this problem.

```
+----------------------------------------------------------------------+
| [File  Edit  View  Export]   <- app menu row (thin, optional v2)     |
+---+------------------------------------------------------+-----------+
|   | ContextBar: options for the ACTIVE TOOL + SELECTION  |   |       |
| T |------------------------------------------------------| V |   P   |
| o |                                                      | i |   r   |
| o |                                                      | e |   o   |
| l |                 CANVAS + RULERS                      | w |   p   |
|   |                                                      |   |   e   |
| P |                                                      | D |   r   |
| a |                                                      | o |   t   |
| l |                                                      | c |   i   |
| e |                                                      | k |   e   |
| t |                                                      |   |   s   |
| t |                                                      |   |       |
| e |                                                      |   |       |
|   |                                                      |   |       |
+---+------------------------------------------------------+---+-------+
|  StatusBar: tool | coords | selection | geom | zoom | info           |
+----------------------------------------------------------------------+
```

Five containers:

| # | Container | Type | Contents |
|---|-----------|------|----------|
| 1 | **Tool Palette** | vertical `QToolBar`, docked left | All 9 tools + Delete + Undo/Redo. Icons only, 32 px square. Tooltips show label and shortcut. |
| 2 | **Context Bar** | horizontal `QToolBar`, docked top | Tool-specific options + selection-specific options. Swapped via `QStackedWidget`. |
| 3 | **View Dock** | right `QDockWidget`, collapsible | View toggles, minimap, swatches. Off by default. |
| 4 | **Properties Dock** | right `QDockWidget` | Layer list + layer properties (current right sidebar, cleaned up). |
| 5 | **Status Bar** | `QStatusBar` | Zoom, coords, tool name, selection count, geometry, info. |

The main commit actions (Export Preview / Platform / All / Queue) move
to a **File menu + keyboard shortcuts**, with the most-used Export
Platform also pinned to the right side of the Context Bar for
discoverability.

Why left-docked tools, not top:
- Vertical tool palettes scale to more tools without clipping.
- The user's eye travels top-down through "choose tool > set options >
  work on canvas", matching every major editor since Photoshop 3.
- Leaves the top row exclusively for active-tool context, which is
  exactly what Affinity, Figma, Photoshop, Illustrator, and Procreate
  do.

---

## 3. Specific Grouping

### 3.1 Tool Palette (left dock, always visible)

One column, ~40 px wide, icon buttons (32 px square + 4 px padding).
Every button is a `QToolButton` with `setCheckable(True)` belonging to a
`QActionGroup` so exactly one is checked.

Order (grouped with thin 8 px separators):

```
[undo] [redo]
-----
[select]     Q / V
[censor]     X
[crop]       C
[note]       N
-----
[watermark]  E
[text]       T
[arrow]      A
[shape]      (cycles rect/ellipse; long-press for popup)
[pick]       I
-----
[delete]     Del
-----
[focus]      .
```

Shape tool uses the Photoshop-style nested-tool pattern: a tiny
triangle in the lower-right indicates variants. Long-press (or
right-click) reveals Rectangle / Ellipse / (future: Line, Polygon).

### 3.2 Context Bar (top, always visible, 40 px tall)

Contents swap based on active tool. Implemented as a `QStackedWidget`
where each index is a `QWidget` with the controls for that tool.

**When Select is active** (default empty state):
```
[ Align v ]  [Distribute v]  |  [ Apply Template v ]  |  spacer  |  [Export Platform] [Export v] [Queue]
```

**When a single overlay is selected** the bar adds selection-specific
controls before the commit actions:
```
+-- overlay is selected (any type) --+
[ Opacity --o-- ] [ Rotation -o- ]  |  [Align v]  |  (rest unchanged)

+-- overlay is selected (text) -- appends text subrow --+
[Font v] [Size o 24] [B] [I] [Color] [Outline] [OL o] [Kern o] [LH o] [W o]
  [Pos v] [Save Template]

+-- overlay is selected (shape) --+
[Fill] [Stroke] [Stroke Width o]

+-- overlay is selected (arrow) --+
[Color] [Stroke Width o] [Arrowhead Size o]
```

**When Censor tool is active:**
```
[Style: black|blur|pixelate v]  (spacer)  [Export Platform] ...
```

**When Crop tool is active:**
```
[Preset: Free crop | platform presets v]  (spacer)  ...
```

**When Shape tool is active:**
```
[Kind: Rectangle | Ellipse v] [Fill] [Stroke] [Stroke Width o]  ...
```

**When Text tool is active (no text selected yet):**
```
[Font v] [Size o] [B] [I] [Color] [Outline]  ...
```

Rationale: the context bar is the tool's options surface. Users learn a
context bar in minutes because only the relevant controls appear. No
disabled-but-visible clutter.

### 3.3 View Dock (right, collapsible, off by default)

A `QDockWidget` with a vertical stack of `QGroupBox`es:

```
[v] View
  [ ] Base image
  [ ] Notes
  [ ] Rulers
  [ ] Rule-of-thirds  (Shift+G)
  [ ] Minimap
  [ ] Flip preview    (V)

[v] Grid
  [ ] Show grid       (G)
  Spacing: [ 55 ] px

[v] Recent Colors
  [#][#][#][#][#][#][#][#]    (hidden when all empty)
```

Collapsing to zero width hides the dock entirely. A toolbar button in
the Tool Palette opens/closes it (Photoshop's approach: tiny chevron
rail along the right edge).

Why a dock, not a popup menu: these are "glance" toggles users want
visible mid-work (Rulers, Grid). A popup menu would require two clicks
per toggle.

Why collapsible: default layouts are fine without it. Users who never
touch grid/thirds never see it.

### 3.4 Properties Dock (right, always visible by default)

Effectively the current layer panel cleaned up:

```
[Filter layers....]
+-- Layer list (drag to reorder, thumbnails) --+
|  [eye] [thumb] Text: "Follow us..."           |
|  [eye] [thumb] Watermark: logo_v2.png         |
|  [eye] [thumb] Censor (black) 120x80          |
+-------------------------------------------------+
+-- Layer properties (disabled when nothing selected) --+
|  Opacity  [----o----] 100                     |
|  [ ] Enabled   [ ] Locked                     |
|  X [ 120 ]  Y [ 340 ]                         |
|  Rotation [ 0 ]°                              |
+-------------------------------------------------+
```

No change in semantics, just containment: it lives in a real
`QDockWidget` so Qt handles resize, detach, and state persistence for
free. The user no longer fights a naive `QSplitter`.

The key difference: the layer list gets its own horizontal budget,
independent of the toolbar's width demands. Splitter between canvas and
dock is resizable but the dock has a **minimum width of 260 px** (about
22 em at font_size=12) so it can never be squashed invisible again.

### 3.5 Status Bar (bottom)

Shared across the entire Studio; a real `QStatusBar` not a hand-rolled
`QHBoxLayout`. Contents unchanged from today:

```
Tool: Select  |  Cursor: 1240, 320 #a4b2c0  |  2 selected  |  120x80 @ 440,210  |  Zoom: [Fit] [50%] [100%] [200%]  100%  |  [info message ------------>]
```

Zoom buttons shrink to icons at narrow widths. `info_label` flexes and
scrolls if too long.

---

## 4. Context-Sensitive Behavior

Rules for swapping Context Bar contents. Implement as a single
`_refresh_context_bar()` method called on:

- `_set_tool()` after the active tool changes.
- `_scene.selectionChanged` after selection changes.

Decision table (first match wins):

| Condition | Context Bar stack shows |
|-----------|-------------------------|
| Text overlay selected (any tool) | `text_options_page` |
| Shape overlay selected (any tool) | `shape_options_page` |
| Arrow overlay selected (any tool) | `arrow_options_page` |
| Image overlay selected (any tool) | `image_options_page` |
| Tool = TEXT_OVERLAY, no selection | `text_tool_page` (no Pos, no Save Template) |
| Tool = SHAPE_RECT/ELLIPSE, no selection | `shape_tool_page` |
| Tool = ARROW, no selection | `arrow_tool_page` |
| Tool = CENSOR | `censor_page` (style combo) |
| Tool = CROP | `crop_page` (preset combo) |
| Otherwise | `default_page` (Align + Apply Template + spacer + Export) |

Constant-across-all-pages tail: `Align v`, `Apply Template v`, spacer,
`Export Platform`, `Export v` (menu with Preview / All / Platform), and
`Queue`. Keep those in a trailing `QHBoxLayout` that the stacked widget
always appends. Implementation note: render the tail as a sibling
widget in the Context Bar, so only the **leading** controls swap.

One-line summary: only context-relevant controls are visible; commit
actions are always pinned to the right edge.

---

## 5. Responsive Behavior

Design breakpoints (pixels of window width):

| Width | Tool Palette | Context Bar | View Dock | Properties Dock |
|-------|--------------|-------------|-----------|-----------------|
| >= 1600 | 40 px, icons | full | 260 px, open | 320 px, open |
| 1280-1600 | 40 px, icons | full | 260 px, collapsed | 260 px, open |
| 1024-1280 | 40 px, icons | condensed (labels drop on swatches, pos combo) | hidden | 220 px, open |
| 800-1024 | 32 px, icons, slimmer separators | condensed, export collapses into Export v menu | hidden | 200 px, open |
| <800 | 32 px | Tool options wrap to a second row | hidden | 180 px min, collapsible |

Implementation:

- Use `QToolBar` for the Context Bar so Qt provides **overflow chevron**
  for free. When horizontal space runs out, Qt pushes extra actions into
  an auto-generated popup. This is exactly what Photoshop does.
- Wrap the Context Bar's tool-options-only section in a `QStackedWidget`
  sized to content. The tail (Align, Template, Export, Queue) is
  outside the stack, aligned right.
- Docks auto-collapse via `QDockWidget::setFeatures(DockWidgetClosable
  | DockWidgetMovable)`.
- Tool Palette does not collapse: tools must always be one click away.
  At <800 px the canvas is already too small to work in, so this is
  fine.

One-line summary: let `QToolBar` manage overflow, let `QDockWidget`
manage docking, and stop trying to fit everything in one row.

---

## 6. Qt Implementation Notes

Container choices and why:

| Container | Widget | Why |
|-----------|--------|-----|
| Tool Palette | `QToolBar` set to `Qt.LeftToolBarArea` via `QMainWindow.addToolBar` OR a hand-built vertical `QFrame` with `QToolButton`s | `QToolBar` handles orientation, tooltips, overflow. If Studio isn't hosted by a `QMainWindow`, promote it: Studio becomes a `QMainWindow` inside the tab. |
| Context Bar | `QToolBar` at `Qt.TopToolBarArea`, containing a `QStackedWidget` for the swappable leading section and a fixed trailing `QWidget` for Align/Template/Export/Queue | `QToolBar` gets overflow chevron for free. |
| View Dock | `QDockWidget` on the right | Free resize, detach, state save. |
| Properties Dock | Second `QDockWidget` on the right, tabbed with View Dock via `tabifyDockWidget()` | User can flip between View and Layers with a single click. |
| Status Bar | `QStatusBar` (real one) via `setStatusBar()` | Native styling, permanent widgets via `addPermanentWidget`, transient via `showMessage`. |

Promotion: `StudioEditor` should become a `QMainWindow` (or hold one as
its child) to unlock `addDockWidget` / `addToolBar` / `setStatusBar`.
One-line summary: make Studio a `QMainWindow` so Qt's native docking
system does the heavy lifting.

Widget-specific notes:

- **Tool buttons.** Use `QToolButton` with `setToolButtonStyle(Qt.ToolButtonIconOnly)`
  at 32 px. Add an `objectName` per tool (`studio_tool_select`, etc.).
  Replace the current `btn_select = QPushButton("Select")` pattern.
  Icon source: SVG / font-icon glyph via theme. Fallback label first
  letter if no icon asset.
- **Shape tool variants.** `QToolButton` with `setPopupMode(QToolButton.DelayedPopup)`
  and a `QMenu` of Rectangle / Ellipse actions. Long-press opens menu;
  short click re-uses last variant.
- **Context bar pages.** Each page is a `QWidget` with a `QHBoxLayout`.
  Build once in `_build_context_bar()`, never destroy. Only swap
  `QStackedWidget.setCurrentWidget()`.
- **Dock defaults.** Save / restore via `QMainWindow.saveState()` and
  `restoreState()` into `QSettings("DoxyEdit", "DoxyEdit")` under key
  `studio_window_state`. This also captures user dock moves and sizes.
- **Do NOT** use `setStyleSheet` on individual widgets for sizing. Keep
  the project rule: theme tokens + object names + global QSS.
- **QToolBar separators** via `addSeparator()`. Do not use `QLabel("|")`
  anymore; that's the current anti-pattern.
- **Menu for Export.** Build a `QMenu` with Preview / Platform / All /
  Queue as `QAction`s. Reuse the menu for: (a) Context Bar Export
  button, (b) App `File > Export` menu, (c) Ctrl+Shift+E shortcut. One
  source of truth.

Keyboard shortcuts: keep the existing ones. The palette buttons should
have tooltips with the letter in parentheses: "Select tool (V)".

One-line summary per decision:

- Use `QMainWindow` inside Studio tab to get docking for free.
- Use a left `QToolBar` for the tool palette.
- Use a top `QToolBar` with a `QStackedWidget` for the context bar.
- Use two tabbed `QDockWidget`s on the right for View and Layers.
- Replace hand-rolled status `QHBoxLayout` with `QStatusBar`.
- Collapse Export verbs into a single `Export v` menu button.
- Replace `QPushButton("Select")` tool buttons with `QToolButton`.
- Replace `QLabel("|")` separators with `toolbar.addSeparator()`.
- Persist layout via `saveState/restoreState` to `QSettings`.

---

## 7. Migration Plan (3-6 PRs)

Every PR ships working software. No multi-PR "big rewrite" branches.
Each PR deletes the code it replaces so the codebase never carries both
versions.

### PR 1: Status bar extraction (small, safe, 1 day)

Replace the bottom `QHBoxLayout` in `_build()` with a proper `QStatusBar`
instance, populated via `addPermanentWidget`. Behavior identical, just
the container changes. Zero regression risk, reviewers can eyeball it.

- Promote `StudioEditor` to host a `QMainWindow` internally, or use a
  lightweight `QStatusBar` as a standalone widget if promotion is
  deferred.
- Remove `_pad_lg, _pad, _pad_lg, _pad` hand-built margin on status row.

Ship target: `fix: studio status bar uses QStatusBar`.

### PR 2: Tool palette extraction (medium, 2 days)

Move the 9 tool buttons + undo/redo + delete + focus out of the top
toolbar into a new vertical `QToolBar` on the left.

- Create `_build_tool_palette()` returning a `QToolBar`.
- Replace `QPushButton` tool buttons with `QToolButton` in a
  `QActionGroup`.
- Remove those buttons from the top `QHBoxLayout`.
- The existing `toolbar` still holds all the other widgets; they just
  shift left to fill the space.

Ship target: `feat: studio tool palette as left-docked QToolBar`.

At the end of PR 2 the top row is still cluttered but now has **only**
tool options / toggles / sliders / export. That alone is a readability
win.

### PR 3: Export + Align menu consolidation (small, 1 day)

Replace the four export/queue buttons with a single `Export v` menu
button. Align already uses a menu, keep it. Save Template joins the
Template combo as a menu item.

- Build the `QMenu` once as a class attribute, reuse for button +
  shortcut.
- Bind Ctrl+Shift+E to the menu's default action (Export Platform).

Ship target: `feat: studio export verbs collapse into menu`.

### PR 4: Context bar with QStackedWidget (large, 3 days)

The centerpiece. Move tool-options + selection-options from the flat
top row into a `QStackedWidget` inside a real `QToolBar`.

- Build each page as a `QWidget`: `default_page`, `censor_page`,
  `crop_page`, `shape_page`, `text_tool_page`, `text_sel_page`,
  `shape_sel_page`, `arrow_sel_page`, `image_sel_page`.
- Add `_refresh_context_bar()` wired to `selectionChanged` and
  `_set_tool()`.
- Delete the old `self._props_row` widget and the permanent
  text-properties second row.
- Tail widgets (Align, Apply Template, Export menu, Queue) go in a
  fixed right-aligned layout outside the stack.

Ship target: `feat: studio context bar swaps per tool and selection`.

This is the PR where the screenshot problem actually dies. Before:
clipped "Export Preview". After: one `Export v` dropdown that never
clips.

### PR 5: View dock (medium, 2 days)

Move Grid, thirds, Rulers, Notes, Base, Map, Flip, swatches, grid
spacing out of the top row into a right-side `QDockWidget`.

- Build `_build_view_dock()` returning the dock.
- Migrate the eight swatch buttons into a `QGridLayout` inside the
  dock. Hide the strip entirely when no recent colors exist.
- Add a Tool Palette button (or keyboard `F7`) to toggle the dock.

Ship target: `feat: studio view dock holds grid/rulers/swatches`.

### PR 6: Properties dock + layout persistence (medium, 2 days)

Final cleanup. Convert the layer sidebar into a proper `QDockWidget`
tabbed with the View dock. Enforce minimum width 260 px. Hook up
`saveState/restoreState` to `QSettings` so dock layout is persisted
between sessions.

- Remove the `_canvas_split` `QSplitter` in favor of dock geometry.
- Add a Reset Layout action in a new `View` menu.

Ship target: `feat: studio properties dock + persistent layout`.

Optional PR 7 (nice-to-have): replace text tool button labels with SVG
icons, polish visual density, add keyboard chord for Shape variants.

---

## 8. One-Line Decision Summary

For the coder:

1. Studio becomes a `QMainWindow` internally.
2. Left vertical `QToolBar` = tool palette (icons only).
3. Top horizontal `QToolBar` = context bar with `QStackedWidget` for
   tool-specific options; commit actions pinned right.
4. Context bar contents switch on active tool AND selection type.
5. Right `QDockWidget` (tabbed): View toggles (grid/rulers/swatches)
   and Layer panel.
6. Bottom `QStatusBar` for read-only info.
7. Export verbs collapse into one `Export v` menu button.
8. Replace `QLabel("|")` separators with `QToolBar.addSeparator()`.
9. Replace `QPushButton` tool buttons with `QToolButton` in a
   `QActionGroup`.
10. Persist dock layout to `QSettings` via `saveState/restoreState`.
11. `QToolBar` gives overflow-chevron for free; stop hand-building
    responsive logic.
12. Layer panel gets a minimum width of 260 px so the splitter can
    never hide it again.
13. Minimum window width target: 800 px. Below that, tool palette
    shrinks to 32 px but does not hide.
14. Every swappable context bar page is a pre-built `QWidget` in a
    `QStackedWidget`; never destroyed, only shown/hidden.
15. Ship the redesign as 6 incremental PRs. Each PR replaces (does not
    duplicate) the code it supersedes.

---

## Appendix: What Must NOT Change

Per the brief, preserve:

- All 9 tools and their shortcuts.
- Undo/redo + active-tool highlight.
- All view toggles (Grid, thirds, Rulers, Notes, Base, Minimap, Focus,
  Flip-view).
- All sliders: Opacity, Scale, Font, Size, B, I, Text color, Outline
  color, OL, Kerning, LH, Rotation, Text-width.
- Alignment dropdown.
- Export Preview, Export Platform, Export All, Queue (verbs can merge
  into a menu; they must still be reachable).
- Recent-color swatches strip.
- Layer + properties panels (right side, now in proper dock).
- Rulers + minimap overlays on the canvas.
- Censor style combo (black/blur/pixelate).
- Crop combo (Free crop / platform presets).
- Shape kind combo (Rectangle / Ellipse).
- Apply Template combo + Save Template button.
- Cursor coords + selection count + tool name + zoom in status bar.

No feature is deleted. Each is re-hosted into the container that
matches its scope: tools into the palette, options into the context
bar, toggles into the view dock, info into the status bar, layers into
the properties dock, verbs into a menu.

---

## Plan II - Text UX + toolbar overflow fixes (round 2)

Plan I focused on container architecture. Plan II addresses the next
wave of user complaints after partial rollout: the Text tool is clumsy,
the floating Text Controls dialog doesn't feel like a real tool surface,
Templates vs Default Style are indistinguishable, and the top toolbar
still clips. Each section below ends with a one-line verdict the coder
can act on.

### 1. Text tool flow

#### 1.1 The four complaints, decoded

1. "Text button acts weird, you can click and drag to set a text field
   size/width." The user expects drag-to-size like Figma / Photoshop;
   current code accepts a click, ignores the drag vector, and always
   creates a width-0 overlay that auto-shrinks to content. A drag that
   looks like it is defining a text box does nothing. That is worse than
   no drag support, because it teaches the user a gesture that silently
   fails.
2. "You have to click text each time you want to make a new text field."
   `StudioScene.mousePressEvent` at studio.py:2169 sets
   `self.current_tool = StudioTool.SELECT` after a single placement. One
   placement per tool activation is the single biggest friction in
   Studio today.
3. "Text button isn't mirrored in the text popup UI." The floating Text
   Controls dialog at studio.py:4443 has no placement trigger; once the
   popup has focus, creating a new text overlay requires round-tripping
   through the left palette or the canvas.
4. Implicit fourth complaint: no Escape affordance. If the user activates
   Text and changes their mind, the only exit is a left-palette click
   that is itself outside the canvas eye-line.

#### 1.2 Click vs drag distinction

Split placement into two gestures, following the Figma / Illustrator
convention:

- **Click** (mousePress + mouseRelease at same spot, or drag < 6 px):
  point-insertion. Creates an OverlayTextItem with `text_width = 0`
  (auto-width). Current behavior for this case is correct; preserve it.
- **Drag** (press, move >= 6 px, release): box-insertion. Creates an
  OverlayTextItem whose `text_width` is set to the drag rectangle width
  and whose position is the drag rectangle top-left. Height is ignored
  (text flows naturally), but the width becomes an explicit constraint
  and the overlay wraps to it immediately. This matches the user's
  mental model: "I drew a rectangle, text lives inside it."

Qt-level implementation, concentrated in `StudioScene.mousePressEvent` /
`mouseMoveEvent` / `mouseReleaseEvent`:

```
# mousePressEvent, TEXT_OVERLAY branch (replaces current studio.py:2166-2170):
self._draw_start = pos
self._temp_item = QGraphicsRectItem(QRectF(pos, pos))
pen = QPen(QColor(theme.accent_bright), 1, Qt.PenStyle.DashLine)
self._temp_item.setPen(pen)
self._temp_item.setBrush(Qt.BrushStyle.NoBrush)
self._temp_item.setZValue(500)
self.addItem(self._temp_item)
# do not early-revert current_tool here

# mouseMoveEvent: reuse the existing rect-growing path (already handles shift-square)

# mouseReleaseEvent, TEXT_OVERLAY branch:
rect = self._temp_item.rect()
self.removeItem(self._temp_item); self._temp_item = None
if rect.width() < 6 and rect.height() < 6:
    # treated as click: point-insertion
    self.on_text_overlay_placed(self._draw_start, 0)
else:
    # treated as drag: box-insertion, width locked
    self.on_text_overlay_placed(rect.topLeft(), int(rect.width()))
self._draw_start = None
if not self._sticky_text_tool:
    self.current_tool = StudioTool.SELECT
```

Extend the callback signature: `on_text_overlay_placed(pos, width)`
where `width == 0` means "auto-size". `_on_text_placed` at studio.py:5764
forwards the width into `_add_text_overlay` which already writes into
`CanvasOverlay.text_width`. The slider in the popup and the drag gesture
then share one source of truth: `overlay.text_width`.

Verdict: **drag creates a text box with explicit width, click creates a
point-insertion auto-sized overlay. 6 px threshold distinguishes them.**

#### 1.3 Sticky tool vs one-shot revert

Current: one-shot revert (auto-SELECT after one placement). Industry:
every major design tool lets the user *stay in the tool* until dismissed.
Figma, Illustrator, Photoshop, Procreate, Affinity: all sticky.

Proposal: make sticky the **default**, with a preference toggle for
users who want the current behavior. Store as `studio_text_tool_sticky`
in `QSettings` (project-scoped overrides are overkill here; this is a
UI preference). Default `True`. Expose in:

- The Settings dialog (see section 7) as "Tools: stay active after use"
  covering Text, Shape, Arrow, Censor uniformly. Not just Text.
- A small checkbox pinned to the bottom of the floating Text Controls
  popup labeled "Keep tool active", so users discover it without
  opening Settings.

While sticky, the tool-active visual treatment must be obvious: the
left-palette button stays highlighted, the canvas cursor stays as the
text I-beam, and the status bar reads "Tool: Text  -  click or drag to
add, Esc to exit".

Verdict: **sticky by default across all insertion tools, with an
"exit after use" preference and an Esc hotkey. Never silently revert.**

#### 1.4 Escape-to-exit

Keyboard exit is non-negotiable; it is the muscle memory of every tool
the user already uses. Wire a `QShortcut(Qt.Key.Key_Escape)` with
`Qt.WidgetWithChildrenShortcut` context on `StudioEditor` that:

- If `current_tool != SELECT`, revert to SELECT.
- Else, if any overlay is selected, clear selection.
- Else, no-op (let the parent consume Escape for dialog dismissal etc.).

Escape must also cancel an in-progress drag-to-size rectangle: in
`mouseMoveEvent`, if `event.key() == Qt.Key.Key_Escape` (via a
`keyPressEvent` override on the scene), remove the temp item and zero
out `_draw_start`.

Verdict: **Esc reverts tool, then clears selection. Esc during a drag
cancels the drag.**

#### 1.5 New-text stamp button inside the popup

Covered in section 2 below. Shortcut here: a "T+" button that places a
new text overlay at the canvas center (or last-click location) using
the popup's current style. This lets a keyboard-heavy user who is
tweaking Size / Color in the popup immediately stamp another overlay
without returning to the canvas.

### 2. Floating Text Controls popup

The dialog at studio.py:4443 is a dumb container today: it holds the
old `_props_row` form rows inside a `QFormLayout`. It has no toolbar,
no primary actions, no tool parity with the main palette. Rebuild as a
proper tool panel.

#### 2.1 Target layout

```
+----- Text Controls ------------[x]+
| [T+ New]  [Apply Default]  [...]  |  <- sticky top mini-toolbar
|-----------------------------------|
|  Position   [bottom-right v]      |
|  Font       [Inter         v]     |
|  Size       [----o----] 24        |
|  Style      [B] [I] [U] [S]       |
|  Align      [L] [C] [R]           |
|  Colors     [■ font] [◻ outline]  |
|  Outline    [--o------] 2         |
|  Kerning    [----o----] 0         |
|  Line H     [---o-----] 1.2       |
|  Rotation   [----o----] 0         |
|  Width      [o--------] auto      |
|-----------------------------------|
|  Style presets                    |
|  [Save as default] [Load default] |
|  Named templates: [my-header v]   |
|  [Save as template...] [Delete]   |
|-----------------------------------|
|  [ ] Keep tool active             |  <- sticky-tool toggle
+-----------------------------------+
```

Three bands: **sticky toolbar**, **field form**, **preset footer**.
Plus a persistent sticky-tool checkbox. No other rearrangement of the
existing sliders is needed; they stay where they are.

#### 2.2 The sticky top mini-toolbar

Actions, in order:

| Button | Action | Notes |
|--------|--------|-------|
| `T+ New` | Stamp a new text overlay using the popup's current style at canvas viewport center | Keyboard-accessible. Same as double-clicking the T palette button in "stamp once" mode. |
| `Apply Default` | Overwrite selected text overlay(s) with the saved default style | Disabled when no text overlay is selected. |
| `...` overflow | `QToolButton.MenuButtonPopup` | Holds secondary actions: Copy Style, Paste Style, Apply This Style to All Text, Find and Replace Text, Reset Default Text Style, Align Left/Center/Right (all currently only in right-click). |

The T+ button is a full `QToolButton` with the T glyph plus a small "+"
badge. Tooltip: "Add new text overlay (T)". It mirrors the left-palette
Text tool button in label + shortcut but behaves as a one-shot stamp,
not a tool activator. Rationale: users in popup-focus want to produce a
new overlay without committing to tool-mode.

Implementation: build the toolbar as a `QToolBar(self._text_controls_dlg)`
and `QFormLayout.setMenuBar()` it into the dialog. Qt treats a toolbar
set via `setMenuBar` as a sticky top band, which is the correct
semantic: it is the dialog's own command surface.

#### 2.3 What stays out

Not on the popup toolbar:

- Export verbs. Text Controls is about shaping content, not committing
  it. Export lives in the top Context Bar.
- Undo / Redo. Application-scoped; keep on the main palette.
- Delete overlay. Covered by Del on the canvas; putting it in the popup
  invites double-dismiss.
- Apply Template combo. This confuses with named templates, which are
  in the footer (section 3.2). Top-toolbar Apply Template already
  covers the cross-asset use case.

Verdict: **top of popup is a 3-item sticky toolbar: T+ New, Apply Default,
overflow menu. Bottom is the sticky-tool checkbox. Middle is unchanged
field form + preset footer (see section 3).**

### 3. Templates vs default style

#### 3.1 Disambiguation

Two concepts are currently named similarly and saved via similarly-named
UI. Rename them cleanly:

| Today | Scope | Trigger | Propose rename |
|-------|-------|---------|----------------|
| "Save as Default Text Style" (right-click) | Per-install, `QSettings` key `studio_text_defaults`, auto-applied to every *new* text overlay on *any* project | right-click > Save as Default Text Style | **Default Text Style**. All UI labels refer to "default style". |
| "Save Template" (_props_row button, studio.py:4427) | Per-project, `project.default_overlays` list, applied explicitly via top-bar Apply Template combo | `Save Template` button + `Apply Template v` combo | **Named Preset** (or "Text Preset" when text-only). |

"Template" remains a valid top-level word for the cross-overlay concept
(it applies to watermarks, shapes etc.) but in the Text Controls popup,
text-only presets should be called **Presets** to reduce cognitive load.

#### 3.2 Decision tree the user can hold in their head

```
I want THIS text to look...
|
+-- like every NEW text I make from now on
|     -> Save as Default
|
+-- the same as an EXISTING style I saved
|     -> Apply Default          (from the saved default)
|     -> Load Preset "foo"      (from a named preset)
|
+-- reusable across assets under a name
|     -> Save as Preset "foo"
|
+-- same as another text overlay in this asset
      -> right-click > Copy Style, right-click target > Paste Style
```

Four clean verbs: Save as Default, Apply Default, Save as Preset, Load
Preset. Copy/Paste Style remains as a quick pair for one-off mimicry.

#### 3.3 Where each action lives

| Action | Primary home | Secondary home |
|--------|--------------|----------------|
| Save as Default | Popup preset footer (button) | Right-click > Style > Save as Default |
| Apply Default | Popup sticky toolbar (button) | Right-click > Style > Apply Default |
| Reset Default | Popup overflow menu | Right-click > Style > Reset Default |
| Save as Preset ... | Popup preset footer (button) | - |
| Load Preset | Popup preset footer (combo) | Top Context Bar Apply Template v (covers non-text too) |
| Delete Preset | Popup preset footer (x next to combo) | - |
| Copy Style | Popup overflow menu | Right-click > Style > Copy |
| Paste Style | Popup overflow menu | Right-click > Style > Paste |
| Apply This Style to All Text | Popup overflow menu | Right-click > Style > Apply to All Text |

Right-click is **grouped under a Style submenu**, not flattened. The
current flat list at studio.py:1557-1562 is eight adjacent nearly-
identical verbs; nobody reads them. Collapsing to `Style >` leaves the
top-level menu focused on operational verbs (Edit Text, Align, Drop
Shadow, Duplicate, Delete).

Verdict: **rename to Default / Preset. Four verbs: Save as Default,
Apply Default, Save as Preset, Load Preset. Popup owns the primary UI;
right-click gets a Style submenu.**

### 4. Apply-style / apply-default actions enumerated

The four buttons the user asked for, mapped to implementation:

| # | User intent | Label | Location | Behavior |
|---|-------------|-------|----------|----------|
| a | Set the default style | **Save as Default** | Popup preset footer | Reads style fields from *currently selected text overlay* (required); writes to `QSettings('DoxyEdit','DoxyEdit').studio_text_defaults`. If no selection, reads from popup's current live field values instead. Toast: "Default text style saved". |
| b | Apply default to current selection | **Apply Default** | Popup sticky toolbar | For each selected text overlay, copy fields from `_load_text_style_defaults()` into the overlay via `_push_overlay_attr` (one undo group). Disabled when selection is empty or has no text overlays. |
| c | Save current selection's style as default | Same as (a) | Same | (a) already handles this: "read from current selection, write to default". No separate verb needed once we clarify that Save as Default *uses the selection* as the source. |
| d | Save as a named template | **Save as Preset...** | Popup preset footer | Prompts for name; writes a `CanvasOverlay` dict with only the `_TEXT_STYLE_FIELDS` populated (no position, no text) into `project.default_overlays`. Existing `_save_as_template` at studio.py:6485 does the *full-overlay* variant; add a `_save_as_preset` sibling that strips position + text + width so the preset is purely stylistic. Both write to `default_overlays` with a `kind` discriminator (`"template"` vs `"text_preset"`). |

Extra action the user did *not* name but will want once (a)-(d) are in
place: **Load Preset** (combo on the preset footer). Select a preset name,
and either (i) apply it to current selection if there is one, or (ii)
stage it as the popup's live style for the *next* insertion. Same button
does both jobs because context disambiguates.

Verdict: **four footer actions: Save as Default, Save as Preset..., Load
Preset v, Delete Preset. One toolbar action: Apply Default. All share
the selection as the implicit source/target.**

### 5. Toolbar overflow strategy

Three options on the table. Recommend option B.

#### Option A - Promote to QToolBar

Replace the hand-built `QHBoxLayout` with a `QToolBar`. Qt gives you a
free `>>` overflow chevron when contents exceed the bar's width, and
items spill into an auto-popup menu.

Pro: one-line fix for clipping ("aterma", "ort Prev", "ueue Th...").
Con: the overflow popup shows items in a linear dropdown, losing visual
grouping. Sliders and checkboxes behave poorly inside a QToolBar popup.
Opacity / Scale sliders are near-unusable when collapsed into a menu
entry. This option rescues text labels but degrades control ergonomics.

#### Option B - Context Bar with QStackedWidget (RECOMMENDED)

Already proposed in Plan I section 3.2. Under-scored here because it
*eliminates the overflow problem* rather than managing it. If the text
properties are only visible when text is active, then text / shape /
arrow / censor / crop sliders never fight for horizontal budget at the
same time. The bar only ever holds one tool's worth of controls plus a
trailing commit strip.

Concrete Qt: `QToolBar` at top (for overflow safety on the commit strip),
holding a `QStackedWidget` for the leading tool-options section, plus a
right-aligned fixed `QWidget` for Align / Apply Template / Export menu /
Queue. Line-level guidance:

```
# in _build(), replace the single 'toolbar' QHBoxLayout around line ~4000:

self._context_bar = QToolBar("studio_context_bar", self)
self._context_bar.setMovable(False)
self._context_bar.setIconSize(QSize(18, 18))

# Leading (swappable) section
self._ctx_stack = QStackedWidget()
self._ctx_stack.addWidget(self._build_ctx_default())      # index 0
self._ctx_stack.addWidget(self._build_ctx_text_tool())    # 1
self._ctx_stack.addWidget(self._build_ctx_text_sel())     # 2
self._ctx_stack.addWidget(self._build_ctx_shape())        # 3
self._ctx_stack.addWidget(self._build_ctx_arrow())        # 4
self._ctx_stack.addWidget(self._build_ctx_censor())       # 5
self._ctx_stack.addWidget(self._build_ctx_crop())         # 6
self._context_bar.addWidget(self._ctx_stack)

# Trailing (fixed) commit strip
self._context_bar.addSeparator()
tail = QWidget(); tail_l = QHBoxLayout(tail); tail_l.setContentsMargins(0,0,0,0)
tail_l.addWidget(self.combo_align)
tail_l.addWidget(self.combo_template)
tail_l.addWidget(self.btn_export_menu)   # new single Export v menu
tail_l.addWidget(self.btn_queue)
spacer = QWidget(); spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
self._context_bar.addWidget(spacer)       # pushes tail right
self._context_bar.addWidget(tail)
```

`_refresh_context_bar()` (wire to `selectionChanged` + `_set_tool`) picks
the stack index. Because `QStackedWidget` sizes to its current page,
narrow content pages (e.g., Censor has one combo) release horizontal
budget back to the commit strip automatically.

#### Option C - QScrollArea horizontal wrap

Wrap the current flat row in a `QScrollArea(Qt.Horizontal)`. The toolbar
keeps all widgets, user scrolls horizontally to reach them.

Pro: lowest refactor cost.
Con: horizontal scrollbars in tool surfaces are universally reviled.
Affordance is poor (user doesn't see what's off-screen). Keyboard
navigation is broken. Skip.

Verdict: **Option B (Plan I section 3.2) is the right answer. Option A
is tempting as a one-PR patch but produces an unusable overflow popup
for sliders; use A only if Option B slips.**

### 6. Top toolbar grouping

Even with Option B in place, the top bar still carries ~10 widgets at
once (tool options leading + commit strip trailing). Today they touch,
separated only by `QLabel("|")` anti-patterns. Proposed groups, in
left-to-right order:

| Group | Members | Separator after |
|-------|---------|-----------------|
| History | Undo, Redo | `addSeparator()` |
| Tool options (swappable) | Whatever the active tool needs | `addSeparator()` |
| Arrangement | Align v, Distribute v, Apply Template v | `addSeparator()` |
| Spacer | expanding | - |
| Commit | Export Platform (icon), Export v (menu), Queue | - |

Visual separation uses `QToolBar.addSeparator()` (native styled), not
`QFrame` or `QLabel("|")`. If the theme's separator is too subtle, bump
the rule in the global QSS:

```
QToolBar::separator {
    background: #<theme.border>;
    width: 1px;
    margin: 6px 4px;
}
```

No colored dividers. Color separators imply semantic meaning and invite
every designer's instinct to brand them; they end up as visual clutter.
Stick to theme.border grays.

Grouping in the left **Tool Palette** follows the same rule with
whitespace separators (4-8 px between groups) per Plan I section 3.1.
Already covered; restated here only to make clear that the grouping
discipline applies to both bars.

Verdict: **five groups: History, Tool options, Arrangement, spacer,
Commit. Native `addSeparator()` between. No labels, no colors.**

### 7. Settings / Preferences dialog

The user's "settings popup" / "set op up" note maps to a real gap: a
dozen small preferences are scattered across context menus, right-click,
and `QSettings` reads with no UI. Centralize in a single Preferences
dialog, reached via a gear icon in the left palette bottom or via
`Ctrl+,` (standard).

#### 7.1 Panels (tabbed QDialog)

1. **Tools**
   - Keep tool active after use: [x] Text  [x] Shape  [x] Arrow
     [x] Censor (each overrides the per-tool default)
   - Drag-to-size threshold: [6] px
   - Snap threshold: [8] px (currently `SNAP_THRESHOLD_PX`)

2. **Canvas**
   - Background: [color swatch]  (current: theme.studio_bg)
   - Grid spacing default: [55] px
   - Grid visible by default: [ ]
   - Rule-of-thirds visible by default: [ ]
   - Rulers visible by default: [x]

3. **Text defaults**
   - Font family: [Inter v]
   - Font size: [24]
   - Color: [swatch]
   - Outline color / width: [swatch] [0]
   - Shadow: [off v]
   - Inline live preview box showing "The quick brown fox" with the
     selected defaults applied. This is the single place to edit the
     default style outside of right-click-on-selection.
   - [Save as default] saves to `QSettings.studio_text_defaults`.
   - [Reset to built-ins] clears it.

4. **Export**
   - Default export folder
   - Default format (PNG / JPEG / WebP)
   - JPEG quality slider
   - Preview scale (50% / 100% / original)

5. **Keyboard** (future / v2)
   - Rebindable shortcut list

Implementation: a `QDialog` with a `QTabWidget`. Each tab is a
`QWidget` with a `QFormLayout`. Persistence: `QSettings("DoxyEdit",
"DoxyEdit")` namespaced under `studio_*`. Apply-on-close (or Apply /
Cancel / OK buttons if the user expects the form-dialog pattern).

#### 7.2 What to MOVE into Settings (and remove from elsewhere)

- Grid spacing spinbox (currently in top toolbar) -> Canvas panel. The
  grid *toggle* stays as a View Dock switch because users flip it
  mid-work; the spacing is a set-and-forget pref.
- Canvas bg color (nowhere today, hardcoded via theme) -> Canvas panel,
  per-project override.
- Default text style fields (currently only right-click > Save as
  Default, saves from a selection) -> Text defaults panel, with an
  inline editor. Right-click shortcut stays for "save from selection".

Verdict: **one `Ctrl+,` Preferences dialog with 4-5 tabs. Move set-and-
forget prefs out of menus and top bar. Keep mid-work toggles where they
are (view dock / context bar).**

### 8. Migration plan

Six PRs. Each is independently shippable; each deletes the code it
supersedes.

#### PR A - Text drag-to-size + sticky tool + Escape

Scope: studio.py scene + editor only. No container changes.

- Rewrite `StudioScene.mousePressEvent` / `mouseMoveEvent` /
  `mouseReleaseEvent` for `TEXT_OVERLAY` to draw a dashed rect during
  drag; emit `(pos, width)` on release.
- Extend `on_text_overlay_placed` signature and `_on_text_placed` to
  accept width; pass through to `_add_text_overlay`.
- Add `_sticky_tool_for(tool)` reading `QSettings
  .studio_text_tool_sticky` (default True). In the insertion branches,
  only revert to SELECT when not sticky.
- Add application-scoped `QShortcut(Key_Escape)` on StudioEditor that
  reverts tool then clears selection.
- Add a scene `keyPressEvent` override that cancels in-progress drag on
  Esc.

Risk: low. Preserve auto-width behavior for clicks (drag under 6 px).
Ship target: `feat: studio text tool supports drag-to-size, sticky, Esc`.

#### PR B - Text Controls popup sticky toolbar + footer

Scope: popup rebuild, no scene changes.

- Restructure `_text_controls_dlg` at studio.py:4443: add a
  `QToolBar` via `setMenuBar`, populated with T+ New, Apply Default,
  overflow menu.
- Add preset footer section with Save as Default, Save as Preset...,
  Load Preset v, Delete Preset buttons.
- Add sticky-tool checkbox at bottom bound to
  `QSettings.studio_text_tool_sticky`.
- Wire Apply Default to a new `_apply_default_text_style_to_selection`
  method that undo-groups `_push_overlay_attr` calls over
  `_TEXT_STYLE_FIELDS`.
- Add `_save_as_preset` sibling of `_save_as_template` that saves a
  style-only `CanvasOverlay` dict with `_kind = "text_preset"` to
  `project.default_overlays`.
- Add the overflow menu's Copy Style / Paste Style / Apply to All /
  Find and Replace shims that just call the existing right-click
  handlers.

Risk: medium. Popup is already an independent widget; refactoring is
local. Ship target: `feat: studio text controls popup gains sticky
toolbar and preset footer`.

#### PR C - Right-click Style submenu

Scope: `OverlayTextItem.contextMenuEvent` at studio.py:~1530.

- Group Save as Default / Reset Default / Copy / Paste / Apply to All
  under a new `Style >` submenu.
- Rename labels: "Save as Default", "Apply Default", "Reset Default".
- Leave Edit Text, Change Color, Change Background, Clear Background,
  Align, Drop Shadow, Underline, Strikethrough, Duplicate, Delete at
  the top level - those are *content* verbs, not *style* verbs.

Risk: low. Pure label + nesting change. Ship target: `refactor: studio
text right-click groups style verbs under a submenu`.

#### PR D - Context Bar QStackedWidget (Plan I PR 4)

Already scoped in Plan I section 7 PR 4. Now also subsumes the
text-tool-active case: `text_tool_page` becomes a thin page showing
only Font / Size / Color, and the full controls remain in the popup.
The popup's presence becomes the disambiguator: Context Bar carries
summary controls, popup carries the full form.

Risk: high (largest refactor). Ship target: `feat: studio context bar
swaps per tool and selection`.

#### PR E - Preferences dialog

Scope: new file `doxyedit/studio_prefs.py`, plus a wiring line in the
main window or Studio's left palette.

- `QDialog` with tabbed panels as in section 7.1.
- Consolidate `QSettings` reads into a `StudioPrefs` dataclass so the
  rest of Studio reads typed fields, not raw settings keys.
- Remove the grid-spacing spinbox from the top toolbar (it now lives
  in Canvas panel).
- Hook `Ctrl+,` shortcut.

Risk: medium. New code is additive; the removal of the grid spinbox is
the only code deletion and is guarded by the settings round-trip.
Ship target: `feat: studio preferences dialog (Ctrl+,)`.

#### PR F - Toolbar grouping polish + remove QLabel separators

Scope: aesthetic and grouping cleanup.

- Replace all `QLabel("|")` instances in `_build()` with
  `toolbar.addSeparator()` (QToolBar) or `QFrame` vertical line
  (QHBoxLayout).
- Tune `QToolBar::separator` in global QSS.
- Confirm the five groups (History, Tool options, Arrangement, spacer,
  Commit) render with visible but unobtrusive separation.

Risk: low. Visual-only. Ship target: `polish: studio top bar uses
native toolbar separators and groups`.

### 9. One-line decision summary (Plan II)

1. Text tool: click = auto-size, drag (>=6 px) = width-locked box.
2. Text tool is sticky by default; Escape exits; scene Esc cancels the
   in-progress drag.
3. Floating Text Controls gets a sticky top mini-toolbar (T+ New,
   Apply Default, overflow), a preset footer, and a sticky-tool
   checkbox.
4. Rename: "Default style" (install-wide, auto-applied) vs "Preset"
   (project-saved, named). Four verbs: Save as Default, Apply Default,
   Save as Preset, Load Preset. Copy/Paste Style stays for one-off.
5. Right-click groups all style verbs under a `Style >` submenu.
6. Top toolbar overflow: use Plan I's `QStackedWidget` Context Bar, not
   a plain `QToolBar` overflow or a `QScrollArea` horizontal wrap.
7. Five top-bar groups separated by native `addSeparator()`: History,
   Tool options, Arrangement, spacer, Commit.
8. Add a `Ctrl+,` Preferences dialog with Tools / Canvas / Text
   defaults / Export tabs; move set-and-forget prefs out of menus.
9. Rollout: six PRs, each ships alone. PRs A, C, F are low-risk
   cleanups; PR B is the popup rebuild; PR D is the large Context Bar
   refactor; PR E adds the Preferences dialog.
10. Do not build a parallel universe: every PR deletes the path it
    supersedes so the codebase never carries both UIs.
