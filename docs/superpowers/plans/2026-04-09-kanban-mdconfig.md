# Kanban Board + Config File — Implementation Plan

## Part A: Kanban Posting Schedule Board
**Goal:** Trello-style 4-column board (Pending→Ready→Posted→Skip) showing platform assignments as draggable cards.

**Files:** Create `doxyedit/kanban.py`, modify `doxyedit/window.py`

### Task 1: KanbanPanel widget
- New file `kanban.py` with `KanbanPanel(QWidget)`
- 4 column QScrollAreas in a horizontal layout
- Column headers with count badges
- `refresh(project)` rebuilds cards from `project.assets[].assignments`
- Each card: thumbnail (64x64) + platform/slot label + asset name

### Task 2: Drag-drop between columns
- Cards are QPushButtons or QFrames with drag support
- Drop on column → change `PlatformAssignment.status`
- Emit `status_changed` signal

### Task 3: Window integration
- Add "Schedule" tab after Platforms
- Connect signals, wire theme, refresh on project load

## Part B: YAML Config File
**Goal:** Let users define custom platforms via config.yaml instead of editing Python.

**Files:** Modify `doxyedit/models.py`, `doxyedit/window.py`

### Task 4: Config loader in models.py
- `load_config(project_dir)` reads `config.yaml` if present
- Merges custom platforms into PLATFORMS dict
- Falls back to hardcoded defaults

### Task 5: Config UI
- Tools menu: "Edit Project Config..."
- Opens config.yaml in system editor or inline QTextEdit dialog
- Auto-creates template if missing
