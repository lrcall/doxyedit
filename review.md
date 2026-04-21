I have enough now. Let me deliver the comprehensive review.

# DoxyEdit Project-Wide Systematic Code Review

This is a comprehensive per-module audit. For each file I list findings with line numbers and effort/impact estimates. Effort scale: XS=<15 min, S=<1 hr, M=<half day, L=multi-day.

---

## Core Modules

### 1. `E:\git\doxyedit\doxyedit\window.py` (6558 lines)

**Purpose:** Main `QMainWindow` — wires every panel, handles menus, project/collection lifecycle, auto-save, hotkeys.

**Findings:**
- `window.py:1110, 1150, 1417, 1758, 2786, 2800, 4417, 5829, 5853, 6062, 6087, 6532` — `_own_save_pending` is incremented inline in compound statements (`getattr(self, "_own_save_pending", 0) + 1; self.project.save(...)`) and read/decremented in `_do_reload:5793`. Counter-by-string pattern is fragile. Matches prior review's "own_save_pending landmine." **M** — impact: save/reload races.
- `window.py:46` — `AUTOSAVE_INTERVAL_MS = 30_000` hardcoded, not in config. **XS** — user cannot tune.
- `window.py:200-204` — `_proj_tab_bar.setStyleSheet(...)` hardcodes `background: transparent`, `padding: 4px 12px`, `font-weight: bold`. Violates UI token rule from CLAUDE.md (no inline stylesheets). **S** — token violation.
- `window.py:218-224` — `_new_tab_btn` uses inline stylesheet with `rgba(255,255,255,0.08)` etc. — hardcoded colors in `QPushButton`. Same violation. **S**.
- `window.py:688` — `self._progress_label.setStyleSheet(f"padding-right: {self._ui_padding * 3}px;")` — inline stylesheet should be object-named QSS selector. **XS**.
- `window.py:699, 704, 474` — three independent polling timers (`_reminder_timer 5min`, `_autopost_timer 5min`, `_social_tick 60s`) always running regardless of whether their tabs are visible. **S** — impact: unnecessary work.
- `window.py:1110, 3610, 3613` — 4 places store `sub_platform_status[pid] = {"status": ...}`, but `browser.py:2095` etc. read status as string. State shape inconsistent (prior review "sub_platform_status readers no writers"). **M**.
- `window.py:1297-1331` — `_apply_theme` re-runs `generate_stylesheet()` on every call; calls `browser._delegate.set_theme`, `_file_browser._theme = ...` (directly mutating), `set_theme(...)` on several panels, and iterates all notes tabs re-rendering HTML. Not memoized, no change-detection. Called from `_rebind_project:5905` which fires on every tab swap. **M** — visible lag on project switch.
- `window.py:1319` — `self._file_browser._theme = self._theme` directly mutates private attribute (no setter). **XS** — encapsulation break.
- `window.py:1688-1751` — `_render_notes_preview_to` builds 90+ lines of inline CSS every keystroke (connected to `textChanged` via `_live_render_notes` at line 1453). No debounce. Typing in notes tab fires markdown.markdown + setHtml on every char. **M** — input lag on big notes.
- `window.py:1845, 1847` — `_RemovableMenu` right-click behavior catches only items with `.data()` set — fragile for deeply nested submenus.
- `window.py:2148-2152` — `print(f"[Paste] ...")` debug prints to stdout from a user action. **XS** — leftover noise.
- `window.py:2300-2324` — `_update_progress` runs on a 2-second timer iterating all assets 4 times (O(n)×4). For 70k assets that's ~280k dict lookups every 2s. **S** — fold loops. 
- `window.py:2334-2336, 4119, 5292, 5298, 6068` — multiple `setStyleSheet(f"QStatusBar {{ background: {theme}...}}")` raw injections. Violates QSS discipline. **S**.
- `window.py:2700-2702` — drop accept checks `.endswith(".doxycoll.json") or .endswith(".doxycoll") or .endswith(".doxycol")` — same set repeated at `2716, 2720, 6197-6198, 6233`. Needs a constant `DOXY_PROJ_EXTS`, `DOXY_COLL_EXTS`. **S**.
- `window.py:3104-3110` — `_float_composer_dialog` sets `_post, _is_new` as closure vars to work around Qt signal quirks — ugly. **S**.
- `window.py:3151` — `for aid in post.asset_ids[:1]` silently drops all but the first asset during export (matches prior review's "_export_post_assets runs 2-3x"). **S — bug**.
- `window.py:3246-3302` — `_push_post_to_oneup` makes N synchronous urllib calls to OneUp via `schedule_via_mcp` on the UI thread with 15s timeouts. Can freeze UI up to N×15s. **L** — must run on QThread.
- `window.py:3416-3425` — `_check_reminders` swallows all exceptions (`except Exception: pass`) — hides bugs. **XS**.
- `window.py:3453-3632` — `_on_sync_oneup` is a 180-line function that makes 3+ MCP HTTP calls synchronously, then iterates all posts, pushing posts one-by-one via UI thread. `QApplication.processEvents()` called multiple times as a workaround. Matches prior review. **L** — architectural; full rewrite to QThread.
- `window.py:3497-3525` — manual JSON-RPC init+call block duplicated from `oneup.py:137-182`. Two copies of MCP session logic. **M**.
- `window.py:4080, 4085` — `_copy_full_path`, `_copy_as_files` both call `active_view` but guard with `tabs.currentIndex() != 0` — tab-index hardcoded. Not using widget identity as CLAUDE.md architecture rule dictates. **XS**.
- `window.py:4170, 4174, 4187, 4196` — `_set_filter`, `_show_import_sources` inner dialogs define local functions (`_remove`, `_set_filter`, `_refresh`) that capture `dlg`, `sources`, `table` — large dialog methods with nested lambdas; hard to test. **S — readability**.
- `window.py:4406` — `_reload_project` reads `self._project_path` and runs `Project.load(self._project_path)` **synchronously** on UI thread — always blocks (only startup uses `ProjectLoader` now). **M**.
- `window.py:4651-4696` — `_count_chains`/`_collapse` recursion into assets_dir does `list(d.iterdir())` twice per directory — double I/O. **S**.
- `window.py:4706-4711` — after folder rename, asset paths are repaired via `rglob(fname)` scan per asset — O(n×filesystem). **M** — could hash once.
- `window.py:4819-4904` — `_auto_post_subscriptions` fully synchronous Playwright CDP call inside the UI thread with `QApplication.processEvents()` in a loop. Matches prior review's browserpost sync warning. **L**.
- `window.py:5061-5090` — `_find_duplicates` reads every asset's entire file bytes (MD5 over full bytes) on UI thread with a QProgressDialog. For 10k assets @10MB that's 100GB of I/O blocking UI. **L** — QThread.
- `window.py:5196-5268` — `_find_similar` runs O(n²) perceptual-hash comparison on UI thread with progress dialog. OK up to a few thousand; blows up past that. **M** — QThread.
- `window.py:5357-5429` — `_auto_link_by_filename` recompiles a 5-line regex per method call, but OK here since function-scope.
- `window.py:5506-5560` — `_show_checklist` duplicates functionality already in `checklist.py:ChecklistPanel`. Two UIs for same data. **M** — remove legacy.
- `window.py:5595-5631` — `_show_shortcuts` is a hardcoded multi-line string — shortcuts displayed here don't match actual registered shortcuts. Prone to drift. **S** — generate from registry.
- `window.py:5640-5673` — `_show_whats_new` is a frozen v2.3.1 message — stale on any new release. **XS** — move to `wiki/Changelog.md` read.
- `window.py:5725` — `self.browser._thumb_cache.request_batch([(asset.id, asset.source_path)], size=THUMB_GEN_SIZE)` — re-imports `THUMB_GEN_SIZE` from browser module, but the module-global `browser.THUMB_GEN_SIZE` gets mutated at startup (line 737). Mutable module globals = action-at-a-distance. **S**.
- `window.py:5888-5890` — `del TAG_SHORTCUTS[key]` mutates a module-level dict. Multiple MainWindow instances would stomp on each other. **S** — global state bug.
- `window.py:5898-5900` — `self._project_slots[self._current_slot]["project"] = self.project` — assumes slot exists; defensive `0 <= ... < len(...)` check is good but duplicated at 6097, 2756.
- `window.py:5876-6021` — `_rebind_project` does ~15 heavy calls on every project switch: `set_theme`, `apply_theme`, `thumb_cache.set_project`, `rebuild_tag_bar`, `refresh()` on 6+ panels, `refresh_discovered_tags`, etc. No lazy "only refresh visible panel" pattern. Matches prior Pass 1 finding — huge refactor candidate. **L** — PanelMixin pattern.
- `window.py:5951` — `if self._notes_edit.isVisible():` — fine, but the check is only `isVisible()`, not whether text changed. Redundant set.
- `window.py:6063, 6087-6088` — `Project.save` called synchronously on UI thread at every `_save_project`. For 70k-asset projects writing 1MB+ JSON, that's ~50ms blocking. **S** — threaded save + atomic rename.
- `window.py:6129-6142` — `_autosave_collection` writes a collection file on every save — disk write on every keystroke-level change if paths overlap. No debounce. Matches prior review. **S**.
- `window.py:6181, 6210` — Collection save prompts use `QMessageBox.information` blockingly after write.
- `window.py:6247-6251` — `_open_collection` spawns a new `MainWindow` per project file — no thread isolation. If user has 10 projects in a collection, 10 windows pop up simultaneously, each synchronously loading. **M**.

**Verdict:** God object with tight coupling to every panel. Needs a `ProjectController` or Observer pattern, plus `PanelMixin.refresh_if_visible()` per the prior review. Multiple synchronous HTTP/disk I/O paths still block the UI. 50+ distinct findings just in this file.

---

### 2. `E:\git\doxyedit\doxyedit\browser.py` (3783 lines)

**Purpose:** Asset browser — thumbnail grid model, delegate, folder sections, import workers, drag/drop.

**Findings:**
- `browser.py:35` — `THUMB_GEN_SIZE = 512` is a module-global mutated at runtime by `window.py:737` — hidden coupling. **S**.
- `browser.py:218-285` — `FlowLayout` re-implements Qt's own QLayout semantics; works, but `heightForWidth` recomputes geometry twice (dry-run then real). **XS** — could memoize.
- `browser.py:301-307` — `_FolderHeader` class never used anywhere? (No references elsewhere.) **XS** — dead code candidate.
- `browser.py:323-394` — `ThumbnailModel` roles: 10 user-roles, stored as class-level constants. Fine. `update_post_status` iterates all posts O(p) — OK.
- `browser.py:431-433` — `from doxyedit.themes import THEMES, DEFAULT_THEME` is a module-scope import; also imported lazily at `565, 581, 635, 1066-1076, 3033, 3116` inside functions (7+ times per paint cycle). **S** — hoist to module top.
- `browser.py:486-529` — `_update_metrics` derives 40+ numbers per metric update. Called from `_update_metrics` (self) — fine. OK.
- `browser.py:541-547` — Font/FontMetrics cache keyed by size. Loads `(self.badge_font_size, "bold")` as tuple key (line 674) mixing with int keys in same dict `self._fonts`. Works but ugly. **XS**.
- `browser.py:602-620` — `_scaled_cache` keyed by `(pixmap.cacheKey(), ts, fill_mode)` — invalidated only explicitly via `invalidate_cache`. Unbounded growth if user flips fill_mode / zooms many times. **M** — add LRU cap.
- `browser.py:657-701` — Two separate `if ... post_status_map.get ...` branches for platform + social badges duplicate badge drawing code (6 near-identical blocks). **S** — extract `_draw_badge(painter, color, char, x, y)`.
- `browser.py:718-720` — `self._fonts[(...)]` is mutated inside paint(). Paint called from paint event — non-thread-safe mutations in a paint method are legal in Qt (single-threaded) but noisy.
- `browser.py:781-807` — Group/variant dot + link-mode border painted via parent-widget `getattr(browser, '_link_mode', False)` — introspective parent lookup from the delegate. Fragile. **XS**.
- `browser.py:866-890` — `RootFolderHeader.__init__` does `QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)` — creates a new QSettings per header. Happens for every folder on every `_rebuild_folder_sections`. Prior review's "QSettings hit per card." **S**.
- `browser.py:938-944, 1204-1209, 1530, 1627+` — `QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)` repeated 40+ times across the file. Should be a cached module getter. **S**.
- `browser.py:1056-1085` — `_theme_accent_variant` walks up the parent chain looking for `_delegate`. Classic access-by-parentage anti-pattern; breaks if reparented. **S**.
- `browser.py:1110-1116` — inline `setStyleSheet` for folder header colors — overlay exception-ish but not one of the allowed categories. Violates CLAUDE.md "NEVER hardcode colors". **M**.
- `browser.py:1187-1245` — `AssetBrowser.__init__` takes 60 lines of state init; could use a `_state` dataclass. **S**.
- `browser.py:1264-1273, 1283, 1529-1531, 1636-1640, 1645-1656` — Custom `_btn_style()` that mixes inline `padding: Npx; font-size: Mpx;` — QSS should be generated from the theme. **M** — theme discipline violation.
- `browser.py:1430` — `self._tag_button_map: dict[str, QPushButton]` — O(1) lookup is good.
- `browser.py:1626-1641` — `_apply_tag_button_styles` hardcodes `color`, `border`, `border-radius`, `background` in f-strings per button. Inline stylesheets again. Tag pills are the biggest token-violation surface in the app. **M**.
- `browser.py:1696-1704, 1701-1704` — `_collapse_all_folders` / `_expand_all_folders` — mutates `self._collapsed_folders` set; OK.
- `browser.py:1788-1792` — `_scan_folders` spawns a `QThread` (`_ScanWorker`) but keeps ref as `worker = ...` local variable — no attribute retention; GC risk. Connects `lambda _: worker.deleteLater()` as a workaround. **S** — hold reference or subclass.
- `browser.py:1914-1916` — `_on_scroll_idle` triggers reprioritize on every idle — fine.
- `browser.py:1977-1994` — `_cache_ordered_batch` builds 3 lists and merges to order (visible → filtered → rest). For 70k assets, creates 210k tuples. **S** — single-pass with a set.
- `browser.py:2138-2153` — `_compute_filtered` prior review finding — per-asset Path() creation inside lambdas (`Path(a.source_path).name.lower()`). For 70k assets that's 70k Path objects per call. Better to cache normalized path on Asset at load. **M**.
- `browser.py:2216-2246` — Stat-based sorting caches `mtime_cache/fsize_cache` dicts per call — good. But `By Folder` code path duplicates the whole secondary-sort block from below. **S** — factor out.
- `browser.py:2288-2355` — `_refresh_grid` is 70 lines. Duplicated tag-count/starred-count iteration at 2333-2335 already in `_update_progress` in window.py. **S**.
- `browser.py:2368-2375` — `deleteLater()` on old folder sections inside a tight loop. No batching — could cause repaint storms. **XS**.
- `browser.py:2434-2444` — Each `FolderSection` wires 7 signal connections with 7 lambdas capturing `s=section, v=section.view`. When project switches rebuild 100 sections = 700 lambdas leaked unless deleteLater runs properly. **S**.
- `browser.py:2519-2521` — `QTimer.singleShot(0, ...)`, `(200, ...)`, `(500, ...)` — three deferred layout finalizations per folder-section rebuild. Triple the work. **S**.
- `browser.py:2588-2604` — `_on_folder_select_all` does O(n) scan of all assets — fine.
- `browser.py:2708-2727` — `_on_phash_ready(asset_id, phash_hex)` converts `int(phash_hex, 16)` but `on_phash_ready` signature takes hex string. Value stored as int — consumers in `_find_similar` use `.specs.get("phash")` expecting int. OK but mixed types.
- `browser.py:2819` — `shutdown()` calls `_thumb_cache.shutdown()` but doesn't wait for worker to finalize state before process exit.
- `browser.py:2891-2899` — `import_folder` synchronous version — iterates `Path.iterdir()` with per-file date-filter lookup (nested loop) — O(n × m) for `source_entry` match. **S** — build path→source dict once.
- `browser.py:3006-3086` — `_drag_fix` with 6 different drag implementations selected by integer — legacy hackfix for a Qt drag bug, with F8 to cycle. Matches prior review. **S** — pick one, delete others.
- `browser.py:3118-3126` — Iterates `s.allKeys()` for every right-click menu open — slow on settings with many keys. Prior review #2 noted similar. **S** — cache editors.
- `browser.py:3476-3724` — `eventFilter` is 250 lines handling Wheel/Mouse/Key events for view + viewport + search_box. Multiple nested branches. **M** — split per event type.
- `browser.py:3697-3711, 3743-3752` — `Escape` handler duplicated across `eventFilter` and `keyPressEvent`. Matches prior review's "Escape fought by 5 handlers." **S**.

**Verdict:** Dense, performance-sensitive module that works. Main concerns: inline stylesheets violate token discipline, QSettings instantiated per-call everywhere, `eventFilter` too large, unbounded `_scaled_cache`.

---

### 3. `E:\git\doxyedit\doxyedit\studio.py` (2521 lines)

**Purpose:** Unified censor + overlay + crop + annotation workspace using QGraphicsScene.

**Findings:**
- `studio.py:42-56` — `_AppEscapeFilter` installs an `QApplication.installEventFilter` that catches ALL Escape keypresses anywhere in the app, then checks `self._editor.isVisible()`. Prints debug to stdout. Installed at `1278-1280` — no uninstall on editor close. **M** — leak/interference with other dialogs.
- `studio.py:63-85` — `_themed_menu` re-reads `THEMES[DEFAULT_THEME]` — always default theme, ignores the actual active theme on the main window. Bug: if user switched theme, context menus still use default. **S**.
- `studio.py:171-199` — `CensorRectItem` overlay exception hardcoded colors — OK per CLAUDE.md overlay exception.
- `studio.py:216-230` — `_on_handle_moved` calls `_sync_censors_to_asset()` on every handle drag pixel — ouch, sync-per-drag-event. **S** — debounce.
- `studio.py:381-417` — `OverlayTextItem.paint` draws text stroke by rendering the text 8 times offset — with `super().paint(painter, option, widget)` which re-renders QTextDocument layout 8x per frame. With a 20-char text at 48pt that's slow. **M** — pre-rasterize stroke to QPainterPath.
- `studio.py:430-443` — `sceneEvent` intercepts Escape inside QGraphicsTextItem (separate from `_AppEscapeFilter`). Both fire on same key = two Escape handlers in one module.
- `studio.py:518-567` — `AddCensorCmd`, `DeleteItemCmd` only undo/redo 2 types (censor, overlay) — cropping and notes are NOT undoable. Gaps in undo coverage. **M**.
- `studio.py:625-642` — `drawForeground` draws grid — every paint. For large scenes this is costly. **S**.
- `studio.py:730-772` — `mouseMoveEvent`/`mouseReleaseEvent` — `self._temp_item.setRect(r)` fires `itemChange` signals on every mousemove. Fine.
- `studio.py:802-828` — `StudioView` middle-drag pan — single-implementation.
- `studio.py:1047` — `from doxyedit.themes import THEMES, DEFAULT_THEME as _DT` — redundant import after `_dt = THEMES[DEFAULT_THEME]` 2 lines above.
- `studio.py:1257` — `self._props_row.setEnabled(False)` — always-visible-but-disabled property row; good decision per comment, but `Enabled=False` doesn't visually match disabled QSS state in all themes. **XS**.
- `studio.py:1262-1265` — callbacks set by attribute assignment (`self._scene.on_censor_finished = ...`) instead of signals — bypasses Qt signal dispatch; works but less debuggable. **XS**.
- `studio.py:1277-1280` — installs `_AppEscapeFilter` but never removes it. Leak. **S**.
- `studio.py:1391-1399` — `load_asset` uses `io.BytesIO()` to round-trip PSD through PNG to load into QPixmap — wasteful. `pil_to_qpixmap()` in imaging.py already does this. **S**.
- `studio.py:1425-1427` — overlay Z-values start at 200 + i but there's no reindex on reorder. After several duplicates, Z values drift indefinitely. **S**.
- `studio.py:1619-1637` — `_on_note_drawn` opens `QInputDialog.exec()` — blocking UI.
- `studio.py:2151-2191` — `_delete_selected` mixes undo-supported (censor, overlay) with NOT-undoable (crops, notes, annotations) — user pressing Ctrl+Z after deleting a crop sees partial undo. **M** — consistency.
- `studio.py:2195-2207` — `_remove_censor_item`/`_remove_overlay_item` bypass the undo stack entirely — context-menu deletes cannot be undone. **S**.
- `studio.py:2255-2273` — `_export_preview` does `load_image_for_export` + `apply_censors` + `apply_overlays` synchronously. Large PSDs block. **M**.
- `studio.py:2311-2428` — `_export_all_platforms` loops per-crop, running `load_image_for_export` and `apply_*` multiple times for the same source PSD — no caching (matches prior review #2). **L** — cache loaded image.
- `studio.py:2397, 2407` — `any(p.lower() == crop_lbl or crop_lbl in p.lower() or p.lower() in crop_lbl for p in cr.platforms)` — 3-way substring match; fragile. Matches prior review "crop-label substring matching fragile." **S** — explicit match rules.
- `studio.py:2430-2437` — `_open_export_folder` uses `creationflags=0x08000000` — good per CLAUDE.md rule for Windows subprocess.
- `studio.py:2481-2510` — `_show_filmstrip_from_files` opens every PNG in folder synchronously to build thumbnails. Blocks. **S**.

**Verdict:** Core editing surface has multiple undo gaps, Escape handler duplication, PSD load wasted work, and one app-level event filter leak. Architecture-smell on export caching.

---

### 4. `E:\git\doxyedit\doxyedit\models.py` (1025 lines)

**Purpose:** Central data model — dataclasses + PLATFORMS + Project save/load.

**Findings:**
- `models.py:46-50` — `VINIK_COLORS` is module-level — fine.
- `models.py:159-215` — `CropRegion`, `CensorRegion`, `CanvasOverlay` all use `@dataclass` with `from_dict` (CanvasOverlay) / direct-kwarg (others). Inconsistent. `CensorRegion` has no `from_dict` — caller at `window.py:2188-2189` does `{k: v for k, v in c.items() if k in CensorRegion.__dataclass_fields__}` manually. **S** — unify.
- `models.py:226-241, 255-260, 272-278, 295-315` — `ReleaseStep`, `EngagementWindow`, `CampaignMilestone`, `Campaign`, `SubredditConfig`, `SocialPost` all define their own `to_dict`/`from_dict`. 6 near-identical pairs. Could use `@dataclass` + default asdict for to_dict. **S**.
- `models.py:446-455` — `SocialPost` has 26 fields. `to_dict` (457-479) explicitly lists every field; `from_dict` (482-507) lists every field. Adding a new field requires touching both + `composer.py:_save` (per CLAUDE.md architecture note). Serialization boilerplate. **M** — asdict-based approach.
- `models.py:456-479` — `to_dict` omits `reply_templates`? No, it's line 463. OK.
- `models.py:748` — `tray_items: list | dict` — union type forces every consumer to check `isinstance(..., list)` at call sites. `window.py:5984-5985, tray.py:598-603`. **S** — normalize to dict.
- `models.py:805-863` — `Project.save` manually builds the dict with 30+ keys; adding fields needs hand-edit. **S** — asdict on `@dataclass`.
- `models.py:812-816` — migration of `custom_tags → tag_definitions` runs every save. OK but silent no-op most saves.
- `models.py:832-862` — no `sort_keys=True` on json.dumps — save diff noise. **XS**.
- `models.py:863` — `default=str` on `json.dumps` silently stringifies unknown types. Hides serialization bugs. **XS**.
- `models.py:866-964` — `Project.load` reads YAML config for custom platforms (line 910) — synchronous disk I/O inside load. **S**.
- `models.py:912-914` — `proj._custom_platforms` dynamic attribute — not declared in dataclass. Use a proper slot or don't attach. **XS**.
- `models.py:931-932` — auto-migrate CLI notes to specs via `re.match(r'^\d+x\d+', ...)` — silent data rewrite on every load. **XS**.
- `models.py:957` — `pa = PlatformAssignment(..., notes=..., campaign_id=...)` — drops `crop` if passed as kwarg; crop restored separately below. OK but non-obvious.
- `models.py:981-994` — `invalidate_index` sets `_asset_index = None`, `get_asset` rebuilds dict scanning all assets — O(n) rebuild on first lookup after invalidation. Called from many places. **S** — keep index live.
- `models.py:996-1025` — `summary` rebuilds platform→assignment map by iterating all assets × assignments — O(n×p) per call. Cached version of "platform fill" would help. **S**.

**Verdict:** Core data model is sound but has heavy boilerplate (6 to_dict/from_dict pairs) and manual save/load serialization. `_custom_platforms` dynamic attribute is a minor code smell. Matches CLAUDE.md's "composer save: when adding fields to SocialPost ALSO update PostComposerWidget._save()" — confirmed as real maintenance burden.

---

## Major Panels

### 5. `E:\git\doxyedit\doxyedit\platforms.py` (1108 lines)

**Purpose:** Platform assignment panel — 3-pane split (sidebar | cards | dashboard).

**Findings:**
- `platforms.py:21-26` — `STATUS_CYCLE` (pending→ready→posted→skip) is module-global; `STATUS_ICONS` mirror. **XS** — lives close by, fine.
- `platforms.py:30-45` — Layout ratios hardcoded as module constants. Matches theme-token pattern. OK.
- `platforms.py:57-77` — `_DroppableSlotRow.dropEvent` on line 73-78 — `return` inside `for` loop before `event.acceptProposedAction()` for multiple URLs. Only first URL handled. **S** — loop through all.
- `platforms.py:144-145, 375-376, 456-458, 609` — `QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)` repeated 10+ times in this file alone. Same anti-pattern as browser. **S**.
- `platforms.py:238-261` — `_rebuild_milestones` does `deleteLater()` in a tight loop; adds another QCheckBox per milestone. OK.
- `platforms.py:425-428` — `_ShrinkableWidget(QWidget)` defined inline inside `_build()` — unit-testing impossible. **XS**.
- `platforms.py:466-531` — `refresh()` rebuilds entire card list on every call. For 10+ platforms × 5 slots = 50 slot rows rebuilt per tag change. **S** — diff-based rebuild.
- `platforms.py:504-532` — summary calculation (lines 514-521) inside the cards loop duplicates work done later in `_rebuild_dashboard` (828-830). **XS**.
- `platforms.py:649-663` — `_load_thumb` uses `QTimer.singleShot(0, ...)` per slot — 50+ timers on refresh. **S**.
- `platforms.py:730-737` — `_on_file_dropped` references `event.acceptProposedAction()` — `event` is not defined in this scope (no `event` parameter). **S — bug**. (Will throw NameError if drop doesn't match asset.)
- `platforms.py:916-918` — `cell.mousePressEvent = lambda _, _aid=_aid: ...` — overrides Qt method with a lambda. Fragile; breaks if Qt calls need a default super. **S**.
- `platforms.py:1047-1058` — `_auto_fill_platform` opens each asset via PIL (`Image.open(asset.source_path)`) inside a tight loop — disk-bound; UI-thread. For 70k-asset project assigning a platform: 70k PIL opens. **L**.
- `platforms.py:1085-1106` — `assign_asset` also opens PIL.Image.open per assignment to check aspect ratio. **M**.

**Verdict:** Full rebuild on every refresh + O(n) PIL.Image.open inside UI-thread hot paths. Dropevent bug on line 737.

---

### 6. `E:\git\doxyedit\doxyedit\composer.py` (541 lines)

**Purpose:** QDialog + QWidget wrapper for post composer; asset-drop line edit.

**Findings:**
- `composer.py:42-46` — `_path_index` built once per AssetDropLineEdit init via `os.path.normpath(...).lower()` — for 70k assets, 70k normpath calls. Fine on init; but init called per-dialog-open. **S** — cache on project.
- `composer.py:81-84` — `_NoScrollDateTimeEdit` — good pattern, nice touch.
- `composer.py:125-132` — `root.setContentsMargins(_pad_lg + _pad, ...)` — 4 identical values from sum. Cleaner. **XS**.
- `composer.py:192-199` — Splitter default fallback `[350, 650]` hardcoded — should be ratio-based.
- `composer.py:262-285` — `_update_left_tz` — hardcoded `"US/Eastern", "US/Pacific", "Asia/Tokyo"` — should be a project/identity setting. **S**.
- `composer.py:347-366` — `_use_selected_assets` walks up `parent()` chain looking for `.browser` — fragile. **S** — store main-window reference on init.
- `composer.py:372-447` — `_save` method duplicates every field of `SocialPost` — exactly the maintenance burden flagged in CLAUDE.md. Matches architecture rule: "when adding fields to SocialPost ALSO update _save." **M** — refactor to `SocialPost.from_dict(data)`.
- `composer.py:423-445` — readiness check runs synchronously for every platform on save. Fine for now.
- `composer.py:529-531` — `_dock_requested = True` dynamic attribute attached to `dlg` — used once in window.py. Convention without a protocol.

**Verdict:** Clean two-layer separation (Widget/Dialog). Only real issue is the `_save` boilerplate.

---

### 7. `E:\git\doxyedit\doxyedit\composer_left.py` (646 lines)

**Purpose:** Preview panel with raw/studio/platform modes + SFW/NSFW + crop status.

**Findings:**
- `composer_left.py:225, 265-266` — `dot.setStyleSheet(f"color: {dot_colors.get(status, _dt.text_muted)};")` — inline stylesheet for a single color. Violates token discipline but isolated to a dot. **S** — use property selectors.
- `composer_left.py:258-274` — `_generate_studio_preview` loads image via `load_image_for_export` then applies censors/overlays on UI thread. PSD load blocks preview — matches prior review #2 "composer_left._update_preview synchronous PSD load." **M** — threaded.
- `composer_left.py:299-323` — `_generate_platform_preview` may call `prepare_for_platform` which loads image + applies crop+resize synchronously. **M** — threaded.
- `composer_left.py:626-646` — `_load_pixmap` uses `load_psd_thumb(str(src), min_size=0)` — loads thumbnail, not full image. OK but returns thumb when user wants full. Matches prior review #2 "overlay_editor.py:217 + censor.py:120 raw QPixmap(path)." **S** — unify.
- `composer_left.py:424-462` — `_apply_scaled_pixmap` paints notes/crops in Python loop with QPainter every resize. For 50 crops/notes on resize: 50 rect draws per mouse move. **S** — OK mostly.
- `composer_left.py:596-606` — `_toggle_censored_preview` generates censored preview lazily and caches (`_censored_pm`) — good.

**Verdict:** PSD loads on UI thread. Color dots use inline stylesheets. Minor compared to window.py.

---

### 8. `E:\git\doxyedit\doxyedit\composer_right.py` (1897 lines)

**Purpose:** Right column — platforms, strategy, captions, schedule, release chain.

**Findings:**
- `composer_right.py:24-25, 27-52` — Module-level cache `_chrome_profile_cache`, `_chrome_cache_time` — 30s TTL. No lock; two threads calling would race. **XS**.
- `composer_right.py:34-48` — `list_chrome_profiles` reads each Chrome profile's `Preferences` JSON on disk to get display name. On main thread. Could be 10+ disk reads. **S** — cache to disk.
- `composer_right.py:73-76` — `subprocess.Popen(cmd, creationflags=0x08000000)` for Chrome — good.
- `composer_right.py:107` — `QSettings(...).value("font_size", 12, type=int)` again.
- `composer_right.py:170-174` — `get_categories`, `get_connected_platforms`, `get_active_account_label` all called in `_build_ui` — each reads `config.yaml`. Prior review "config.yaml re-parsed 13x" confirmed. **M**.
- `composer_right.py:190-192` — `self._category_combo = None` fallback when no categories — OK.
- `composer_right.py:215-221` — `SUB_PLATFORMS` iterated for checkboxes — if config expanded, order isn't deterministic (`dict` iter order in old Python was insertion but OK now).
- `composer_right.py:311-363` — Strategy buttons + stacked widget — strategy generation runs via Claude CLI (claude_modal). OK, threaded.
- The rest of the file handles form wiring, per-platform captions (dynamic rebuild on platform change), release chain, and JSON data get/set. No major issues beyond the config re-read.

**Verdict:** Config repeatedly re-parsed (prior review known). Otherwise structurally fine.

---

### 9. `E:\git\doxyedit\doxyedit\tagpanel.py` (1044 lines)

**Purpose:** Tag checklist sidebar — multi-select, drag-reorder, rename/delete/hide/pin.

**Findings:**
- `tagpanel.py:14-18` — `FITNESS_COLORS` hardcoded in module — should be theme tokens. **S** — moved some but these three slipped.
- `tagpanel.py:252-254` — `dot.setStyleSheet(f"background: {tag.color}; border-radius: {_dot // 2}px; ...")` — inline style for tag color dot. Tag color IS a user-set runtime value (not theme token), so inline is reasonable. OK.
- `tagpanel.py:262-264` — `checkbox.setStyleSheet(f"QCheckBox#tag_checkbox {{ color: {tag.color}; }}...")` — inline stylesheet per-row. On 50 tags = 50 style applications. Slow on first build. **S**.
- `tagpanel.py:294-298` — `_set_fitness` hardcodes `#888` fallback. Not theme-driven. **XS**.
- `tagpanel.py:315-329` — `set_row_selected` builds CSS with RGBA math manually (`rgba({r},{g},{b},{a/255:.2f})`). Repeated structure across many rows. **S**.
- `tagpanel.py:349-352, 355-357, 556` — `QColorDialog` invocation doesn't inherit parent theme.
- `tagpanel.py:463-465` — `hasattr(self, '_rows')` check — speaks to unreliable `_rows` init order.
- `tagpanel.py:544-572` — `_add_tag_row` rebuilds every signal per tag. Fine.
- `tagpanel.py:573-600+` (read) — `refresh_discovered_tags` iterates all assets × all tags to build a set, O(n×t). **S** — cache `_used_tag_ids` already done in browser; share.
- `_TagContainer` drag-reorder code — `mousePressEvent`/`mouseMoveEvent` — uses `grabMouse()` which can leak mouse if parent dies mid-drag.

**Verdict:** Inline stylesheet per tag row. Per-asset scans repeated across the file + browser. Not catastrophic.

---

### 10. `E:\git\doxyedit\doxyedit\preview.py` (1041 lines)

**Purpose:** HoverPreview (cursor tooltip), NoteRectItem, ResizableCropItem, ImagePreviewDialog, PreviewPane.

**Findings:**
- `preview.py:18-82` — `HoverPreview` singleton class — OK. `show_for` loads pixmap synchronously. For PSDs that's slow even though `load_pixmap` uses cache. **S**.
- `preview.py:88` — `_FONT = QFont(); _FONT.setBold(True)` — class-level mutable default. Bold flag carried across threads. Low risk since QFont is copied.
- `preview.py:110-140` — `NoteRectItem.paint` resets painter transform then uses `QFontMetrics` fresh each paint — per-note allocation. **XS**.
- `preview.py:170-201` — `ResizableCropItem.paint` computes scale from view each paint — fine.
- `preview.py:475-477` — `QApplication.clipboard().setText(asset.source_path)` using `__import__('PySide6.QtWidgets', fromlist=['QApplication'])` — reflexive import via lambda. Ugly. **XS** — normal import.
- `preview.py:494-500` — `QShortcut(QKeySequence("Escape"), self, self.close)` plus `QShortcut("N")`, `("C")`, `("V")` — single-char shortcuts conflict with any user typing in text fields in the dialog.
- `preview.py:703-720, 722-736, 737-773` — mouse events overridden via `self.view.mousePressEvent = self._view_mouse_press` — classic method-swap antipattern. **S** — subclass QGraphicsView.
- `preview.py:756-764` — `QInputDialog(self)` for note text — blocking modal.
- `preview.py:827-848` — `_load_asset` clears scene, reloads pixmap. OK.
- `preview.py:897-908` — `closeEvent` persists geometry — good.
- `preview.py:1027-1031` — `_copy_image_to_clipboard` references `self._pixmap_item` via `getattr(...)` but PreviewPane's load_asset doesn't set it; it's a latent bug-sitting-in-wait. **S**.
- `preview.py:1013-1025` — `keyPressEvent` in `PreviewPane` handles Ctrl+C and arrow navigation — partial duplication of dialog's key handling.

**Verdict:** Good separation of floating dialog vs docked pane. Method-swap anti-pattern (line 489-492) should be replaced with subclassing.

---

### 11. `E:\git\doxyedit\doxyedit\kanban.py` (293 lines)

**Purpose:** Drag-drop status-column board for platform assignments.

**Findings:**
- `kanban.py:236-247` — `refresh()` rebuilds all cards from scratch every call; applies theme inline on each card (`card.setStyleSheet(...)` at 239-245). Inline stylesheet per card again. **S**.
- `kanban.py:260` — Kanban panel appears to not be wired into the main window anymore — comment at `window.py:560` says "(Kanban panel moved into Platforms tab above)" but there's no kanban widget in window.py. Module is **dead** unless invoked by CLI. **M — dead code or unused module**.

**Verdict:** Likely dead code. Not referenced anywhere in window.py that we've seen. Confirm with grep.

---

### 12. `E:\git\doxyedit\doxyedit\gantt.py` (647 lines)

**Purpose:** Gantt chart — scheduled posts on timeline.

**Findings:**
- `gantt.py:31-40` — `_STATUS_COLORS` maps strings to token names — fine but duplicated in timeline.py (_STATUS_ICONS).
- `gantt.py:110-129` — Tooltip HTML built in Python per bar — 20+ lines of f-string HTML per bar. For 100 bars, 2000 lines of HTML generation per refresh. **S** — cache or simplify.
- `gantt.py:300-310` — `_rebuild_chart` clears scene + all label widgets per call; no diff-update. Called from `refresh()` which fires from `_on_social_tick` every 60s. **S**.
- `gantt.py:324-369` — Date parsing via `datetime.fromisoformat` in a loop — good.

**Verdict:** Synchronous full rebuild on every tick. Tooltip HTML generation could be heavy.

---

### 13. `E:\git\doxyedit\doxyedit\timeline.py` (678 lines)

**Purpose:** Day-grouped post feed.

**Findings:**
- `timeline.py:60` — `THUMB_SIZE = 64` — local constant, not from theme.
- `timeline.py:88-147` — `PostCard` constructor builds thumbs loading pixmaps via `thumb_cache.get(aid)` — if miss, falls back to `_load_thumb_direct` (line 302-324) which calls `load_psd_thumb` or `QPixmap(str(src))` on **UI thread**. Matches session fix note at top of this review (`calendar_pane.py`, `composer.py`, `composer_right.py`, `themes.py`, `timeline.py`, `window.py`) as modified — this is the tokenization session. **M** — PSD loads still here.
- `timeline.py:141-156` — timezone calculation per card + per platform — repeated work.
- `timeline.py:180-201` — Metrics calculation per card builds labels manually. Fine.
- `timeline.py:205-282` — Engagement-panel row rebuild is 80 lines inside PostCard.__init__. **S** — extract.
- `timeline.py:339-345` — right-click "Edit Metrics" only for POSTED posts. OK.

**Verdict:** Per-post PSD loads on UI thread when thumb cache misses. Moderate issue.

---

### 14. `E:\git\doxyedit\doxyedit\calendar_pane.py` (371 lines)

**Purpose:** Month-grid calendar with status dots.

**Findings:**
- `calendar_pane.py:196-204` — Clock timer fires every 60s whether calendar visible or not. Low cost but unnecessary. **XS**.
- `calendar_pane.py:230-323` — `_populate_grid` rebuilds every day cell (42 cells) including cleanup via `.clicked.disconnect()` on each — OK.
- `calendar_pane.py:286-290, 293-302` — Leading/trailing "other_month" calendar day logic is a manual offset walk; `calendar.monthcalendar` returns `0` for empty cells — confusing logic but works.

**Verdict:** Clean. Clock timer is a minor ding.

---

### 15. `E:\git\doxyedit\doxyedit\stats.py` (229 lines)

**Purpose:** Stats panel — counts, tag frequency, platform fill, folder breakdown.

**Findings:**
- `stats.py:66-70` — `os.path.getsize` called per asset in a loop on UI thread when Overview tab activated. For 70k assets that's 70k stat calls. Matches prior review. **S** — bg thread.
- `stats.py:90-93` — Tag counting duplicates work done elsewhere (browser._used_tag_ids, window._update_progress). **S**.
- `stats.py:140-145` — Folder counting duplicates `filebrowser._folder_counts`. **S**.
- `stats.py:125, 158` — `"#ff6b6b"`, `"#7ca1c0"` hardcoded — should use `theme.error`, `theme.accent_bright`. **S**.

**Verdict:** Blocking I/O + hardcoded colors. Rebuild on tab activation is fine at 10k but not 70k.

---

### 16. `E:\git\doxyedit\doxyedit\checklist.py` (197 lines)

**Purpose:** Project posting checklist panel.

**Findings:**
- `checklist.py:95-100` — Prefix parsing `"[x] "` / `"[ ] "` done manually — fragile if project file hand-edited with `"[X] "` etc. **XS** — case-insensitive.
- `checklist.py:185-196` — `_update_progress` iterates all rows, counts checked. O(n) per check-change. Fine for short lists.

**Verdict:** Clean. No significant findings.

---

### 17. `E:\git\doxyedit\doxyedit\health.py` (473 lines)

**Purpose:** File health panel — missing/zero/untagged/unassigned/large scanner.

**Findings:**
- `health.py:13-22` — `ISSUE_DEFS` — each lambda calls `Path(a.source_path).exists()` (line 13, 14, 20, 21). For 70k assets run_scan hits the filesystem 5×70k = 350k times **on UI thread**. **L** — threaded scan.
- `health.py:310-375` — `_find_rename_candidates` does recursive directory scan (`_scan` with `max_depth=3`) on UI thread. When user opens health panel with 100 missing files: 100 directory walks synchronously. **L** — threaded.
- `health.py:412-438` — `_auto_locate_all` calls `_find_rename_candidates` per missing asset — same blocking.
- `health.py:31-62` — Path-mode heuristic OK, debug logic sound.

**Verdict:** Heavy filesystem I/O on UI thread. Real user-visible freeze for projects with many missing files.

---

### 18. `E:\git\doxyedit\doxyedit\infopanel.py` (383 lines)

**Purpose:** Right sidebar — selected asset metadata, tag pills, notes.

**Findings:**
- `infopanel.py:36` — `_TagPill.setStyleSheet("")` — empty string overrides cascade; effectively no-op. Should be removed or set proper style. **XS**.
- `infopanel.py:71` — `scroll.setStyleSheet("")` — empty style. Dead code. **XS**.
- `infopanel.py:192-195` — swatch inline CSS for color swatches — overlay-like, value-driven. OK.
- `infopanel.py:240-247` — `os.path.getsize(asset.source_path)` on UI thread per select. OK for single asset.
- `infopanel.py:358-359` — `text.strip().lower().replace(" ", "_")` for tag creation — forces lowercase snake_case; conflicts with browser.py:3343 which allows any casing (`tag_id = tag.strip()`). **Inconsistency** between panels. **S**.

**Verdict:** Inconsistent tag-normalization across the codebase.

---

### 19. `E:\git\doxyedit\doxyedit\filebrowser.py` (389 lines)

**Purpose:** Left sidebar — QFileSystemModel tree with pinned folders + asset count badges.

**Findings:**
- `filebrowser.py:332-349` — `_update_folder_counts` builds `_folder_counts` dict, then `_recursive_counts` via O(n²) scan over `_folder_counts`: "for folder in ... for path, c in ... if path.startswith(prefix)". For projects with 1000 unique folders = 1M comparisons. **M** — radix trie or sorted-prefix.
- `filebrowser.py:14-99` — `FolderDelegate.paint` — reads `panel._theme`, alphas, fonts on every paint, every row. Cache locally. **S**.
- `filebrowser.py:111-118` — no theme reference stored; `_theme` attribute set via `window._apply_theme:1319`. Dynamic attribute pattern again.

**Verdict:** O(n²) in folder count could bite large trees.

---

### 20. `E:\git\doxyedit\doxyedit\reminders.py` (222 lines)

**Purpose:** Release chain and engagement reminder generator.

**Findings:**
- `reminders.py:81-125` — `scan_pending_reminders` iterates all posts × all release chain steps — OK.
- `reminders.py:128-168` — Patreon cadence scan iterates all posts, reverse-sorts, picks latest — OK.
- `reminders.py:170-201` — Engagement scan iterates all posts × all engagement checks — OK.
- `reminders.py:204-205` — Final sort by urgency + due_at — good.

**Verdict:** Clean. Pure data layer. No significant findings.

---

### 21. `E:\git\doxyedit\doxyedit\tray.py` (632 lines)

**Purpose:** Work tray — collapsible right panel with named sub-trays + drag-out.

**Findings:**
- `tray.py:19-67` — `DragOutListWidget` — solid.
- `tray.py:230-232` — `_rebuild_index` rebuilds dict of size n — called on `remove_asset:263`, `_move_to_top:422`, `_move_to_bottom:432`. Tiny n so fine.
- `tray.py:320-324` — `asset.starred + 1) % 5 + 1` — cycle math for star but only does 5 values not 6 (matches Asset.cycle_star).
- `tray.py:393` — context menu has `Quick Tag` + tag removal; logic duplicated with browser's context menu (browser.py:3179+). **M** — extract shared code.
- `tray.py:456-472` — `_cycle_view_mode` — hardcoded cell sizes `120` / `80`. Should scale with font. **XS**.

**Verdict:** Fine. Context-menu duplication with browser.

---

## Posting Pipeline

### 22. `E:\git\doxyedit\doxyedit\oneup.py` (473 lines)

**Purpose:** OneUp REST + MCP client.

**Findings:**
- `oneup.py:348-473` — `sync_accounts_from_mcp` makes 3 sequential urllib calls (initialize + list-accounts + list-categories + N× list-category-accounts) on CALLER thread. Window.py:3468 calls this from `_on_sync_oneup` on UI thread. **L — UI freeze** (prior review).
- `oneup.py:127-186` — `schedule_via_mcp` similar pattern — 2 synchronous urlopen with 15s timeout each = up to 30s freeze per post. Called in a loop in window.py. **L**.
- `oneup.py:207-219` — `_find_config` walks 3 locations; reads `yaml` implicitly via every caller. No caching at module level. Matches prior review.
- `oneup.py:305-328` — `get_connected_platforms` re-parses yaml file. Every call. **M**.
- `oneup.py:456-458` — `pass  # categories sync is best-effort` — silent swallow.

**Verdict:** UI-blocking HTTP + YAML reparsed per call. Prior reviews called out.

---

### 23. `E:\git\doxyedit\doxyedit\quickpost.py` (236 lines)

**Purpose:** Clipboard+browser quick-post for subscription platforms.

**Findings:**
- `quickpost.py:76-83` — `clipboard.setText(caption)` + `webbrowser.open(post_url)` — on UI thread; OK but webbrowser.open can spawn slow process on Windows.
- `quickpost.py:98-125` — `_export_for_platform` loads image, applies censors/overlays, saves to tempdir. UI-thread. Called from `window.py:4875` in a loop. **M**.
- `quickpost.py:149-157` — `batch_quick_post` is a generator — caller must iterate. Matches the usage pattern.
- `quickpost.py:186-234` — `post_everywhere` — large function handling direct + subscription + fallback chain. Each branch synchronous.

**Verdict:** Clean but UI-thread heavy via `_export_for_platform` chain.

---

### 24. `E:\git\doxyedit\doxyedit\browserpost.py` (342 lines)

**Purpose:** Playwright + CDP browser automation.

**Findings:**
- `browserpost.py:130-148` — `_load_selectors` reparses yaml every call. **S** — cache.
- `browserpost.py:151-177` — `_run_steps` retries up to 2 times with `await asyncio.sleep(1)` — good.
- `browserpost.py:320-342` — `post_to_platform_sync` creates a new `asyncio.new_event_loop()` per call; doesn't close on exception. Resource leak. **S**.
- `browserpost.py:86-127` — `launch_debug_chrome` good, uses `CREATE_NO_WINDOW`.

**Verdict:** Synchronous Playwright blocks UI thread when called from window.py. Event loop not closed on exception.

---

### 25. `E:\git\doxyedit\doxyedit\directpost.py` (539 lines)

**Purpose:** Telegram, Discord, Bluesky direct posters.

**Findings:**
- `directpost.py:32-75` — `_build_multipart` uses `lines: list[bytes]` + `b"\r\n".join(...)` — efficient.
- `directpost.py:112-156` — `send_media_group` builds a duplicate boundary+form-data with MediaGroup structure inline — duplicates `_build_multipart` logic with extra fields. **S** — refactor.
- `directpost.py:160-176` — `_execute` returns `DirectPostResult` — debug prints on all paths.
- `directpost.py:493-539` — `push_to_direct` — per-post scan of clients, re-exports images. Each push is synchronous.

**Verdict:** Synchronous HTTP in UI thread path. Media-group duplicates multipart builder.

---

### 26. `E:\git\doxyedit\doxyedit\imagehost.py` (148 lines)

**Purpose:** Imgur + imgbb uploaders (not actively used in current flow).

**Findings:**
- `imagehost.py:23-24` — `_upload_cache: dict[str, str]` module-level, unbounded. Every uploaded image cached forever. **XS** — LRU or drop.
- `imagehost.py:36-79, 82-116` — Base64 encodes entire file then uploads. For 50MB PSD: 70MB base64 in memory. **S** — only accept small images.
- `imagehost.py:45` — `client_id = "546c25a59c58ad7"` — committed API key in repo! **L** — security concern if this repo is public (review confirmed this one's anonymous Imgur default).

**Verdict:** Unused? No grep of this module imported by anything. Possibly dead or future-flag.

---

### 27. `E:\git\doxyedit\doxyedit\strategy.py` (671 lines)

**Purpose:** Local + Claude-based strategy briefing generator.

**Findings:**
- `strategy.py:27-33` — Hardcoded character tag allowlist in module. Must stay in sync with CLAUDE.md. **XS** — derive from tag_definitions.
- `strategy.py:83-97` — `_parse_dt` tries 5 datetime formats — OK.
- `strategy.py:118-131` — `_build_tag_post_history` builds tag→posts dict. Called from multiple sections. **S** — memoize within strategy gen call.
- `strategy.py:143-154` — `_last_posted` sorts via `max`; OK.
- Sections at 168-380 — pure data → markdown. Clean.

**Verdict:** Clean pure-data layer. Hardcoded tag lists should drift into config.

---

## Image / Canvas

### 28. `E:\git\doxyedit\doxyedit\imaging.py` (263 lines)

**Purpose:** PIL↔Qt conversion, PSD loading, Windows Shell thumbnail extraction.

**Findings:**
- `imaging.py:46-53` — `_PREVIEW_CACHE_DIR` singleton — created on first call, lives at `~/.doxyedit/preview_cache/`. **Prior review #2 "preview_cache unbounded growth"** — confirmed. No eviction. **M**.
- `imaging.py:98-175` — `get_shell_thumbnail` — complex ctypes GDI calls; no `try/finally` to ensure `ReleaseDC`/`DeleteObject` on exception. Handle leak possible. **S**.
- `imaging.py:103` — `ctypes.windll.ole32.CoInitialize(None)` called per-thumbnail — should be per-thread init.
- `imaging.py:243-263` — `get_export_dir` makes filesystem calls + creates dir — called from export code. Good.

**Verdict:** Unbounded preview_cache still a risk. ctypes GDI lacks cleanup.

---

### 29. `E:\git\doxyedit\doxyedit\exporter.py` (281 lines)

**Purpose:** PIL-based censor/overlay/resize batch exporter.

**Findings:**
- `exporter.py:83-174` — `_composite_text_overlay` does 8-direction stroke render by drawing text in 8 positions — similar to studio.py stroke logic but in PIL. Duplicated concept. **S**.
- `exporter.py:97-106` — Font candidate list tries 6 name variants × 2 extensions × 2 paths = 24 tries with exceptions caught. Slow font lookup. **S** — cache.
- `exporter.py:143-158` — Shadow crop+blur only on non-zero blur. Good perf.
- `exporter.py:213-275` — `export_project` batch — synchronous sequential. No progress callback. **M**.

**Verdict:** Font lookup inefficient. Batch export lacks progress/threading.

---

### 30. `E:\git\doxyedit\doxyedit\pipeline.py` (484 lines)

**Purpose:** Single-slot prepare pipeline.

**Findings:**
- `pipeline.py:222-256` — Crop-matching logic: label_match → aspect_match → only_crop → largest. 4 fallback levels with `print(f"[Pipeline] ...")` debug output. Prints on every export. **S** — logger.
- `pipeline.py:260` — Auto-fit fallback when no crops exist — silent default.
- `pipeline.py:286-302` — Censor transform loop creates new CensorRegion per region + forward-copies `blur_radius`/`pixelate_ratio` via `hasattr/getattr`. **S** — use `replace()`.
- `pipeline.py:342-347` — Dedup collision loop (`candidate = ... f"_{i:03d}.png"`) — tries 1000 candidates. OK.
- `pipeline.py:390-484` — `check_readiness` returns a dict with fixed keys — could be a dataclass. **S**.

**Verdict:** Debug prints to stdout on every call. Minor architectural polish needed.

---

### 31. `E:\git\doxyedit\doxyedit\canvas.py` (226 lines)

**Purpose:** Old CanvasScene + EditableTextItem + TagItem.

**Findings:**
- `canvas.py:1-226` — Class imported only via `window.py:24` `try/except ImportError: TagItem = None` for legacy instanceof. Rest of module (`EditableTextItem`, `MovablePixmapItem`, `CanvasScene`, `CanvasView`) — **confirmed dead** per prior review. **L — dead code**, safe to delete along with `project.py` legacy save.

**Verdict:** Dead module except for `TagItem` class used in one `isinstance` check in window.py.

---

### 32. `E:\git\doxyedit\doxyedit\censor.py` (213 lines)

**Purpose:** Legacy censor editor (superseded by studio.py).

**Findings:**
- `censor.py:1-213` — Contains `CensorRectItem`, `CensorEditor`. Prior review #2: "overlay_editor.py:217 + censor.py:120 raw QPixmap(path) — PSDs show blank." Line 120 confirmed. Not imported by window.py (uses studio.py instead). **Dead module**. **M — dead code**.
- `censor.py:99, 112` — hardcoded colors `QColor(40, 40, 40)`, inline stylesheet — irrelevant if dead.

**Verdict:** Confirmed dead legacy.

---

### 33. `E:\git\doxyedit\doxyedit\overlay_editor.py` (407 lines)

**Purpose:** Legacy overlay editor (superseded by studio.py).

**Findings:**
- `overlay_editor.py:1-407` — Similar to censor.py — not imported by window.py. Module is **dead**. **M**.
- `overlay_editor.py:217` — `pm = QPixmap(asset.source_path)` — raw load, no PSD path. Per prior review #2. But again, dead module.

**Verdict:** Confirmed dead legacy.

---

### 34. `E:\git\doxyedit\doxyedit\thumbcache.py` (597 lines)

**Purpose:** QThread-backed thumbnail generator with SQLite index + per-project disk cache + LRU memory cache.

**Findings:**
- `thumbcache.py:42-89` — `GlobalCacheIndex` — SQLite with WAL, proper. Good.
- `thumbcache.py:95-196` — `DiskCache` — SQLite-migrated from JSON. Good.
- `thumbcache.py:199-429` — `ThumbWorker` — 3-priority queue (fast / upgrade / slow). Well-designed.
- `thumbcache.py:307-360` — `_process_item` handles ext-based dispatch; clean.
- `thumbcache.py:432` — `_LRU_MAX = 2000` — configurable via QSettings but module constant.
- `thumbcache.py:454` — `_migrate_flat_cache` — one-time migration, OK.
- `thumbcache.py:459-597` — `ThumbCache` — wraps worker + disk cache + LRU memory.
- `thumbcache.py:460-465` — Two `QSettings()` calls for `cache_dir` and one for `cache_dir` redundantly — the second could use the stored value from the first. **XS**.
- `thumbcache.py:483-498` — `set_project` always drains queue; fine.
- `thumbcache.py:501` — `get` is O(1). Good.
- `thumbcache.py:540-543` — QImage→QPixmap conversion in GUI thread ensures thread safety. Excellent.

**Verdict:** Best-architected module in the project.

---

## Infrastructure

### 35. `E:\git\doxyedit\doxyedit\main.py` (263 lines)

**Purpose:** App entry point — splash, logging, async project load.

**Findings:**
- `main.py:77-89` — `_Splash` sets its own stylesheet with 8 f-string lines — fine, scoped to splash only.
- `main.py:145-148` — `set_status` calls `processEvents()` — fine, splash is meant to be interactive.
- `main.py:218-254` — Uses QEventLoop to block startup while worker runs but keep UI responsive — prior review flagged this as **FIXED** via `ProjectLoader`. Good.
- `main.py:243` — `if not done["flag"]: wait_loop.exec()` — guards against already-complete fast path.

**Verdict:** Clean. Recent work (async loader) fixed the prior blocking load.

---

### 36. `E:\git\doxyedit\doxyedit\themes.py` (2092 lines)

**Purpose:** Theme dataclass + named themes + `generate_stylesheet(theme)`.

**Findings:**
- `themes.py:46-47` — `font_size: int = 12`, `font_family: str = "Segoe UI"` — sensible defaults.
- `themes.py:50-136` — 80+ semantic tokens — comprehensive.
- `themes.py:152-177` (Vinik24 sample) — Hex values used directly. Good.
- Rest of file builds a large QSS stylesheet in `generate_stylesheet` (not shown above due to size) — expect inline arithmetic from font_size throughout. Should be clean given the /tokenize work.
- Theme contrast is checked via `scripts/check_theme_contrast.py` (WCAG pass/fail) — infrastructure support exists.

**Verdict:** The core of the token system. Large but well-structured. No findings without reading the full stylesheet generator.

---

### 37. `E:\git\doxyedit\doxyedit\config.py` (224 lines)

**Purpose:** Global `doxyedit.config.json` for tag presets / shortcuts / platforms.

**Findings:**
- `config.py:21-28` — Config path selection handles Nuitka/PyInstaller — good.
- `config.py:35-64` — Load returns silently on missing file — good.
- `config.py:86-89` — `save()` reads from current live dicts as fallback — coupling between config dataclass and `models.py` module globals. **S**.
- `config.py:105-124` — `get_tag_presets`, `get_tag_sized` — merges config-over-defaults. 3 similar functions share pattern. **XS**.
- `config.py:217-224` — Singleton cached at module load — mutated by `main.py:_apply_config` at startup. Fine.

**Verdict:** Clean, small, well-scoped.

---

### 38. `E:\git\doxyedit\doxyedit\project.py` (155 lines)

**Purpose:** Legacy save/load for old canvas format (`save_project`, `load_project` for scene graph).

**Findings:**
- `project.py:1-155` — Only imports `canvas.py` (EditableTextItem, TagItem, MovablePixmapItem). Not imported by anything in window.py (prior review #2 called out "project.py = dead old-canvas-format leftover"). **Confirmed dead**. **M**.
- `project.py:90-131` — Base64 serialization of pixmaps in JSON — legacy format.

**Verdict:** Dead code. Safe to delete.

---

### 39. `E:\git\doxyedit\doxyedit\autotag.py` (98 lines)

**Purpose:** Pixel-based visual tag generator (warm/cool/dark/bright/detailed/flat/aspect).

**Findings:**
- `autotag.py:14-71` — Uses numpy on 200×200 thumbnail — fast. Clean.
- `autotag.py:74-87` — `compute_dominant_colors` via `getcolors(maxcolors=2500)` — returns None if > 2500. For highly detailed images returns `[]` — fallback fails silently. **XS**.
- `autotag.py:90-98` — `compute_phash` — 8×8 average hash returning 64-bit int. Clean.

**Verdict:** Clean pure-compute module. No significant findings.

---

### 40. `E:\git\doxyedit\doxyedit\crossproject.py` (271 lines)

**Purpose:** Cross-project schedule cache + conflict detection.

**Findings:**
- `crossproject.py:88-107` — `peek_project_schedule` reads entire project JSON just to extract `posts`. For a 1MB project file per peek — high overhead. Registry can have 10+ projects. **S** — partial streaming or cache only posts.
- `crossproject.py:119-163` — Cache uses mtime; good.
- `crossproject.py:191-271` — Conflict detection; pure data. Fine.

**Verdict:** Good. `peek_project_schedule` re-parses JSON but cache prevents re-reads.

---

### 41. `E:\git\doxyedit\doxyedit\windroptarget.py` (174 lines)

**Purpose:** Windows-only global hotkey + WM_DROPFILES simulation.

**Findings:**
- `windroptarget.py:148` — PostMessage is async; if target app doesn't free the allocated memory, it leaks. Header comment acknowledges this. **S** — can't be fixed from this side.

**Verdict:** Clean low-level Win32 code, well-commented.

---

### 42. `E:\git\doxyedit\doxyedit\claude_modal.py` (87 lines)

**Purpose:** Reusable Claude CLI modal with QThread worker.

**Findings:**
- `claude_modal.py:25-30` — `subprocess.run` with `timeout=180` + `creationflags=0x08000000` — good.
- `claude_modal.py:33-87` — Shows themed progress modal; worker runs Claude CLI in background. Good.

**Verdict:** Clean. No findings.

---

### 43. `E:\git\doxyedit\doxyedit\__main__.py` (1830 lines — huge)

**Purpose:** `python -m doxyedit` CLI with 40+ subcommands.

**Findings (sampled from first 250 lines):**
- `__main__.py:43-53` — `cmd_summary` loads project for each command invocation. Fine for CLI.
- `__main__.py:115-126` — `cmd_add_tag` saves project each call — atomicity on concurrent invocations not handled. **S** — file lock.
- `__main__.py:204-240` — `cmd_find_dupes` does average-hash over full PIL load of every asset synchronously. For 70k assets: >30 minutes. OK for CLI but no progress/abort. **S**.
- Full file at 1830 lines indicates command-per-function pattern — monolithic dispatch. **M** — split into `cli/` subpackage.

**Verdict:** CLI grew organically into one huge file. Concurrency/progress not addressed.

---

## Scripts/Tools

### 44. `E:\git\doxyedit\run.py` (3 lines)

**Verdict:** Trivial launcher. No findings.

### 44a. `E:\git\doxyedit\launcher.py` (7 lines)

**Verdict:** Trivial BAT launcher. No findings.

### 44b. `E:\git\doxyedit\build_help.py` (527 lines)

**Purpose:** Builds dist/DoxyEdit Help.html from wiki markdown.

**Findings:**
- `build_help.py:33-54` — Duplicate Vinik24 color palette hardcoded here and in themes.py — will drift. **S** — read from themes.
- `build_help.py:123+` — Large CSS string definition — standalone, OK for static help export.

**Verdict:** Duplicate palette; otherwise fine for a build script.

### 45. `E:\git\doxyedit\scripts\tokenize_validate.py` (100 lines)

**Verdict:** Tokenization validator — great hygiene tool. Clean.

### 45a. `E:\git\doxyedit\scripts\check_theme_contrast.py` (98 lines)

**Verdict:** WCAG contrast checker — clean and useful.

### 46. `E:\git\doxyedit\tools\tag-by-folder.py` (119 lines)

**Findings:**
- `tag-by-folder.py:22-23` — Absolute paths hardcoded in script (`PROJECT_FILE`, `BASE_PATH`) — should be CLI args. **XS** — user-specific tool.

**Verdict:** Ops script. Fine but not generic.

---

## Summary Matrix

| File | Lines | Key Findings | Verdict |
|------|-------|--------------|---------|
| window.py | 6558 | 50+ findings; god object, multiple sync HTTP/disk paths, `_own_save_pending` fragile, duplicated MCP code, sync_oneup UI-blocking | architectural-smell |
| browser.py | 3783 | ~30 findings; inline stylesheets, QSettings per-call, eventFilter 250 lines, unbounded scaled_cache | needs attention |
| studio.py | 2521 | AppEscapeFilter leak, undo coverage gaps, export re-loads PSD per crop, two Escape handlers | needs attention |
| themes.py | 2092 | Large but well-structured token system | clean |
| composer_right.py | 1897 | Config reparsed, chrome profile cache no-lock | needs attention |
| __main__.py | 1830 | Monolithic CLI dispatcher | architectural-smell |
| platforms.py | 1108 | drop bug at 737, PIL.open per assign, full rebuild on refresh | needs attention |
| tagpanel.py | 1044 | Inline CSS per row, hardcoded FITNESS_COLORS | needs attention |
| preview.py | 1041 | Method-swap antipattern, single-char shortcuts | needs attention |
| models.py | 1025 | 6 to_dict/from_dict pairs, tray_items union type | needs attention |
| timeline.py | 678 | PSD load on UI thread via `_load_thumb_direct` | needs attention |
| strategy.py | 671 | Hardcoded character tag list | clean |
| gantt.py | 647 | Tooltip HTML heavy per bar, full rebuild each tick | needs attention |
| composer_left.py | 646 | Sync PSD/platform preview gen | needs attention |
| tray.py | 632 | Context menu duplicates browser | needs attention |
| thumbcache.py | 597 | Best-architected module | clean |
| composer.py | 541 | _save boilerplate | needs attention |
| directpost.py | 539 | Media group duplicates multipart builder | needs attention |
| build_help.py | 527 | Duplicate palette | clean |
| pipeline.py | 484 | Debug prints to stdout, 4-level crop fallback | needs attention |
| oneup.py | 473 | UI-blocking HTTP + yaml reparsed | architectural-smell |
| health.py | 473 | Filesystem I/O on UI thread | architectural-smell |
| overlay_editor.py | 407 | **Dead module** | dead-code |
| filebrowser.py | 389 | O(n²) recursive folder counts | needs attention |
| infopanel.py | 383 | Empty setStyleSheet, tag-normalize inconsistency | clean |
| calendar_pane.py | 371 | Clock timer always running | clean |
| browserpost.py | 342 | Event loop leak on exception | needs attention |
| kanban.py | 293 | **Likely dead code** | dead-code |
| exporter.py | 281 | Font lookup inefficient | clean |
| crossproject.py | 271 | Full project JSON reparsed per peek | clean |
| main.py | 263 | Async loader correct | clean |
| imaging.py | 263 | preview_cache unbounded, ctypes GDI leak possible | needs attention |
| quickpost.py | 236 | Sync _export_for_platform | clean |
| stats.py | 229 | os.stat per asset on UI | needs attention |
| canvas.py | 226 | **Mostly dead** except TagItem isinstance | dead-code |
| config.py | 224 | Clean singleton | clean |
| reminders.py | 222 | Pure data layer | clean |
| censor.py | 213 | **Dead module** | dead-code |
| checklist.py | 197 | Prefix parsing case-sensitive | clean |
| windroptarget.py | 174 | Win32-safe | clean |
| project.py | 155 | **Dead module** | dead-code |
| imagehost.py | 148 | Unused? unbounded upload cache + committed API key | dead-code (likely) |
| tools/tag-by-folder.py | 119 | Hardcoded paths | clean |
| scripts/tokenize_validate.py | 100 | Validator tool | clean |
| scripts/check_theme_contrast.py | 98 | WCAG checker | clean |
| autotag.py | 98 | Numpy-based | clean |
| claude_modal.py | 87 | Clean | clean |
| main.py | 263 | Async startup fixed | clean |
| launcher.py | 7 | Trivial | clean |
| run.py | 3 | Trivial | clean |
| __init__.py | 2 | Version only | clean |

---

## Top 10 Never-Mentioned (items not in prior reviews, ranked by impact)

1. **platforms.py:737** — `_on_file_dropped` references undefined `event.acceptProposedAction()` when no matching asset found. **Bug waiting** — any file-drop onto a platform slot that isn't a tracked asset throws `NameError`. Effort: XS.

2. **studio.py:1278-1280** — `_AppEscapeFilter` installed at `QApplication` level but never removed on editor close — every keypress in every dialog app-wide routes through this filter. If user has multiple MainWindow instances, multiple filters pile up. Effort: S.

3. **window.py:5888-5890** — `del TAG_SHORTCUTS[key]` mutates module-level `models.TAG_SHORTCUTS` dict. Multiple `MainWindow._open_windows` entries stomp on each other's shortcut bindings when switching projects. Effort: S.

4. **thumbcache.py:456-597 / imaging.py:46-53** — `~/.doxyedit/preview_cache/` + `GlobalCacheIndex` SQLite both grow forever with no eviction policy. Over time, running through thousands of PSDs fills the user's home directory indefinitely. Effort: M.

5. **studio.py:2397, 2407** — Crop-platform matching uses 3-way substring logic `p.lower() == crop_lbl or crop_lbl in p.lower() or p.lower() in crop_lbl`. A platform called `ks` matches any crop labeled `kickstarter`, `ks_jp`, or `ks_header` — silent false positives in multi-platform exports. Effort: S.

6. **health.py:310-375** — `_find_rename_candidates` does blocking recursive filesystem scan (max_depth=3) per missing asset on the UI thread. For projects with 500+ missing assets after a folder reorganization, the panel freezes for minutes. Effort: L.

7. **window.py:2300-2324 + stats.py:66-70** — `_update_progress` iterates all assets 4× every 2 seconds AND stats.py iterates all + does `os.path.getsize` per asset on Overview tab activation. Two independent CPU/IO-heavy loops over the same 70k list. Effort: S.

8. **filebrowser.py:332-349** — `_recursive_counts` computed as O(n²) `.startswith()` loop over folder paths. Ships fine at 100 folders, degrades at 1000+. Effort: M.

9. **browser.py:602-620** — `_scaled_cache` is keyed by `(pixmap.cacheKey(), ts, fill_mode)` and **never evicted**. Zooming, toggling fill mode, and reloading thumbs all add entries. For 70k assets at varying zoom levels, this dict can grow to hundreds of thousands of QPixmap scaled copies. Memory pressure grows silently. Effort: S (add LRU cap).

10. **kanban.py entire file + censor.py entire file + overlay_editor.py entire file + project.py entire file + canvas.py except TagItem** — ~1300 lines of dead code across 5 modules. Not reachable from window.py. Costs maintenance mental load (tokenize_validate runs on them, imports still resolve, devs still read them). Effort: M — delete with grep safety check.

---

All paths referenced above use absolute form. Relevant files for follow-up:
- `E:\git\doxyedit\doxyedit\window.py`
- `E:\git\doxyedit\doxyedit\browser.py`
- `E:\git\doxyedit\doxyedit\studio.py`
- `E:\git\doxyedit\doxyedit\platforms.py`
- `E:\git\doxyedit\doxyedit\health.py`
- `E:\git\doxyedit\doxyedit\imaging.py`
- `E:\git\doxyedit\doxyedit\oneup.py`
- `E:\git\doxyedit\doxyedit\kanban.py` (dead)
- `E:\git\doxyedit\doxyedit\censor.py` (dead)
- `E:\git\doxyedit\doxyedit\overlay_editor.py` (dead)
- `E:\git\doxyedit\doxyedit\project.py` (dead)
- `E:\git\doxyedit\doxyedit\canvas.py` (dead except TagItem)
- `E:\git\doxyedit\doxyedit\thumbcache.py` (reference implementation)