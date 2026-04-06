---
tags: [eagle, ui, comparison, planned, design]
description: Feature-by-feature contrast between DoxyEdit and Eagle — what to borrow, what to skip, what DoxyEdit already does better.
---

# Eagle Contrast

Not a competition comparison — a borrow list. What Eagle does well that DoxyEdit could adopt, and what DoxyEdit already handles differently (sometimes better for art workflows).

---

## Side-by-Side Feature Matrix

| Feature | Eagle | DoxyEdit | Gap |
|---------|-------|----------|-----|
| Thumbnail grid (virtual scroll) | ✓ | ✓ | — |
| Folder tree sidebar | ✓ full tree | ✗ sort mode only | **Borrow** |
| Asset count badges on folders | ✓ | ✗ | **Borrow** |
| Right info panel (selected asset) | ✓ | ✗ (tray ≠ info) | **Borrow** |
| Color palette swatches per asset | ✓ extracted | partial (auto-tags only) | **Borrow** |
| Search by dominant color | ✓ | ✗ | Maybe later |
| Smart folders (saved filter presets) | ✓ | ✗ | **Borrow** |
| Zoom slider (visible, draggable) | ✓ | Ctrl+scroll only | **Polish** |
| Thumbnail labels (hover-only option) | ✓ | always visible | **Polish** |
| Star ratings (1–5) | ✓ | ✓ (5 colors) | — |
| Tags with color coding | ✓ | ✓ richer | DoxyEdit better |
| Tag keyboard shortcuts | ✗ | ✓ | DoxyEdit better |
| Tag sections / groups | basic | ✓ 4 sections | DoxyEdit better |
| Eye toggle (hide by tag) | ✗ | ✓ | DoxyEdit better |
| Batch tag via number keys | ✗ | ✓ | DoxyEdit better |
| Platform export pipeline | ✗ | ✓ | DoxyEdit better |
| Non-destructive censor | ✗ | ✓ | DoxyEdit better |
| Notes / annotations | ✓ text | ✓ text + drawn boxes | DoxyEdit better |
| Hover preview popup | ✓ | ✓ | — |
| Full-screen preview window | ✓ | ✓ | — |
| Drag files out to other apps | ✓ | ✓ (tray drag) | — |
| Import from URL (paste) | ✓ | ✓ | — |
| Drag & drop import | ✓ | ✓ | — |
| Duplicate file detection | ✓ | ✓ basic | — |
| Trash / soft delete | ✓ | ✓ (ignore tag) | — |
| Format filter (show only PSD etc.) | ✓ | ✗ | **Borrow** |
| Sort by color | ✓ | ✗ | Maybe later |
| Multiple libraries open at once | ✓ tabs | ✓ multi-project tabs | — |
| Cloud sync | ✓ Pro | ✗ intentionally local | Skip |
| Board / mood board view | ✓ | Canvas tab (different) | — |
| PSD/SAI native thumbnails | ✗ plugin | ✓ native | DoxyEdit better |
| CLI / scripting integration | ✗ | ✓ | DoxyEdit better |

---

## Priority Borrow List

### High value, low effort

**Visible zoom slider**
Replace (or supplement) Ctrl+scroll with a visible slider in the toolbar. Eagle puts it top-center. One `QSlider` wired to the existing thumb size logic.

**Hover-only filenames**
Option to hide filename labels until hover. Cleaner grid, especially at small zoom. Toggle in View menu. Already have the delegate — just suppress the text draw when the flag is set.

**Format filter button**
Single button or dropdown: "PSD only", "PNG only", "SAI only", etc. Filter `_filtered_assets` by `Path(asset.source_path).suffix`. Useful when a folder has mixed formats.

---

### High value, medium effort

**Folder tree sidebar**
The biggest visual gap. Replace or supplement the current "By Folder" sort mode with a persistent tree panel on the left. `QTreeView` + `QFileSystemModel` with asset count overlay. Clicking a folder node filters the grid. See [[Roadmap]] for full spec.

**Right info panel**
When an asset is selected, show: large thumbnail, filename, resolution, tags (pill chips, editable), notes (inline editable), file size, date. Replaces the need to open a separate dialog for basic metadata. 220px fixed-width panel, collapsible. The Work Tray already exists on the right — info panel could live above it, or replace it when something is selected.

**Smart folders**
Saved filter presets with a name. "Starred + Finished", "Needs Censor", "Character Art only". Stored in the project file. Appear in the sidebar above the folder tree. Low data model complexity — just a list of `{name, filters}` objects.

**Color palette swatches on right panel**
Already partially computed via autotag (warm/cool etc.). Extract 5 dominant colors on import (Pillow `image.getcolors()` or k-means) and store in `asset.specs.palette`. Display as small color circles in the info panel. No search-by-color needed yet — just visual reference.

---

### Lower priority / skip for now

**Search by color** — niche for art workflow, complex to do well. Skip.

**Multiple libraries open simultaneously** — already implemented as multi-project tabs.

**Cloud sync** — intentionally out of scope. Local-first is a feature.

**Sort by color** — could derive from palette data later but not a pressing need.

---

## UI Unification Opportunities

These don't add features — they just bring DoxyEdit's visual language closer to Eagle's cleaner style:

1. **Less toolbar clutter** — move "Recursive", "Hover Preview", "Cache All" checkboxes to View menu or a `⋯` overflow button. Keep only the most-used controls in the toolbar strip.

2. **Sidebar-first mental model** — folder navigation belongs on the left, not embedded in a sort dropdown. Even before a full folder tree is built, restructuring the sidebar to feel like a nav panel (not a tag list) sets the right expectation.

3. **No tab bar for core workflow** — Eagle has no tabs. Everything lives in one view, navigated via the sidebar. Long-term, moving Canvas and Censor into contextual panels (accessible via right-click or a side button) instead of top-level tabs would feel cleaner.

4. **Thumbnail cell consistency** — Eagle uses uniform square cells with images letterboxed inside. DoxyEdit currently sizes cells to thumbnail width. Switching to uniform square grid (existing `setGridSize` already does this) looks more polished and makes the grid feel less chaotic with mixed portrait/landscape images.

5. **Muted unselected state** — Eagle dims non-selected thumbnails slightly when one is selected. Focus effect. Small stylesheet tweak on the delegate.

---

## Related

- [[UI Direction — Eagle Layout]] — three-panel layout reference and implementation plan
- [[Eagle Integration]] — import/export Eagle library format
- [[Interface Overview]] — current DoxyEdit layout
- [[Roadmap]] — full feature backlog
