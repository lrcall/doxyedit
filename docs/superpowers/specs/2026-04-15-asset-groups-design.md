# Asset Groups: Duplicates & Variants

**Date:** 2026-04-15
**Status:** Approved

## Problem

DoxyEdit has duplicate scanning (MD5) and similarity scanning (perceptual hash) but no persistent linking between related assets. Users can't click an asset and see its duplicates or variants highlighted in the grid. Groups are discovered, acted on once, then lost.

## Two Distinct Concepts

**Duplicate groups** — exact copies of the same file. "Pick one, the others are redundant." Conflict resolution: one is marked as keeper, the rest are extras.

**Variant sets** — related images meant to coexist. Color variants, pose variants, SFW/NSFW pairs, sequential frames. They belong together as a set.

These are fundamentally different: duplicates are a problem to resolve, variants are a relationship to preserve.

## Data Model

Two keys on `Asset.specs` (already serialized via `asdict()`):

| Key | Type | Meaning |
|-----|------|---------|
| `specs["duplicate_group"]` | `str` | Group ID (MD5 hash). All assets sharing this value are exact duplicates. |
| `specs["duplicate_keep"]` | `bool` | `True` on the one asset to keep per duplicate group. |
| `specs["variant_set"]` | `str` | Set ID (e.g. `"vs_a1b2c3"`). All assets sharing this value are variants. |

No new dataclass. No new top-level project fields. The `specs` dict is the extension point.

## Highlight Mode ("Link Mode")

### Toggle

New toolbar toggle button on the browser bar: **"Link Mode"** (icon: chain link or similar). Keyboard shortcut TBD.

### Behavior When Active

1. User clicks an asset in the grid.
2. System reads the clicked asset's `duplicate_group` and `variant_set` from `specs`.
3. All other assets sharing the same `duplicate_group` get a **red border** drawn by the delegate.
4. All other assets sharing the same `variant_set` get a **teal/blue border** drawn by the delegate.
5. The clicked asset retains its normal selection highlight.
6. Non-related assets remain normal (no dimming — keep it simple).
7. Clicking empty space or toggling Link Mode off clears all highlights.

### Always-Visible Indicators

Even outside Link Mode, the delegate draws small corner indicators on thumbnails:

- **Red dot** (top-right corner) — asset belongs to a `duplicate_group`
- **Blue/teal dot** (top-left corner) — asset belongs to a `variant_set`

These are always visible so grouped assets are identifiable at a glance.

## Group Creation — Four Paths

### 1. Duplicate Scanner (existing, enhanced)

The existing `Find Duplicates` tool (`_find_duplicates` in window.py) currently computes MD5 hashes and shows a dialog. Enhancement:

- In addition to tagging, write `specs["duplicate_group"] = md5_hash` on all members of each group.
- Mark the first asset in each group with `specs["duplicate_keep"] = True`.
- Dialog gains a new button: **"Link as Duplicate Groups"** (alongside existing Tag and Remove buttons).

### 2. Manual Variant Linking

- Multi-select 2+ assets in the grid.
- Right-click → **"Link as Variants"**.
- Generates a variant set ID: `"vs_" + uuid4().hex[:8]`.
- Writes `specs["variant_set"] = set_id` on all selected assets.
- If any selected asset already has a `variant_set`, merge into the existing set (use the first found ID).

### 3. Perceptual Hash Auto-Suggest

The existing `Find Similar Images` tool (`_find_similar` in window.py) already groups by phash distance. Enhancement:

- New button in the results dialog: **"Create Variant Sets"**.
- Each similarity group becomes a variant set.
- User sees the proposed groups and confirms before writing.

### 4. Filename Stem Auto-Detect

New tool action under Tools menu: **"Auto-Link Variants by Filename"**.

- Scans all assets and groups by shared filename stem.
- Stem extraction: strip trailing patterns like `_01`, `_02`, `_nsfw`, `_sfw`, `_color`, `_bw`, `_final`, `_v2` etc.
- Example: `dragon_01.png`, `dragon_02.png`, `dragon_nsfw.png` → stem `dragon` → one variant set.
- Shows a confirmation dialog with proposed groups before writing.
- Only creates groups of 2+ assets.

## Group Management (Right-Click Menu)

When right-clicking an asset that belongs to a group, add to the context menu:

**For duplicate groups:**
- "Select Duplicate Group (N)" — hard-selects all assets in the duplicate group
- "Mark as Keeper" — sets `duplicate_keep = True`, clears it on siblings
- "Remove from Duplicate Group" — clears `specs["duplicate_group"]` on this asset
- "Dissolve Duplicate Group" — clears `specs["duplicate_group"]` on all members

**For variant sets:**
- "Select Variant Set (N)" — hard-selects all assets in the variant set
- "Remove from Variant Set" — clears `specs["variant_set"]` on this asset
- "Dissolve Variant Set" — clears `specs["variant_set"]` on all members

These menu items only appear when the asset has the relevant `specs` key.

## Delegate Rendering Changes

`AssetDelegate.paint()` additions:

1. **Corner dots (always):**
   - Red 6px circle, top-right, if `specs.get("duplicate_group")`
   - Teal 6px circle, top-left, if `specs.get("variant_set")`

2. **Link Mode highlight borders (when active + asset clicked):**
   - 3px red border around duplicate siblings of the clicked asset
   - 3px teal border around variant siblings of the clicked asset
   - Drawn on top of the thumbnail, inside the cell rect

3. **Performance:** Build lookup dicts (`duplicate_group → [asset_ids]`, `variant_set → [asset_ids]`) once on refresh, stored on the browser. Delegate reads from these — no per-paint scanning.

## Lookup Index

`AssetBrowser` maintains two dicts, rebuilt on `_refresh_grid()`:

```python
self._duplicate_groups: dict[str, list[str]] = {}  # group_id → [asset_id, ...]
self._variant_sets: dict[str, list[str]] = {}      # set_id → [asset_id, ...]
```

Built by iterating `self._filtered_assets` once. The delegate and Link Mode selection handler reference these dicts.

## What This Does NOT Do

- No nested groups or group-of-groups
- No cross-project variant linking
- No automatic detection on import (run tools manually)
- No special sort/filter mode for groups (use existing tag filters or Link Mode to find them)
- No UI for renaming variant sets (the ID is internal)
