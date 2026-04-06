---
tags: [preview, annotations, notes, navigation]
description: Full-image preview window — zoom, pan, navigation, and note annotations.
---

# Preview Window

The preview window shows a full-resolution, zoomable view of the selected image. Only one preview window is ever open at a time — opening another image updates the same window instead of spawning a second.

---

## Opening the Preview

- **Enter** key — opens preview for the currently selected thumbnail
- **Double-click** a thumbnail
- **Middle-click** a thumbnail — instant preview (works even with hover disabled)
- **Right-click → Preview** in the context menu

---

## Navigation Inside Preview

| Key | Action |
|-----|--------|
| Space / Tab / Down | Next image |
| Backspace / Up / Left | Previous image |
| Esc | Close preview |
| Ctrl+0 | Fit image to view |
| N | Add note annotation |
| V | Toggle View Notes |

Keys always navigate regardless of which button has focus — the Add Note / View Notes buttons are non-focusable so they never steal the Space key.

Navigation in the preview window syncs the thumbnail selection in the main browser grid (in both flat view and folder view). The grid auto-scrolls to keep the highlighted thumbnail visible.

---

## Mouse Controls

| Action | Effect |
|--------|--------|
| Scroll | Zoom in / out |
| Drag | Pan the image |
| Overpan | The scene has a large margin — you can scroll past image edges freely |

---

## Window Controls

The preview window is fully themed:
- Title bar color matches the active DoxyEdit theme (via DWM)
- Full stylesheet applied (matches the main window)
- Scrollbar handles use the accent color and brighten on hover
- Minimize, maximize, and restore buttons in the title bar

The preview window remembers its size, position, and zoom level between sessions.

---

## View Notes (Default: Off)

When you open the preview window, annotation notes are hidden by default. Press **V** or click **View Notes** to toggle them visible.

This is intentional — it keeps the image clean for review and you explicitly enable notes when you want to see them.

---

## Note Annotations

Draw freeform annotation boxes directly on the image. Notes persist with the project in the asset's `notes` field.

### Adding a Note

1. Press **N** or click **Add Note**
2. Drag a rectangle on the image to define the note area
3. Type your note text in the dialog that appears
4. Click OK — the note is saved

### Managing Notes

- **Delete** key — removes the selected note
- **Ctrl+0** — fit image to view (helps relocate notes after zooming)
- Notes display as bold text with a dark background for readability
- Note font size matches the UI font size setting

### Storage

Notes are stored as text + coordinates in the asset's `notes` field in the project JSON. They persist across sessions and are restored when you open the preview for that image again.

> [!note] Notes Field vs Specs Field
> The `notes` field is for human-written annotations. The `specs` field is for CLI/tool-generated metadata (size, palette, relations). DoxyEdit auto-migrates old CLI-generated notes into `specs.cli_info` on load.

---

## Hover Preview

A smaller popup preview appears when hovering over thumbnails in the grid (when the **Hover Preview** checkbox is enabled).

- Shows the full original resolution (e.g., "2475 × 3375px")
- Shows the full file path
- Configurable delay: **View > Hover Preview Delay** (200–1200ms, persisted)
- Configurable size: fixed pixel size (e.g., 400px), consistent regardless of thumbnail zoom level
- Hides before re-triggering delay when moving between thumbnails

---

## Related

- [[Interface Overview]] — browser grid and thumbnail navigation
- [[Keyboard Shortcuts]] — full shortcut reference
- [[Tagging System]] — adding notes vs tags
