---
tags: [eagle, import, integration, planned]
description: Plan for importing Eagle app library metadata into DoxyEdit — tags, folders, stars, and notes.
---

# Eagle Integration

Eagle (eagle.cool) is a popular art asset manager with a well-documented local library format and REST API. This page documents the integration plan for importing Eagle metadata into DoxyEdit.

---

## Eagle Library Format

Eagle stores libraries as a folder with a `.library` extension:

```
MyLibrary.library/
  metadata.json           ← library name, creation date
  images/
    <item-id>/
      metadata.json       ← per-image: tags, folders, star, notes, url
      <filename>          ← original file (or symlink)
      <filename>_thumbnail.png
```

### Per-Image metadata.json

```json
{
  "id": "LX3K2J1ABC123",
  "name": "cover_art.psd",
  "size": 4820234,
  "ext": "psd",
  "tags": ["character", "cover", "finished"],
  "folders": ["LX3K2J1FOLDER1"],
  "isDeleted": false,
  "url": "",
  "annotation": "Main campaign cover",
  "rating": 4,
  "palettes": [...],
  "width": 3000,
  "height": 4000,
  "noThumbnail": false,
  "modificationTime": 1712345678000
}
```

---

## Eagle REST API

Eagle exposes a local HTTP API at `http://localhost:41595` while running.

### Useful Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/item/list` | All library items with full metadata |
| GET | `/api/folder/list` | Full folder tree |
| GET | `/api/item/info?id=<id>` | Single item metadata |
| POST | `/api/item/addFromPath` | Add a local file to Eagle library |
| POST | `/api/item/update` | Update tags, rating, annotation |

### Check if Eagle is Running

```python
import urllib.request
try:
    urllib.request.urlopen("http://localhost:41595/api/application/info", timeout=1)
    eagle_running = True
except Exception:
    eagle_running = False
```

---

## Integration Plan

### Phase 1 — Library Importer (no Eagle required)

A one-way import that reads an Eagle `.library` folder and maps metadata onto matching DoxyEdit assets by file path.

**Menu location:** `File > Import from Eagle Library…`

**Steps:**
1. Open a folder picker pointed at `*.library/`
2. Walk `images/*/metadata.json`
3. For each Eagle item, find a DoxyEdit asset whose `source_path` ends with the same filename (or full path match)
4. Map metadata:

| Eagle field | DoxyEdit field |
|-------------|---------------|
| `tags[]` | `asset.tags[]` (add, don't replace) |
| `rating` (1–5) | `asset.starred` (1–5) |
| `annotation` | `asset.notes` (prepend if non-empty) |
| `folders[]` | tag derived from folder name |

5. Show a summary dialog: "X assets matched, Y tags imported, Z stars updated"
6. Mark project dirty

**Non-destructive:** Only adds tags/stars — never removes existing DoxyEdit data.

### Phase 2 — Live Sync via API (Eagle must be running)

Bidirectional sync when both apps are open simultaneously.

- Tag changes in DoxyEdit → `POST /api/item/update` to Eagle
- Poll Eagle API every N seconds for changes → apply to DoxyEdit assets
- Or use Eagle's webhook/event system if available

**Complexity:** Medium. Requires matching DoxyEdit asset IDs to Eagle item IDs and maintaining a mapping table.

### Phase 3 — Push to Eagle

Send selected DoxyEdit assets into an Eagle library:

```python
POST /api/item/addFromPath
{
  "path": "C:/art/cover.psd",
  "name": "cover.psd",
  "tags": ["character", "cover"],
  "annotation": "asset notes here"
}
```

---

## Implementation Notes

### Path Matching

Eagle stores the original file in its library folder as a copy (not a reference to the original location). The `metadata.json` does not always contain the original source path.

**Matching strategy (in order):**
1. Exact `source_path` match if Eagle stores it in `url` field
2. Filename match: `Path(eagle_item["name"]).stem == Path(doxyedit_asset.source_path).stem`
3. Size + dimensions match as a tiebreaker

### Tag ID Normalization

Eagle tags are freeform strings. When importing, normalize to DoxyEdit tag ID format:
```python
def eagle_tag_to_id(tag: str) -> str:
    return re.sub(r'[^a-z0-9_]', '_', tag.lower().strip()).strip('_')
```

New tags get added to `tag_definitions` and `custom_tags` automatically.

### Folder → Tag Mapping

Eagle folders become DoxyEdit tags with the group `"eagle_folder"`. Folder hierarchy is flattened (depth 1 and 2 folder names become separate tags).

---

## Files to Create

| File | Purpose |
|------|---------|
| `doxyedit/eagle.py` | `EagleLibrary` class + `EagleApiClient` class |
| `doxyedit/eagle_import_dialog.py` | Import summary/progress dialog |

### EagleLibrary sketch

```python
class EagleLibrary:
    def __init__(self, library_path: str):
        self.path = Path(library_path)

    def iter_items(self):
        """Yield parsed metadata dicts for each image in the library."""
        for meta_file in self.path.glob("images/*/metadata.json"):
            try:
                yield json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                continue

    def get_folders(self) -> dict[str, str]:
        """Return {folder_id: folder_name} mapping."""
        meta = json.loads((self.path / "metadata.json").read_text(encoding="utf-8"))
        result = {}
        def walk(folders):
            for f in folders:
                result[f["id"]] = f["name"]
                walk(f.get("children", []))
        walk(meta.get("folders", []))
        return result
```

---

---

## Phase 4 — Export to Eagle Format (Planned)

Export a DoxyEdit project as a valid Eagle `.library` folder that Eagle can open directly.

### Output Structure

```
MyProject.library/
  metadata.json
  images/
    <asset-id>/
      metadata.json     ← mapped from DoxyEdit asset
      <filename>        ← copy or hardlink of source file
      <filename>_thumbnail.png  ← copy from DoxyEdit thumb cache
```

### Mapping: DoxyEdit → Eagle

| DoxyEdit field | Eagle metadata.json field |
|---------------|--------------------------|
| `asset.id` | `id` (use as-is or generate Eagle-format ID) |
| `asset.source_path` (filename) | `name` |
| `asset.tags[]` | `tags[]` |
| `asset.starred` (1–5) | `rating` (1–5) |
| `asset.notes` | `annotation` |
| `asset.source_folder` (last component) | `folders[]` → create matching folder entry |
| dims from `ThumbCache` | `width`, `height` |
| file extension | `ext` |
| file size (os.path.getsize) | `size` |
| current time | `modificationTime` (ms epoch) |

### library/metadata.json

```json
{
  "name": "<project name>",
  "description": "Exported from DoxyEdit",
  "folders": [
    { "id": "FOLDER_001", "name": "Characters", "children": [] },
    ...
  ],
  "smartFolders": [],
  "quickAccess": [],
  "tagsGroups": [],
  "modificationTime": 1712345678000,
  "applicationVersion": "4.0.0"
}
```

Folders are built from the unique `source_folder` values in the project, one Eagle folder per unique source folder.

### Per-Asset metadata.json

```json
{
  "id": "DOXYEDIT_cover_0",
  "name": "cover.psd",
  "size": 4820234,
  "ext": "psd",
  "tags": ["character", "cover", "finished"],
  "folders": ["FOLDER_001"],
  "isDeleted": false,
  "url": "",
  "annotation": "asset notes text",
  "rating": 4,
  "palettes": [],
  "width": 3000,
  "height": 4000,
  "noThumbnail": false,
  "modificationTime": 1712345678000
}
```

### File Handling Options

On export, present the user with a choice:
- **Copy files** — full copy of each source file into the `.library/images/<id>/` folder (large but fully portable)
- **Thumbnails only** — copy only the cached thumbnail as the "file" (small, but Eagle preview only)
- **Skip file copy** — write metadata only; Eagle will show broken previews but metadata is intact

### Menu Location

`File > Export > Export as Eagle Library…`

Opens a folder picker (choose where to save `<ProjectName>.library`), then a small options dialog (file handling mode), then runs export with a progress bar.

### Implementation Notes

- Eagle item IDs must be 13-char alphanumeric strings. Use `asset.id` padded/hashed to fit, or generate with `secrets.token_hex(6).upper()[:13]`.
- Thumbnail filenames in Eagle are `<original_filename>_thumbnail.png`. Copy from `DiskCache` if available.
- Eagle expects the source file to be **inside** the item folder — it does not reference external paths. For "copy" mode, `shutil.copy2` each file.
- Folder IDs also need to be Eagle-format strings — generate deterministically from folder path hash.

---

## Related

- [[Import & Export]] — existing import workflow
- [[Tagging System]] — tag ID naming rules
- [[Project File Format]] — asset schema
- [[Roadmap]] — feature backlog
