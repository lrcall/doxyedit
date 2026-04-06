---
tags: [health, stats, missing-files, maintenance]
description: Project health tools — remove missing files, project summary, and tag stats.
---

# Health & Stats

DoxyEdit includes tools for maintaining project integrity and reviewing project statistics.

---

## Remove Missing Files

Source files sometimes move, get renamed, or get deleted. The **Remove Missing** tool finds all assets in the project whose source file no longer exists on disk and removes them from the project.

### How to Access

- **Tools > Remove Missing Files**
- Or the **Remove Missing** button in the Health panel

### Workflow

1. DoxyEdit scans every asset's `source_path`
2. Any asset whose file does not exist is listed
3. A confirmation dialog shows how many assets will be removed before proceeding
4. After confirmation, the assets are removed and the project is marked dirty (unsaved)

> [!warning]
> This action cannot be undone within the session. Save your project before running if you want a recoverable backup. A `.bak` file is created when you open the project, which you can restore manually if needed.

---

## Project Summary

**Tools > Summary** opens a compact dialog showing:

- Total asset count
- Tagged vs untagged count
- Starred count
- Platform slot assignment status (how many slots are filled vs pending)
- Tag usage overview

The same data is available via the CLI:

```bash
python -m doxyedit summary project.doxyproj.json
```

This outputs a JSON status overview suitable for Claude CLI integration.

---

## Tag Usage Stats

**Tools > Tag Usage Stats** shows a dialog with every tag and how many assets use it. Useful for identifying stale tags or tags applied to only a handful of assets.

---

## Clear Unused Tags

**Tools > Clear Unused Tags** removes any tag definitions from `tag_definitions` and `custom_tags` that are not applied to any asset. This cleans up the project after bulk removals.

---

## File Watcher

DoxyEdit's asset file watcher (**QFileSystemWatcher**) monitors source files for changes. If a file is modified on disk (e.g., you save a new version from Photoshop), the thumbnail is automatically regenerated without any manual action.

---

## Project Backup

When you open a project, DoxyEdit automatically creates a `.bak` backup of the project file in the same directory. This gives you a one-step rollback if something goes wrong.

---

## F5 Reload

**F5** reloads the project from disk. This picks up external edits made by Claude CLI or manual JSON edits without restarting DoxyEdit.

**Shift+F5** forces a thumbnail recache for all images (regenerates even already-cached thumbnails).

---

## Related

- [[Thumbnail Cache]] — cache management and clearing
- [[CLI Reference]] — CLI summary and status commands
- [[Import & Export]] — moving assets between projects
