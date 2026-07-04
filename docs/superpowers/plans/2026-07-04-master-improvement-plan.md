# DoxyEdit Master Improvement Plan - 2026-07-04

**Provenance:** produced by a 38-agent verified sweep: every wishlist, design doc, backlog,
memory note, and April plan (47 docs) was read, every extracted request was verified against
the CURRENT code (grep/read/changelog, not doc claims), and five independent health
assessments (perf, architecture, tests, UI compliance, agentic infra) ran in parallel.
Numbers: 233 requests extracted, 115 already shipped, 87 still open (28 missing, 59 partial),
40 health findings. The single biggest discovery: the docs lag the code by ~2 months -
half of what the backlogs call "open" already shipped in the v2.5.6 session.

**How to use this doc:** work batches top to bottom. P1 batches are the spine; P2 batches
slot in after their gates; P3 is filler. Each batch is sized for 1-3 focused sessions.
Check items off here as they land. Decisions section needs user answers before the
flagged items start.

---

## Standing Constraints (apply to every batch)

1. **2026-04-22 directive:** no new Studio features. Solidify, refactor, right-size.
2. **Perf reality (perf.log):** compute_filtered and apply_theme are the felt slowness,
   not JSON parse. Optimize what is measured, not what is guessed.
3. **PSD Thumbnail Rule (CLAUDE.md):** thumbnails from Windows shell cache only.
4. **Launch Test rule:** smoke-launch via CLI after every extraction/refactor commit.
5. **New-code rule (from Batch 1 onward):** any logic extracted from window.py/studio.py
   must land headless-importable with a test in the same commit.
6. **Agentic method:** tests-first on integrity seams, perf.log before/after on perf work,
   one mixin/API-step per commit on decompositions, fan-out agents for mechanical sweeps,
   adversarial verify before claiming a batch done.

---

## Batch 1 - Test Harness Foundation  [P1, 2-3 days, DO FIRST]

**Goal:** the verification infrastructure every later batch leans on. Highest
leverage-per-hour in the plan. No dependencies, zero user-facing risk.

- [x] `tests/conftest.py` with session QApplication + offscreen env; switch CI from
      unittest discover to pytest; add pytest-qt  (a7f8b78)
- [x] Project fixture factory: temp dir, tiny Pillow PNGs, populated Project with
      assets/tags/posts/crops/censors  (6fcb6b2, tests/factory.py)
- [x] Golden fixture `tests/fixtures/golden_full.doxyproj.json` covering EVERY schema
      section (all 31 save-dict keys, deterministic generator) + gen2-vs-gen3 deep
      round-trip + forward-compat unknown-keys + schema-coverage guard  (6fcb6b2)
- [x] Perf regression gate `tests/test_perf_budget.py`: 10k assets - build 0.05s,
      save_dict 0.41s, save 0.78s, load 0.29s, summary 0.005s vs generous CI budgets
      (3420c7b). Note: real load path is Project.load, there is no from_dict.
- [x] Out-of-process launch smoke: `run.py --smoke` + subprocess test; exits nonzero
      on swallowed exceptions or plugin boot failures, never touches the crash
      sentinel or running.lock  (cb211b8)
- [x] CI hardening: timeout-minutes 20, pip cache, concurrency cancel, failure log +
      coverage artifacts, requirements-ci.lock  (a7f8b78)
- [x] coverage.py in CI (non-blocking, xml + term report)  (a7f8b78)
- [x] CLI-to-GUI post round-trip test  (6fcb6b2)
- [x] BONUS from Batch 4 landed early: design_manifest.py screenshot artifact step in
      CI (continue-on-error)  (a7f8b78)

**DONE 2026-07-04.** Suite went 670 -> 682 tests. Known facts recorded by the sweep:
variant_exports/guides are save-only fields dropped by Project.load (pinned by test);
unknown keys survive load but are dropped on next save except inside asset.specs.

**Sequencing:** first, before everything. Fixture factory + golden fixture are hard
prerequisites for Batches 2, 6, 8 and the safety net for 3, 5, 10.

---

## Batch 2 - Save & Post Pipeline Data Integrity  [P1, 3-4 days]

**Goal:** close the two critical data-loss / double-post vectors and put every untested
persistence seam under test. Tests first, then the (mostly tiny) fixes.

- [ ] **CRITICAL** BackgroundSaver races the UI thread and silently drops failed autosaves
      (project_io.py:68-118, window.py:8401-8413): snapshot build_save_dict on the UI
      thread or re-mark dirty on failure; unit tests for submit/flush/stop/failure
- [ ] **CRITICAL** OneUp sync matches by caption[:40] fingerprint and can reset pushed
      posts to DRAFT = double-post vector (window.py:4520-4630): extract pure
      sync-decision function into pipeline.py/oneup.py, table-test collision / gone /
      published / failed / scheduled / no-key cases. APPROVED (D2): match by stored
      oneup_post_id, no auto-reset to DRAFT; deleted remote posts need manual re-queue.
- [ ] Direct-post double-send guard untested (directpost.py:497-508): unit-test
      push_to_direct with fake clients; fix sub_platform_status dict-vs-string shape
      mismatch (writers window.py:4584-4595 vs reader browser.py:2095)
- [ ] Composer `_save` field-parity test vs SocialPost dataclass fields; then refactor
      _save to dict-merge (kills the hand-copy regression class CLAUDE.md warns about)
- [ ] Tag rename integrity: extract rename from tagpanel.py:1041 to a pure Project
      method; test definitions/custom_tags/asset.tags/aliases/shortcuts/hidden-lists sync
- [ ] Tray save_state/restore roundtrip test + corrupt .doxy with valid .bak
      recovery-path test (project_io.py:411-455)
- [ ] Injectable fake transport for directpost + OneUp: simulate restarts, assert zero
      double-sends
- [ ] platforms/ package (bluesky/mastodon, 1,719 lines, zero tests): mirror the
      existing mocked-urlopen client test pattern

**Sequencing:** after Batch 1 (fixture factory, fake transport). Parallel-safe with
Batch 3 (different files).

---

## Batch 3 - Startup & Rebind Perf  [P1, 1.5-2 days]

**Goal:** kill the measured felt slowness: triple rebinds on launch, 67k GUI-thread stat
storms, 8.4s file-browser stalls, GUI-thread SQLite commits. Verify every item with
before/after perf.log entries.

- [ ] Collection restore N+1 full rebinds (tab_manager.py:33-74, window.py:1344-1369):
      add tabs with switch=False, keep single _switch_to_slot(0), drop redundant second
      _apply_theme
- [ ] Stop clearing browser._stat_cache in _rebind_project (window.py:7829) - it is
      path-keyed and project-independent; optional off-thread stat warmup on first launch
- [ ] FolderBrowser._auto_expand GUI stall up to 8.4s (filebrowser.py:325-355): memoize
      by (project sig, target), defer via QTimer.singleShot, consider directoryLoaded
      incremental expand + DontWatchForChanges
- [ ] ThumbCache.set_project sync SQLite commits on GUI thread (thumbcache.py:513-531):
      pending-writes counter to skip no-op save_index; flush via worker-queue sentinel;
      lazy DiskCache construction on folder switch
- [ ] apply_theme 0.4-1.2s: mostly fixed by the N+1 fix; optional stylesheet cache per
      (theme_id, accent, font_size); defer accent-out-of-global-sheet refactor unless
      tab switching still feels slow after
- [ ] _refresh_grid tail (browser.py:2610-2636): cache starred/tagged counts +
      dup-group/variant/used-tag rebuild by (id(project), project.version) sig
- [ ] Remaining GUI-thread I/O: health panel scan, PSD/image loads in timeline/composer
      previews/platforms auto-fill
- [ ] GlobalCacheIndex eviction (last of the 4 unbounded caches)

**Sequencing:** land Batch 1 perf gate first so wins are measured. RISK: rebind ordering
is subtle - manual regression test tab switching + collection restore. Batch 8's H6 pass
runs AFTER this ships.

---

## Batch 4 - Agentic Infra: CLI Registry, Doc Truth, Verify Loop  [P1, 1-1.5 days]

**Goal:** make the repo self-verifying for future agent sessions. Cheap wins; do before
the big refactors so doctor + drift checks guard those sessions.

- [ ] Refactor __main__.py elif dispatch into COMMANDS registry dict; generate
      docstring/usage from it (8+ commands are currently undocumented)
- [ ] `tests/test_cli_docs_drift.py`: COMMANDS keys vs wiki/CLI Reference.md, both ways
- [ ] `doctor` CLI command: both validators + Project.load + health ISSUE_DEFS as one
      verify-the-world entry point
- [ ] `scripts/check_doc_drift.py`: doc path references exist, cited commit hashes
      resolve; add as CI step
- [ ] Plugin lint subcommand: `python -m doxyedit plugins lint <file.py>` (~40 lines,
      loader logic exists at plugins.py:147-198)
- [ ] Screenshot CI artifact phase 1: run tools/design_manifest.py offscreen, upload
      manifest PNG per PR
- [ ] Stale doc refresh: delete UI_SPEC "Current Violations" (shipped in 617b731), fix
      "7 themes" to 21, refresh TOKENIZATION_STATUS exception table from validator
      ACCEPTABLE list, reconcile the phantom "icon decisions" CLAUDE.md citation

---

## Batch 5 - window.py Decomposition + AssetBrowser Public API  [P1, 2 sessions]

**Goal:** break the 8,439-line / ~336-method MainWindow god object's worst coupling.
window.py reaches into browser private attrs 92 times - the top cross-file error source.

- [ ] AssetBrowser public API: reset_for_project(), thumb_cache property,
      set_eye_hidden_tags(), select_ids(), set_post_status(); the _rebind_project
      browser block (window.py:7824-7845) becomes one call
- [ ] Graded invalidation: refresh_assets(ids) / refresh_post_status(posts) /
      refresh_filters() alongside full refresh(); convert the 25 blanket refresh() sites
      where scope is knowable
- [ ] Extract the 5 QThread worker classes (window.py:90-324) to doxyedit/workers.py;
      OneUpControllerMixin for the push/sync/fetch block
- [ ] Extract transport/untransport to doxyedit/transport.py - removes the inverted
      GUI-imports-__main__.py dependency (window.py:5684, 5734)
- [ ] Triage the 91 function-local imports: hoist non-startup-motivated ones, tag real
      lazy imports with `# lazy: startup cost`
- [ ] Predeclare conditionally-created attrs as None in __init__ (82 hasattr guards);
      add CLAUDE.md rule: never hasattr(self, ...)
- [ ] TAG_SHORTCUTS remaining module-global writes to per-window state
- [ ] Cache yaml config reads (remaining bit of the OneUp HTTP perf item)

**Sequencing:** after Batch 1 (smoke net) and Batch 3 (both touch _rebind_project - do
perf first to avoid edit collisions). One API step per commit, smoke launch each.

---

## Batch 6 - studio.py Decomposition & Correctness  [P1, 2-3 sessions]

**Goal:** split the 15,133-line monolith (StudioEditor alone is 10,276 lines / ~289
methods) - the single biggest drag on agentic work. Solidify, not features.

- [ ] Split StudioEditor along its existing section markers into studio_layers.py,
      studio_actions.py, studio_tools.py, studio_edit_ops.py, studio_export.py (proven
      H4 mixin pattern); helper classes to studio_widgets.py; ONE mixin per commit,
      smoke-launch after each
- [ ] keyPressEvent 928-line handler (studio.py:4942) to dispatch table
- [ ] studio_items.py: HandleInteractionMixin + build_common_item_menu across the 5
      overlay item classes that each reimplement the same interaction machinery
      (RISKIEST change in this plan - one class per commit, manual Studio testing)
- [ ] Scene-to-model writeback roundtrip tests: StudioPanel offscreen, add/modify
      crop + censor + overlay, save, reload, assert geometry (needs Batch 1 fixture)
- [ ] Crop-label substring false-positive fix (last open third of the review.md
      correctness cluster)
- [ ] Full undo coverage for all Studio mutations - deliberately LAST, so command wiring
      lands on the decomposed structure, not the monolith

**Sequencing:** after Batch 1. Parallel-safe with Batch 5 (disjoint files).

---

## Batch 7 - UI Token Compliance Closeout  [P2, 1 day]

**Goal:** close the validator blind spot so ALL CLEAN actually means all clean.

- [ ] tokenize_validate.py: add hex/rgba-inside-setStyleSheet patterns (whitelist
      data-driven interpolations); triage ~8 new ACCEPTABLE entries - FIRST, so the
      rest of the batch is machine-checked
- [ ] Fix the 3 real semantic-color violations: FITNESS_COLORS (tagpanel.py:19-23) to
      theme success/warning/error (APPROVED D10), stats.py:174 platform bars to theme
      error/accent, studio.py:3863 #333 border to theme.border
- [ ] Bare-px/rgba sweep in dynamic inline styles: browser.py:1183/1801,
      infopanel.py:44/220, tagpanel.py:310, window.py:4778 (use themes.py:1091 helper),
      main.py splash geometry
- [ ] Residual inline styles: composer_left status labels, stats progress chunk,
      filebrowser, project_io.py:222 save-flash
- [ ] Remove dead Kanban CSS selectors (themes.py:1580-1599)
- [ ] Extract the max(14, _f + 2) checkbox-size formula to a shared helper (10 files)
- [ ] Studio toolbar icons: finish the theme-change re-render half

---

## Batch 8 - User-Verified Bugs & Validation  [P2, ~1 day]

**Goal:** resolve the bugs blocked on real-world data; validate perf work via telemetry.

- [x] ~~Social tab crash~~ PARKED (D1: not seen lately). Reopen with
      ~/.doxyedit/last_run.log on next sighting; do not speculate without data
- [ ] Gantt empty bars: user runs the shipped diagnostic (gantt.py:360-372) on a real
      scheduled project, then fix the identified bucket
- [ ] P0 user-verification queue: walk the 6 shipped-but-unconfirmed fixes, check off
      (lightweight, can happen in normal conversation)
- [x] ~~H6 interactive 70k pass~~ PARKED (D9: no keyboard session). Perf wins get
      verified via before/after perf.log entries + the Batch 1 perf gate instead
- [ ] Asset groups end-to-end tests: variant_set / duplicate_group / dissolve currently
      have zero test hits

**Hard dependency:** after Batch 1 (fixtures); no longer gated on Batch 3 now that H6
is parked.

---

## Batch 9 - High-Value Completions (non-Studio)  [P2, 3-4 days, independently shippable]

**Goal:** finish partially-shipped features with real workflow value. Good filler
between P1 sessions; each lands with tests per the new-code rule.

- [ ] Censor mode radios in composer: finish remaining wiring (posting-safety adjacent,
      cheapest high-value item - do first)
- [ ] Duplicate finder / file unification: close remaining gaps
- [ ] Composer prep strip: per-issue Fix buttons
- [ ] Platforms tab campaign & launch planning dashboard: finish remaining views
- [ ] Cross-project schedule conflict detection: surface in scheduling UI
- [ ] Tag hierarchy: wire parent inheritance into filtering (models + walkers shipped)
- [ ] Notes polish only - BOTH surfaces stay per D5 (tab + collapsible panel);
      no tab removal
- [ ] Browser toolbar right-sizing: + Folder/+ Files become ONE + split-button
      (APPROVED D6: click = add files, dropdown = folder/files), checkboxes to
      overflow, muted unselected thumbnails, Eagle grid polish remainder

---

## Batch 10 - SQLite Phase 2 Asset Store  [P2, 1-2 weeks, GATED]

**Goal:** execute the pre-approved Scale Plan Phase 2 - assets to SQLite with migration
path, JSON stays as interchange.

- [ ] SQLite asset store with migration path (Scale Plan Phase 2)
- [ ] Phase 3 remainder: windowed streaming model for 50k+ (tag index already shipped)

**HARD GATE (DECISION D7):** only after Batch 3 ships AND a go/no-go confirms remaining
felt slowness justifies it. Mandatory safety nets: golden fixture round-trip (Batch 1)
and .bak recovery test (Batch 2). Owns whole sessions; never start mid-session.

---

## Batch 11 - P3 Opportunistic Backlog  [P3, hours each, filler only]

- [ ] imagehost.py: DELETE module + its 2 test files (APPROVED D3; git keeps history)
- [ ] canvas_skia.py: KEEP, mark experimental (D4) - header comment + docs note that
      it is an unsupported experimental backend; debug shortcut stays
- [ ] Split __main__.py into subpackage + file locking (registry refactor in Batch 4
      already captured most of the value)
- [ ] File browser: finish drag-folder-to-grid drop handler
- [ ] Flip Horizontal/Vertical for crops (overlays done)
- [ ] Text overlay right-click Style submenu grouping
- [ ] Platforms drag-drop slot-row visual feedback polish
- [ ] Dialog-singleton helper (replace copy-pasted guards)
- [ ] Unify the four social-post composition paths (WAIT for Batch 2 tests - same seams)
- [ ] SocialPost/Project generic to_dict/from_dict migration
- [ ] itch.io release prep (stays P3 per D8: someday, not near-term)

---

## Sequencing Map

```
Batch 1 (harness) ──┬─> Batch 2 (integrity) ──┐
                    ├─> Batch 3 (perf) ───────┤
                    ├─> Batch 8 (bugs/tests)  │
Batch 4 (agentic) ──┘        │                │
  (anytime, early)           └─> Batch 5 (window.py) ─┐
                                 Batch 6 (studio.py) ─┼─> Batch 9 (completions)
                                  (5 ∥ 6 parallel-ok) │
Batch 7 (tokens): anytime                             └─> Batch 10 (SQLite, gated D7)
```

---

## Decisions - RESOLVED 2026-07-04

All 10 answered by the user; batches above already reflect them.

| # | Decision | Answer |
|---|---|---|
| D1 | Social tab crash | Not seen lately - PARKED; reopen with last_run.log on next sighting |
| D2 | OneUp sync redesign | APPROVED: oneup_post_id matching, no auto-reset to DRAFT |
| D3 | imagehost.py | DELETE (module + 2 test files; git keeps history) |
| D4 | canvas_skia.py | KEEP, mark experimental (header + docs note) |
| D5 | Notes tab | KEEP BOTH surfaces (tab + collapsible panel) |
| D6 | Browser top bar | Single + split-button (click = files, dropdown = folder/files) |
| D7 | SQLite Phase 2 | Checkpoint after Batch 3; go only if still slow in normal use |
| D8 | itch.io release | Someday, not near-term - release prep stays P3 |
| D9 | H6 70k keyboard session | NO - verify perf via perf.log + Batch 1 perf gate instead |
| D10 | FITNESS_COLORS | APPROVED theme-driven success/warning/error tones |

---

## Drop List (30 items, verified reasons)

Explicitly NOT doing. Reopen only on explicit re-request.

| Dropped | Why |
|---|---|
| Studio Tier-3: layer masks | Week+ Studio feature vs 04-22 directive, low value |
| Studio Tier-3 remainder: pen tool, shape library, multi-canvas | Same directive; valuable half (blend modes, filters, arrows) already shipped |
| Non-destructive filters completion | 80% shipped covers real use; rest is piling |
| Brush tool v1 | Week+ Studio paint system vs directive |
| GL canvas Tiers 3-4 | Tier 2 shipped, idle behind debug shortcut; canvas is not a measured hotspot |
| Shift+S Skia preview editable | Days of wiring into a backend whose ship-or-cut is open (D4) |
| E2 mipmap pyramid cache | No measured pain behind it |
| Tag compositor in perf events | Telemetry nicety for a debug-only backend |
| Skia bundling de-risk spike | Already shipped (build.bat + skia_build_smoke.py); entry stale |
| GL Tier 1 gate remainders | Shipped in substance; deltas cosmetic |
| Dual-palette VINIK_COLORS | All 21 themes already pass WCAG contrast in CI |
| Rebindable shortcuts panel | Days for low value, no recorded demand |
| Command Palette | Week+ feature vs solidify directive |
| Eagle Gallery 3-panel tab | Shipped filebrowser sidebar + grid covers the workflow |
| Eagle Phases 1/3/4 (import/push/export) | Speculative, zero code, no evidence of Eagle use |
| Search/sort by dominant color | Days for low value; palette pipeline stays if revived |
| Shader tray fixes (.rpy) | Target code is a Ren'Py overlay NOT in this repo - log in the right project |
| Manual TEST_CHECKLIST.md (91 boxes) | Superseded by Batch 1 harness + slimmed H6; references dead UI |
| Window flash remaining paths | Fix shipped (8d80508), no repro since; reopen on sighting |
| Thumbnail ratio modes remainder | Fill/crop toggle shipped end to end |
| Filesystem browser remainder | Shipped and wired; one real gap (drop handler) is in Batch 11 |
| Rotate handle vs slider question | Resolved in practice: both shipped, per item type; close in spec |
| Platform-scoped overlay paste edge case | Rare, benign; document instead of coding |
| Focus-mode polish / PR 7 / Text Controls remainder | Studio cosmetics vs directive; QLabel-separator fix rides along with Batch 6 free |
| formats.py consolidation architecture note | A CLAUDE.md paragraph during Batch 5/6 captures it; standalone doc = new drift |
| PERFORMANCE.md optimization bundles | Superseded by perf.log findings; live items are in Batch 3, rest shipped |
| Asset review brief remainders | Stale pre-pivot brief; the parts that mattered shipped |
| json_parse 5.7s spike | One-off cold-I/O on a background thread; no action |
| _AppEscapeFilter leak + misc cleanups | Already fixed (QShortcut rewrite); stragglers fold in opportunistically |
| Asset grid readiness dots remainder | Shipped end to end; no concrete gap identified |

---

## Appendix A - Verified Open Inventory (87 items)

Every still-open request with code-verified status. Effort/value are the verifier's estimates.

| # | Item | Src | Cat | Status | Effort | Value | Evidence |
|---|---|---|---|---|---|---|---|
| 1 | Asset groups end-to-end verification checklist | 2026-04-15-asset-groups.md | docs | missing | hours | low | docs/superpowers/plans/2026-04-15-asset-groups.md:568-588 - all Task 9 checkboxes still '- [ ]' (unchecked); grep for variant_set/duplicate_group/diss... |
| 2 | Asset grid readiness dots on thumbnails | 2026-04-14-unified-pipeline.md | feature | partial | hours | low | Exists: ReadinessRole (doxyedit/browser.py:361), _readiness_cache (browser.py:370,399-400), update_readiness/invalidate_readiness (browser.py:418-436)... |
| 3 | Censor mode radio buttons in composer (auto/uncensored/custom) | 2026-04-14-unified-pipeline.md | feature | partial | hours | high | Exists: radios at doxyedit/composer_right.py:291-316 (collapsible 'Censor Mode' section, Auto/Uncensored/Custom), included in get_post_data (composer_... |
| 4 | Composer prep strip: per-platform readiness rows with Fix buttons | 2026-04-14-unified-pipeline.md | feature | partial | hours | medium | E:/git/doxyedit/doxyedit/composer_left.py:157-249 (rebuild_prep_strip: dot + platform name + first issue or 'Ready'), doxyedit/composer.py:208,301-303... |
| 5 | Cross-project awareness (schedule conflict detection across projects) | 2026-04-14-suite-expansion-roadmap.md | feature | partial | day | medium | Exists: doxyedit/crossproject.py full module - registry at ~/.doxyedit/project_registry.json :15-16, register/sync :47-84, peek_project_schedule/black... |
| 6 | File browser: drag folder from tree to import | 2026-04-09-file-browser-sidebar.md | feature | partial | hours | low | Drag half exists: E:/git/doxyedit/doxyedit/filebrowser.py:199 (startDrag override) and 399-415 (_start_drag sets file URL + application/x-doxyedit-fol... |
| 7 | Full CLI-to-GUI round-trip integration test for posts | 2026-04-13-social-media-pipeline.md | docs | partial | hours | low | Exists piecewise: tests/test_cli_post_create.py:95-102 (CLI create persists as DRAFT via Project reload), tests/test_cli_schedule.py, test_cli_post_up... |
| 8 | Platforms tab evolution: campaign and launch planning dashboard | 2026-04-14-suite-expansion-roadmap.md | feature | partial | day | medium | Exists: Campaign + CampaignMilestone models (doxyedit/models.py:394-445), campaign_id on PlatformAssignment :456 and SocialPost :592, NewCampaignDialo... |
| 9 | Platforms tab rebuild: drag-drop onto card slot rows with feedback | 2026-04-15-platforms-rebuild.md | bug | partial | hours | low | Exists: every slot row is a _DroppableSlotRow (panel.py:51-81 accept-drops class; instantiated per slot at panel.py:611-612); drops resolve path->asse... |
| 10 | Consolidate formats.py helpers and dead-code deletion post-mortem into an archit... | BACKLOG.md | docs | missing | hours | low | Still listed open in docs/BACKLOG.md:190-191 and wiki/Roadmap.md:61-62. No consolidated architecture note exists in docs/ (glob of docs/**/*.md shows ... |
| 11 | Eagle Gallery 3-panel layout tab | Roadmap.md | feature | missing | days | medium | wiki/Roadmap.md:14-22 still lists it under 'Live (deferred / not yet started)'. Grep for 'Eagle' in doxyedit/ hits only filebrowser.py:101 (Eagle-styl... |
| 12 | H6 interactive verification pass on 70k-asset project | BACKLOG.md | infra | missing | day | medium | docs/BACKLOG.md:30 still lists H6 open; no record of execution anywhere (grep 'H6/verification pass/70k' hits only BACKLOG/old perf notes). docs/TEST_... |
| 13 | Remove dead Kanban CSS selectors from themes.py | BACKLOG.md | refactor | missing | hours | low | themes.py:1580-1599 still ships selectors for QWidget#kanban_panel, QFrame[objectName="kanban_card"], QWidget[objectName="kanban_column"]. The re-ship... |
| 14 | Studio Tier-3: Layer masks | BACKLOG.md | feature | missing | week+ | low | No hits for layer_mask/alpha_mask/mask painting anywhere in doxyedit/ (only _crop_mask_item dimming in preview.py:821, studio.py:9446, unrelated). doc... |
| 15 | Remove remaining inline status-bar save-flash stylesheets in window.py | BACKLOG.md | refactor | partial | hours | low | The three cited window.py sites (2576/2587/6357) no longer exist; the save-flash moved with _save_project into project_io.py:222-225 (inline QStatusBa... |
| 16 | Studio Tier-3: Non-destructive filters per layer | BACKLOG.md | feature | partial | day | medium | Exists: filter_mode grayscale/invert/blur3/blur8 on image layers (models.py:241, studio.py:9674-9703 preview, exporter.py:497-511 export) and img_brig... |
| 17 | Tag hierarchy (parent tags with inheritance) | BACKLOG.md | feature | partial | day | medium | Shipped: TagPreset.parent_id field with round-trip (doxyedit/models.py:45, 52), hierarchy walkers get_tag_children/get_tag_ancestors (models.py:965-10... |
| 18 | Tiny window flash on project load in remaining code paths | BACKLOG.md | bug | partial | hours | low | Fix shipped for both known paths (commit 8d80508): project_io.py:366-403 defers win.show() until ProjectLoader loaded/failed fires in _open_collection... |
| 19 | H6: 70k-asset interactive verification | project_state_v25_cron.md | infra | missing | hours | medium | E:/git/doxyedit/docs/BACKLOG.md:30-41 - 'H6 - interactive verification pass' still listed open with its full checklist (tab swap latency, Auto-Post ca... |
| 20 | SQLite migration for 10k+ asset projects | project_vision.md | perf | missing | week+ | low | Project storage is still JSON: formats.py:1-13 ('Projects save as .doxy... Content is identical' to legacy JSON), project_io.py:22,42 (worker thread s... |
| 21 | Commercial itch.io release preparation | project_vision.md | infra | partial | days | medium | EXISTS: Nuitka exe build pipeline (build.bat root, dist/DoxyEdit.exe target, 11 build exclusions per changelog 1400, doxyedit.ico), __version__='2.5.7... |
| 22 | Duplicate finder / file unification scanner | project_future.md | feature | partial | day | high | Exists: Tools > Find Duplicate Files (window.py:2274), off-thread MD5 scan (_DupeScanThread window.py:90-119, _find_duplicates window.py:6753), result... |
| 23 | GL canvas Tiers 2-4 (Skia GL, OpenGL composite, dirty-rect culling) | next_session_priorities.md | perf | partial | week+ | low | Tier 2 SHIPPED: doxyedit/canvas_skia.py:2086-2115 CanvasSkiaGL via skia.GrDirectContext.MakeGL() bound to QOpenGLWidget FBO (line 2213), with context-... |
| 24 | Integrated filesystem browser (browse before import) | project_future.md | feature | partial | day | low | Exists: doxyedit/filebrowser.py (429 lines) - QFileSystemModel tree rooted at drives (filebrowser.py:170-192), asset-count badges + active-folder high... |
| 25 | P0 user-verification queue for shipped-but-unconfirmed fixes | next_session_priorities.md | infra | partial | hours | medium | All six code items verified present: 0a416bd (Escape clearing regardless of focus), 899e8d6 (right-click Delete crop removes from screen), 910279a (vi... |
| 26 | Residual inline styles in composer_left/stats/studio/filebrowser | project_state_v25_cron.md | ui | partial | hours | low | Residuals still exist exactly as the doc described: composer_left.py:227,240,244 (status dot / Ready / issue labels via inline setStyleSheet), stats.p... |
| 27 | Social tab crash (user-reported, unresolved) | next_session_priorities.md | bug | partial | hours | high | Not root-caused: docs/SESSION_2026-05-02.md:80 'Social tab crash - original report; no traceback received yet', and no social-crash commit exists afte... |
| 28 | Studio Tier-3 features (layer masks, blend modes, pen tool, etc.) | next_session_priorities.md | feature | partial | week+ | low | 3 of 6 shipped despite the 'deferred' label: blend modes (studio.py:2343-2354 + 2987-2998 property-panel combo, Alt+B/Alt+Shift+B cycle studio.py:5142... |
| 29 | Thumbnail ratio modes with fill/crop option | project_future.md | ui | partial | hours | low | Exists: fill/crop toggle - browser.py:466 fill_mode flag, browser.py:648-672 KeepAspectRatioByExpanding + crop when on vs KeepAspectRatio letterbox wh... |
| 30 | Manual QA test checklist: entire checklist unchecked | TEST_CHECKLIST.md | docs | missing | day | low | docs/TEST_CHECKLIST.md has 91 unchecked boxes, 0 checked; only history is the repo-reorg commit b33833a. Still references dead tabs ('Send to Canvas' ... |
| 31 | Scale Plan Phase 2: SQLite asset store with migration path | Scale Plan.md | perf | missing | week+ | low | grep 'sqlite' in doxyedit/ hits only thumbcache.py (GlobalCacheIndex content_index.db at thumbcache.py:46-61, per-project dims cache.db at thumbcache.... |
| 32 | Split monolithic __main__.py CLI (1830 lines) into subpackage; add file locking ... | review.md | refactor | missing | day | low | doxyedit/__main__.py still 1806 lines (wc -l); Glob doxyedit/cli/**/*.py returns nothing; grep for filelock/msvcrt/fcntl in doxyedit/ finds only GUI s... |
| 33 | Asset review brief Phase 2 remainders: drag-between-tag-groups, compare mode, Ob... | asset-review-tool-brief.md | feature | partial | week+ | low | Shipped: batch crop/resize to platform target dims (doxyedit/exporter.py:871 crop_and_resize, doxyedit/pipeline.py:403 batch_export_variants, doxyedit... |
| 34 | Asset review brief: PSD thumbnail extraction, filename-based tag auto-suggest, e... | asset-review-tool-brief.md | feature | partial | day | low | Exists: PSD thumbnails - imaging.py:49 load_psd_thumb (psd-tools) + imaging.py:187 get_shell_thumbnail (Windows shell cache, primary path), wired into... |
| 35 | Gantt chart renders empty bars: diagnostic added, root cause pending | SESSION_2026-05-02.md | bug | partial | hours | medium | Diagnostic shipped and present: doxyedit/gantt.py:360-372 logs the unscheduled / bad-format / out-of-range / in-range-no-platforms buckets when nothin... |
| 36 | Misc small cleanups from code review: debug prints, stale dialogs, hardcoded val... | review.md | refactor | partial | hours | low | SHIPPED: _show_whats_new now reads docs/CHANGELOG.md dynamically (window.py:7423-7457); _show_shortcuts generated from QAction registry, grouped dialo... |
| 37 | Move OneUp/MCP/browser-post HTTP off the UI thread; cache yaml config; dedupe MC... | review.md | perf | partial | hours | medium | Threading + dedupe done: _OneUpPushThread (doxyedit/window.py:274-322, used at 4430/4620), _OneUpFetchThread (window.py:220-260), _AutoPostThread for ... |
| 38 | Move PSD/image loads out of UI thread in timeline, composer previews, platforms ... | review.md | perf | partial | days | medium | ExportCache shipped: doxyedit/export_cache.py:22, used by quickpost (quickpost.py:183-227), directpost (directpost.py:432) and the auto-post batch (wi... |
| 39 | Move filesystem-heavy scans off the UI thread: health panel, duplicate/similar f... | review.md | perf | partial | day | medium | Dupes/similar: _DupeScanThread (window.py:90) and _SimilarScanThread (window.py:128), cancellable (CHANGELOG 'Find Duplicates / Find Similar off UI th... |
| 40 | PERFORMANCE.md high-impact future optimizations (QListView delegate, OpenGL view... | PERFORMANCE.md | perf | partial | hours | low | Shipped: (1) QListView IconMode + ThumbnailModel + ThumbnailDelegate replaced the QGridLayout grid (browser.py:1 docstring, 341, 461, 1596-1626 'repla... |
| 41 | PERFORMANCE.md low-priority optimizations bundle | PERFORMANCE.md | perf | partial | hours | low | Shipped: LRU eviction for in-memory pixmap cache with byte budget (thumbcache.py:438-441, 547-557); stat-syscall cache for sort-by-date/size (browser.... |
| 42 | Scale Plan Phase 3: windowed streaming model + tag search index for 50k+ assets | Scale Plan.md | perf | partial | week+ | low | Exists: inverted tag index (tag_id -> set[asset_id]) at models.py:1354-1359 with tag_users property at 1371-1375, used for filtering at browser.py:246... |
| 43 | Serialization boilerplate refactor: SocialPost/Project to_dict-from_dict pairs, ... | review.md | refactor | partial | day | low | Small dataclasses migrated to generic serialization: CanvasOverlay to_dict=asdict + fields-driven from_dict (models.py:340-345), same pattern for Rele... |
| 44 | Social tab crash: still unreproduced, awaiting traceback | SESSION_2026-05-02.md | bug | partial | hours | medium | docs/SESSION_2026-05-02.md:80 and docs/CHANGELOG.md:8 both still call it unreproduced. What exists: pythonw stderr redirect to last_run.log (tests/tes... |
| 45 | UI token discipline sweep: inline stylesheets and hardcoded colors across panels... | review.md | ui | partial | hours | low | Sweep largely done: commit 141dcaa 'tokenize all remaining hardcoded UI values across entire codebase', b75752d 'validator now ALL CLEAN', e905051 all... |
| 46 | Unbounded caches need eviction: preview_cache, GlobalCacheIndex, browser _scaled... | review.md | bug | partial | hours | low | 3 of 4 done. preview_cache: doxyedit/imaging.py:95-137 _prune_preview_cache (30-day age + 2GB cap, run at startup). browser _scaled_cache: doxyedit/br... |
| 47 | studio.py _AppEscapeFilter installed app-wide and never removed; duplicate Escap... | review.md | bug | partial | hours | low | The leak is fixed: _AppEscapeFilter no longer exists anywhere except review.md; Escape is now a QShortcut parented to the Studio widget with Applicati... |
| 48 | studio.py correctness cluster: menus ignore active theme, crop-label substring f... | review.md | bug | partial | day | medium | 2 of 3 fixed. Menus: doxyedit/studio_items.py:136-143 _themed_menu delegates to themes.apply_menu_theme which reads the active theme from QSettings (d... |
| 49 | window.py god-object refactor: PanelMixin lazy refresh, _rebind_project, _own_sa... | review.md | refactor | partial | days | low | Shipped: LazyRefreshMixin (panel_mixin.py:27) adopted by 7 panels (timeline, gantt, checklist, calendar_pane, stats, health, platforms/panel); _rebind... |
| 50 | window.py mutates module-global TAG_SHORTCUTS dict (cross-window state stomping) | review.md | bug | partial | hours | low | The worst stomper is fixed: project rebind no longer deletes entries from the module dict; it takes a per-window snapshot instead, with an explanatory... |
| 51 | Brush tool v1: primitive but smooth freehand painting | brush-system-plan.md | feature | missing | week+ | medium | No doxyedit/brush.py (Glob: zero hits); no BrushLayerItem/BrushStroke/'brush' overlay type anywhere in doxyedit/ (grep: zero hits); StudioTool enum ha... |
| 52 | E2: scaled-pyramid (mipmap-like) cache for the base pixmap | canvas-architecture-deep-dive.md | perf | missing | day | low | No pyramid/LOD code in StudioEditor: load_asset builds a single full-res QPixmap (doxyedit/studio.py:8523-8563), wheelEvent has no zoom-band LOD switc... |
| 53 | Group text overlay right-click style verbs under a Style submenu | studio-ui-redesign.md | ui | missing | hours | medium | studio_items.py:3675-3731 OverlayTextItem.contextMenuEvent is still flat: Apply This Style to All Text (3706), Find and Replace (3707), Save as Defaul... |
| 54 | Make Shift+S Skia preview editable (tool-drag integration) | gl-canvas-plan.md | feature | missing | days | low | All prerequisites shipped 2026-04-23 but the wiring never did: hit_test_image exists at doxyedit/canvas_skia.py:330, selection state (Day 7) at canvas... |
| 55 | Rebindable keyboard shortcuts panel | studio-ui-redesign.md | feature | missing | days | low | No Keyboard tab in the Studio Settings dialog (tabs listed at studio.py:13200-13446); no QKeySequenceEdit anywhere (grep across doxyedit/: zero hits).... |
| 56 | Toolbar grouping polish: native separators, five groups | studio-ui-redesign.md | ui | missing | hours | low | QLabel("/") separator anti-pattern still live throughout the Studio top bar: studio.py:6136, 6149, 6253, 6280, 6307, 6426, 6442, 6455, plus quickbar (... |
| 57 | Flip Horizontal / Flip Vertical for overlays and crops | studio-v2-spec.md | feature | partial | hours | low | Exists for overlays: CanvasOverlay.flip_h/flip_v at models.py:228-229; context-menu actions with Ctrl+Shift+H/V hints for image overlays (studio_items... |
| 58 | Focus-mode polish | studio-ui-redesign.md | ui | partial | hours | low | Focus mode itself is functional: btn_focus in the layer-sidebar footer so it stays visible while toggled (studio.py:6403-6412, 7993-8007), _on_focus_t... |
| 59 | Full undo coverage for all Studio mutations | studio-v2-spec.md | feature | partial | days | high | Exists: QUndoStack at studio.py:4923-4924 (limit 50), command classes AddCensorCmd/SetAttrCmd/SetZValueCmd/DeleteItemCmd/AddOverlayCmd/AddCropCmd at s... |
| 60 | GL Tier 1: re-enable QOpenGLWidget viewport behind a capability-detection gate | gl-canvas-plan.md | perf | partial | days | low | Shipped: memoized capability probe _probe_gl_viewport with real QOpenGLContext.create() check (studio.py:4220-4266), gate honoring studio_use_gl_viewp... |
| 61 | GL Tier 2: Skia GPU backend via GrDirectContext | gl-canvas-plan.md | perf | partial | week+ | low | Shipped: CanvasSkiaGL(QOpenGLWidget) at canvas_skia.py:2114-2456 with GrDirectContext.MakeGL (2213, 2248), Surface.MakeFromBackendRenderTarget bound t... |
| 62 | Open question: paste of platform-scoped overlays into projects lacking that plat... | studio-v2-spec.md | feature | partial | hours | low | doxyedit/studio.py:14366-14441 _paste_items_from_clipboard rebuilds overlays via CanvasOverlay.from_dict(od) and copies ov.platforms verbatim - no che... |
| 63 | Open question: rotate handle vs rotation slider for overlays | studio-v2-spec.md | ui | partial | day | low | Decision effectively resolved as 'both, per item type': drag rotate handles shipped on censors (doxyedit/studio_items.py:216-494, handle paint at 449-... |
| 64 | Optional PR 7: SVG tool icons, visual density polish, shape-variant keyboard cho... | studio-ui-redesign.md | ui | partial | hours | low | Icons: shipped as theme-aware painter-drawn QIcons instead of SVG - _StudioIcons class (studio.py:3304-3510) with light/dark variants, applied to Shap... |
| 65 | Rebuild floating Text Controls popup: sticky toolbar, preset footer, sticky-tool... | studio-ui-redesign.md | ui | partial | hours | low | Exists: reworked popup with live text editor (studio.py:7115-7126), named-style row Save/Apply/Delete (studio.py:7393-7416), Save as Default / Apply D... |
| 66 | Skia bundling de-risk spike (Nuitka onefile on clean Windows) | canvas-architecture-deep-dive.md | infra | partial | hours | low | Shipped: build.bat:43 adds --include-package=skia (commit 81bb363), and tools/skia_build_smoke.py (147 lines, commit 11094e3) validates every Skia API... |
| 67 | Studio Tier-3 deferred features: layer masks, blend modes, shape library, pen to... | studio-v2-spec.md | feature | partial | week+ | low | 3 of 6 shipped: blend modes (CanvasOverlay.blend_mode models.py:240, normal/multiply/screen/overlay/darken/lighten; 38 references across studio.py/stu... |
| 68 | Tag compositor backend in Studio perf log events | canvas-architecture-deep-dive.md | infra | partial | hours | low | studio.py:_perf_log_event (doxyedit/studio.py:4456-4471) adds only t/items/zoom - no 'compositor' field, and no STUDIO_COMPOSITOR constant exists (the... |
| 69 | studio_compositor feature flag with per-tier kill switch | gl-canvas-plan.md | infra | partial | hours | low | Exists: 'studio_compositor' QSettings key with skia_cpu default and skia_gl opt-in, read in _open_skia_preview at doxyedit/studio.py:8906-8914, with a... |
| 70 | Command Palette (Ctrl+Shift+P fuzzy action search) | ui-redesign-plan.md | feature | missing | week+ | medium | Grep for CommandPalette/command_palette hits only docs/ui-redesign-plan.md and tools/design_variants.py (design fiction). Ctrl+Shift+P is bound to hid... |
| 71 | Dual-palette VINIK_COLORS (dark-bg and light-bg tag color variants) | ui-redesign-plan.md | ui | missing | day | low | doxyedit/models.py:56-61 still defines a single 20-color VINIK_COLORS list; every consumer (browser.py:703, 1726; tagpanel.py:676; infopanel.py:355) i... |
| 72 | Eagle Phase 1: one-way library importer | Eagle Integration.md | feature | missing | days | low | Neither planned file exists: no doxyedit/eagle.py, no doxyedit/eagle_import_dialog.py (Glob of doxyedit/*.py, 56 files, has neither). 'Import from Eag... |
| 73 | Eagle Phase 3: push selected assets into an Eagle library | Eagle Integration.md | feature | missing | day | low | POST /api/item/addFromPath referenced only in wiki/Eagle Integration.md:61,118. No client code, no context-menu or File-menu action ('Send to Eagle' a... |
| 74 | Eagle Phase 4: export project as a valid Eagle .library folder | Eagle Integration.md | feature | missing | days | low | No exporter code: 13-char Eagle item IDs, .library writing, and the copy/thumbnails-only/metadata-only mode dialog exist only in wiki/Eagle Integratio... |
| 75 | Extract repeated _cb = max(14, _f + 2) checkbox-size formula to shared utility | TOKENIZATION_STATUS.md | refactor | missing | hours | low | grep 'max(14, _f + 2)' still hits 10 files: checklist.py:117, filebrowser.py:130, infopanel.py:31 + 64, platforms/panel.py:609 + 813 + 892, tagpanel.p... |
| 76 | First-class dialog-singleton pattern | ui-redesign-plan.md | refactor | missing | hours | low | No base class, decorator, or helper exists (grep for singleton/SingletonDialog/show_or_raise across doxyedit/ returns nothing). The d07683a hand-rolle... |
| 77 | Muted/dimmed unselected thumbnails when one is selected | Eagle Contrast.md | ui | missing | hours | low | ThumbDelegate.paint (browser.py:601-710) draws a selection fill + border for selected items (browser.py:631-643) and a hover fill, but never reduces o... |
| 78 | Search by dominant color | Eagle Contrast.md | feature | missing | days | low | Palette data pipeline exists: thumbcache.py:408-413 extracts 5 dominant colors (autotag.py:74 compute_dominant_colors), stored via browser.py:3117-312... |
| 79 | Shader tray: fix arrow icons facing wrong direction (remove swapped-file workaro... | TRAY_VIEW_SPEC.md | bug | missing | hours | low | The target code (shader_overlay.rpy, a Ren'Py in-game shader overlay) is not in this repo: 'find . -name *.rpy' returns nothing and no file references... |
| 80 | Sort by color | Eagle Contrast.md | feature | missing | hours | low | Sort combo items are fixed at browser.py:1534: 'By Folder, Name A-Z, Name Z-A, Newest, Oldest, Largest, Smallest, Starred First, Most Tagged' - no col... |
| 81 | Declutter toolbar: move Recursive / Hover Preview / Cache All to View menu or ov... | Eagle Contrast.md | ui | partial | hours | low | View-menu counterparts exist and are bidirectionally synced: window.py:2528-2557 (Hover Preview submenu with Size/Delay, Recursive Import, Cache All T... |
| 82 | Eagle-style grid polish: uniform square cells, hover-only filenames, no tag dots... | UI Direction  -  Eagle Layout.md | ui | partial | hours | low | DONE: hover-only filenames (browser.py:469 show_filenames 'always/hover/never'; window.py:2463 View>Display>Filenames menu, applied at window.py:5440)... |
| 83 | Make Notes a write-while-you-work facility instead of a main tab | ui-redesign-plan.md | ui | partial | day | medium | Exists: collapsible Project Notes panel under the Assets grid, View > Project Notes Panel toggle (window.py:543-558, 2405-2408, _toggle_project_notes ... |
| 84 | Minimal top bar: move import actions to File menu or single + button | UI Direction  -  Eagle Layout.md | ui | partial | hours | medium | DONE: the 7 filter buttons were collapsed into one 'Filters ▼' dropdown (browser.py:1408-1428). MISSING: '+ Folder'/'+ Files' are still standalone too... |
| 85 | Shader tray: tokenize remaining hardcoded values | TRAY_VIEW_SPEC.md | refactor | partial | hours | low | Exists: OVERLAY_UI_LOCKED.md:56 lists _SLAB_TRAY_FONT_SCALE = 0.8 and :57 _SLAB_ARROW_W_RATIO as locked tokens, indicating the font-scale (and arrow-w... |
| 86 | Studio toolbar icons do not re-render on theme change | ui-redesign-plan.md | bug | partial | hours | low | Fixed half: _StudioIcons._fg() reads the ACTIVE theme from QSettings, not DEFAULT_THEME (studio.py:3311-3325, commit 6aa9f1c), with light-theme ink de... |
| 87 | Unify the four social-post composition paths and export logic | ui-redesign-plan.md | refactor | partial | days | low | Export half shipped: doxyedit/export_cache.py (ExportCache, per-batch decode + censor/overlay memoization; CHANGELOG docs/CHANGELOG.md:1103) is shared... |


## Appendix B - Health Findings (40, by assessment)

### perf
- **[high] Collection restore performs N+1 full rebinds (every tab added switches + rebinds, then switches back...** - window.py:1362 comments 'Subsequent projects: add as tabs (without switching visible UI)' but _add_project_tab (tab_manager.py:33-42) calls _proj_tab_bar.setCurrentIndex(idx) then _switch_to_slot(idx), and _switch_to_slot (tab_manager.py:61-74) runs a FULL _rebind_project(clear_folder_state=True) pl...
  - Fix: Add tabs without switching during restore: give _add_project_tab a switch=False path (append slot + addTab with signals blocked, no setCurrentIndex/_switch_to_slot), used by the collection-restore loop at window.py:1362; keep the single _switch_to_slot(0) in _finalize. Also drop the redundant second...  (touch: doxyedit/tab_manager.py:33-42, doxyedit/tab_manager.py:61-74, doxyedit/window.py:1344-1369, doxyedit/window.py:1299-1303)
- **[high] compute_filtered stat storm: _stat_cache is nuked on every rebind, then 67k os.stat calls run on the...** - window.py:7829 does self.browser._stat_cache.clear() on every _rebind_project. Lines 7878-7884 then restore the project's saved sort_mode (e.g. Newest/By Folder) and call browser.refresh(), so _compute_filtered_uncached (browser.py:2380) hits the cold-cache stat loops at browser.py:2490-2501 and 253...
  - Fix: Stop clearing _stat_cache in _rebind_project (window.py:7829); clear it only on explicit F5 reload / file-watcher change events, and cap it (dict of 100k tuples is ~20MB, acceptable, or use an LRU trim). Optionally warm it off-thread: after project load, run the stat batch in a QThread/ThreadPoolExe...  (touch: doxyedit/window.py:7829, doxyedit/browser.py:2484-2509, doxyedit/browser.py:2526-2541, doxyedit/browser.py:1288)
- **[high] FolderBrowser._auto_expand blocks the GUI for up to 8.4s resolving Dropbox paths through QFileSystem...** - Today's worst stall: rebind.file_browser 8428ms (perf.log 2026-07-04 14:30:34), previously 3326ms (05-02 15:44). FolderBrowser.set_project (filebrowser.py:318-323) calls _update_folder_counts (properly cached by project version sig, filebrowser.py:366-369) then _auto_expand (filebrowser.py:325-355) ...
  - Fix: 1) Memoize the expand target: skip _auto_expand when (project sig, resolved target) equals the last run. 2) Defer it off the rebind critical path with QTimer.singleShot(0, ...) so the window paints first, and consider QFileSystemModel.directoryLoaded to expand incrementally instead of forcing sync r...  (touch: doxyedit/filebrowser.py:318-323, doxyedit/filebrowser.py:325-355, doxyedit/window.py:7910-7911)
- **[medium] ThumbCache.set_project does synchronous SQLite commits (and sometimes full DiskCache construction) o...** - perf.log: rebind.thumbcache_set_project 1973ms (04-28 12:05), 2950ms and 4274ms (05-08 15:38/15:58). ThumbCache.set_project (thumbcache.py:513-531) runs on the GUI thread from _rebind_project (window.py:7864-7868). Even in the common shared-cache/same-folder case it calls worker.clear_queue() + save...
  - Fix: Track a pending-writes counter in DiskCache and skip save_index() when zero (worker already flushes every 20 puts at thumbcache.py:431-433). Move the flush into the worker thread: post a 'flush' sentinel into the queue instead of committing from the GUI thread. For folder switches, build the new Dis...  (touch: doxyedit/thumbcache.py:513-531, doxyedit/thumbcache.py:193-200, doxyedit/thumbcache.py:106-137, doxyedit/window.py:7864-...)
- **[medium] _apply_theme full-window setStyleSheet costs 0.4-1.2s per genuine theme/accent change; fired per tab...** - window.py:1498 setStyleSheet(generate_stylesheet(...)) cascades a style re-evaluation over the entire widget tree; perf.log shows rebind.apply_theme at 0.35-1.2s in essentially every session, still 426-667ms today. The _theme_sig short-circuit (window.py:1481-1490) works for same-theme rebinds, but ...
  - Fix: Primary mitigation is the collection-restore fix (finding 1). Beyond that, two options if per-tab-switch cost still annoys: (a) cache generated stylesheets per (theme_id, accent, font_size) to skip generate_stylesheet (small win; the dominant cost is Qt's re-polish, not string building), or (b) stop...  (touch: doxyedit/window.py:1476-1530, doxyedit/themes.py (generate_stylesheet), doxyedit/window.py:7857-7863)
- **[low] _refresh_grid tail does 4 full-project passes (starred/tagged counts, dup-group/variant/used-tag reb...** - browser.py:2610-2636: after the (cached) filter compute, every _refresh_grid iterates all project assets twice for the count label (starred = sum(...), tagged = sum(...)) and once more to rebuild _duplicate_groups, _variant_sets and _used_tag_ids from asset.specs. At 67k assets that is a fixed ~40-8...
  - Fix: Cache the tail by the same (id(project), project.version) sig used elsewhere (cf. filebrowser.py:366-369): recompute starred/tagged counts and the group/variant/used-tag indexes only when the sig changes, since they depend on project content, not the active filter. ~1h including making mutation path...  (touch: doxyedit/browser.py:2610-2636, doxyedit/browser.py:2346-2369)
- **[low] project_load.json_parse 5.7s spike is a one-off cold-I/O event on a background thread - no code fix ...** - The single 5688ms json_parse (perf.log 2026-05-08 15:35:21) is 8-40x the steady state (120-770ms across ~40 loads, including 216-319ms in May-July). The timer at models.py:1116-1121 includes Path(path).read_text(), and Project.load runs inside ProjectLoader (QThread, session.py:74-87) for all intera...
  - Fix: No action. If it recurs, split the perf timer into read vs json.loads (2 lines in models.py load) to confirm it is I/O, before considering anything like orjson.  (touch: doxyedit/models.py:1115-1121, doxyedit/session.py:74-87)
### architecture
- **[critical] studio.py is a 15k-line monolith; StudioEditor alone is 10,276 lines / ~289 methods** - doxyedit/studio.py is 15,133 lines. The StudioEditor class (studio.py:4858 to EOF) spans 10,276 lines with roughly 289 methods. Individual methods are beyond reliable single-edit size: StudioScene keyPressEvent is 928 lines (studio.py:4942), _canvas_context_menu is 592 lines (studio.py:821), and _Sh...
  - Fix: Follow the already-proven H4 mixin pattern (SaveLoadMixin in project_io.py, TabManagerMixin in tab_manager.py). StudioEditor already has clean section markers that map 1:1 to mixins: layer panel (studio.py:11928, ~900 lines) -> studio_layers.py; actions (studio.py:12967, ~1,150 lines) -> studio_acti...  (touch: doxyedit/studio.py (whole file), new files doxyedit/studio_layers.py, studio_actions.py, studio_tools.py, studio_edit_op...)
- **[high] MainWindow god object: 8,439 lines, ~336 methods, plus 92 direct reach-ins to AssetBrowser private a...** - doxyedit/window.py MainWindow (window.py:325) has ~336 methods and 234 signal .connect() calls; it is the highest-churn file since May (39 commits). Worse than raw size is the encapsulation break: window.py touches self.browser._<private> 92 times (top offenders: _thumb_cache x16, _delegate x8, _sel...
  - Fix: Two-part fix. (1) Give AssetBrowser a small public API and move state ownership into browser.py: reset_for_project(clear_folder_state: bool), a thumb_cache property, set_eye_hidden_tags(), select_ids(), set_post_status(posts). _rebind_project's browser-clearing block (window.py:7824-7845) becomes on...  (touch: doxyedit/window.py:325, window.py:7824 (_rebind_project), window.py:90-324 (thread classes), doxyedit/browser.py:1236 (A...)
- **[high] The three biggest, highest-churn modules have effectively zero test coverage** - 94 test files exist and CI runs them (.github/workflows/checks.yml), but window.py, studio.py, and browser.py are each imported by exactly 1 test file. These are also the top-3 churn files since the May session (39/27/10 commits). The v2.5.6 test push covered CLI, models, and helpers - the GUI monol...
  - Fix: Do not try to test the monoliths in place; make testing a forcing function for the extractions above. Rule for future sessions: any logic pulled out of window.py/studio.py must land in a headless-importable module (no QApplication needed, or offscreen-safe) with a test in the same commit. Add one ch...  (touch: tests/ (new test_smoke_window.py), .github/workflows/checks.yml, extraction targets from findings 1-2)
- **[medium] Inverted dependency: GUI imports business logic from __main__.py; 91 function-local imports in windo...** - doxyedit/__main__.py is a 1,806-line CLI module, yet window.py imports cmd_transport (window.py:5684) and cmd_untransport (window.py:5734) from it - the GUI depends on the CLI entry point, a circular-import workaround by construction. More broadly window.py contains 91 function-local imports (17x mo...
  - Fix: Extract the transport/untransport implementation from __main__.py into doxyedit/transport.py; both __main__.py and window.py import it (removes the only true GUI->CLI edge). Then triage the 91 deferred imports: hoist the ones that are not startup-cost-motivated (models, themes are already imported a...  (touch: doxyedit/__main__.py:1420 (cmd_transport), __main__.py:1594 (cmd_untransport), doxyedit/window.py:5684, window.py:5734, ...)
- **[medium] studio_items.py: five overlay item classes each reimplement the resize-handle / mouse / context-menu...** - doxyedit/studio_items.py (4,158 lines) has CensorRectItem (:216), OverlayImageItem (:656), OverlayShapeItem (:1534), OverlayArrowItem (:3017), and OverlayTextItem (:3321) each carrying their own copy of the handle-hit-test / mousePress / mouseMove / mouseRelease / hoverMove / itemChange interaction ...
  - Fix: Extract a HandleInteractionMixin (handle hit-test, cursor selection, drag state machine, itemChange snap/undo hooks) that all five items inherit, parameterized by a get_handles() -> list[(id, QPointF)] hook. Extract a build_common_item_menu(item, menu) helper for the shared context-menu tail (raise/...  (touch: doxyedit/studio_items.py:216, :656, :1534, :3017, :3321, :711, :2705, :3675)
- **[medium] hasattr/getattr guard sprawl: 110 hasattr(self,...) in studio.py, 82 in window.py** - window.py has 82 hasattr(self, ...) + 34 getattr(self, ..., default) guards; studio.py has 110 + 45. Attributes like _timeline, _calendar_pane, _gantt_panel, _smart_folder_menu are created conditionally deep inside build methods, so every consumer defensively guards (see _rebind_project, window.py:7...
  - Fix: Declare every conditionally-created attribute in __init__ with a None default (self._timeline = None etc.), switch guards to 'if self._timeline is not None' as files are touched, and add a CLAUDE.md architecture rule: 'never hasattr(self, ...) - predeclare in __init__'. Do not do a big-bang sweep; f...  (touch: doxyedit/window.py:347 (__init__), doxyedit/studio.py StudioEditor __init__, CLAUDE.md Architecture section)
- **[medium] Coarse refresh fan-out: 25 full browser.refresh() calls from window.py** - window.py calls self.browser.refresh() 25 times (33 .refresh() calls total) as the universal 'something changed' response. With the 70k-asset ambition in the Scale Plan, full-grid refresh as the default invalidation is both a perf cliff and a correctness trap: agents adding features learn 'call brow...
  - Fix: As part of the AssetBrowser public API (finding 2), expose graded invalidation: refresh_assets(ids), refresh_post_status(posts), refresh_filters() alongside full refresh(). Then convert the 25 call sites where the change scope is knowable (star toggled, tag edit, post status change). Effort: API ~ha...  (touch: doxyedit/window.py (25 sites, grep 'self.browser.refresh()'), doxyedit/browser.py:1236)
- **[low] Duplicated utilities: two FlowLayouts, three thumbnail loaders, repeated scheduled_time parsing acro...** - FlowLayout is implemented twice (doxyedit/browser.py:222 and doxyedit/studio.py:3930 as _FlowLayout). Asset-thumbnail loading is implemented three times: composer_left.py:628 _load_pixmap, timeline.py:309 _load_thumb_direct, gantt.py:414 _thumb_for_post - each with its own fallback/scaling behavior,...
  - Fix: Create doxyedit/widgets_common.py for the single FlowLayout; create post_time.py with parse_scheduled(post) -> datetime/None, day_key(post) -> str, time_label(post) -> str; add a load_asset_thumb(asset, size, thumb_cache=None) helper (thumbcache.py is the natural home). Each is a mechanical consolid...  (touch: doxyedit/browser.py:222, doxyedit/studio.py:3930, doxyedit/composer_left.py:628, doxyedit/timeline.py:309, doxyedit/gant...)
- **[low] Dead and dormant code: imagehost.py unused by the app; canvas_skia.py is 2,461 lines behind a debug-...** - doxyedit/imagehost.py (166 lines) is imported only by tests/test_imagehost_cache.py and tests/test_imagehost_dispatch.py - zero app-code references; it is dead weight that agents will still read and 'maintain'. doxyedit/canvas_skia.py (2,461 lines, 4th-largest module) is reachable only via a hidden ...
  - Fix: imagehost.py: delete it plus its two test files, or wire it into the posting pipeline if the public-URL upload feature is still wanted (check with user - one decision, 15 minutes either way). canvas_skia.py: a ship-or-cut decision - if the Skia backend is the future per docs/gl-canvas-plan.md, keep ...  (touch: doxyedit/imagehost.py, tests/test_imagehost_cache.py, tests/test_imagehost_dispatch.py, doxyedit/canvas_skia.py, doxyedi...)
### tests
- **[critical] BackgroundSaver races the UI thread and silently drops failed autosaves (data loss)** - doxyedit/project_io.py:68-75 submit_project() hands the LIVE Project object to the worker thread, which calls body.build_save_dict(path) at project_io.py:112 while the UI thread can still be mutating assets/posts (autosave fires on a timer). A concurrent mutation during asdict iteration raises, the ...
  - Fix: Tests first: unit-test BackgroundSaver directly (offscreen QApplication, submit/flush/stop, failure path re-marks dirty). Then fix: either snapshot build_save_dict on the UI thread and submit the dict, or re-set _dirty = True in _on_bg_save_failed. Effort: 0.5 day for tests + a 5-line fix.  (touch: doxyedit/project_io.py:68-118, 184-203; doxyedit/window.py:8401-8413)
- **[critical] OneUp sync matches posts by caption[:40] fingerprint and can reset pushed posts to DRAFT (double-pos...** - window.py:4524-4525 matches local QUEUED posts to remote OneUp state via fp = caption_default[:40] - two posts sharing a 40-char caption prefix collide, marking the wrong post POSTED or FAILED. The CLEAN branch at window.py:4552-4555 resets any pushed-but-unlisted post to DRAFT and clears oneup_post...
  - Fix: Extract the sync decision logic (local posts + remote state dict -> actions) into a pure function in pipeline.py or oneup.py, then table-test it: collision, gone-from-remote, published, failed, scheduled, no-key. Effort: 1 day extraction + tests; the extraction is mostly mechanical since the loop al...  (touch: doxyedit/window.py:4520-4630, 274-320)
- **[high] Direct-post double-send guard (push_to_direct + sub_platform_status writeback) is fully untested** - The only thing preventing a Telegram/Discord/Bluesky re-send is the skip check at directpost.py:497-508 reading post.sub_platform_status, whose writers live in window.py:4584-4595 and window.py:6582-6585 inside untested UI code. grep shows zero tests reference push_to_direct (the HTTP clients ARE te...
  - Fix: Unit-test push_to_direct with fake clients injected via get_direct_clients monkeypatch: already-posted platforms skipped, partial failure leaves per-platform status, no clients = no export. Add one test asserting a second call sends nothing. Fix the reader/writer shape mismatch while there. Effort: ...  (touch: doxyedit/directpost.py:451-540; doxyedit/window.py:4577-4599, 6582-6585; doxyedit/browser.py:2095)
- **[high] Composer _save hand-copies every SocialPost field; a missed field silently reverts data on every edi...** - composer.py:371-404 copies ~15 fields one by one when editing an existing post; CLAUDE.md explicitly warns new SocialPost fields must be added here too. There is no test enforcing parity (composer.py has zero test imports beyond the smoke import list), so the failure mode is: add a field, forget com...
  - Fix: A parity test that does not need the widget: instantiate SocialPost, list its dataclass fields, and assert each field name appears in the _save source (or better, refactor _save to build a dict and update via from_dict-style merge, then behavior-test with qtbot). The static parity check is 1 hour an...  (touch: doxyedit/composer.py:371-425; doxyedit/models.py:591-668)
- **[high] Tag rename integrity (tag_definitions + custom_tags + asset.tags sync) has zero tests** - tagpanel.py:1041 _rename_tag must keep tag_definitions (dict key), custom_tags (array ids), asset.tags across every asset, tag_aliases, custom_shortcuts, hidden_tags and eye_hidden_tags in sync - CLAUDE.md calls this out as a hard invariant of the 1MB project file. tagpanel.py (1,188 lines) has no t...
  - Fix: Extract rename into a pure Project method (rename happens on model data, not widgets), then test: definitions/custom_tags stay mirrored, all asset tag lists updated, shortcuts and hidden lists remapped, alias chain preserved. Effort: half a day; also unlocks calling it from CLI.  (touch: doxyedit/tagpanel.py:1041; doxyedit/models.py (tag_definitions/custom_tags/_migrate_custom_tags))
- **[medium] studio.py (15,133 lines, 24% of the codebase) has effectively no coverage; scene-to-model writeback ...** - The largest module is covered by an import check in test_smoke.py:43 and one menu-resolution helper test (test_studio_items_helpers.py). Crops/censors/overlays authored in Studio are written back into asset dicts and then saved; that writeback path is untested, while only the downstream render (expo...
  - Fix: Do not try to test the canvas. Target the model boundary: construct StudioPanel offscreen with a fixture project, programmatically add/modify a crop + censor + overlay via its public methods, save, reload, assert geometry roundtrips. 3-5 such tests cover the highest-value seam. Effort: 1 day once th...  (touch: doxyedit/studio.py; doxyedit/studio_items.py; doxyedit/canvas_skia.py)
- **[medium] Tray persistence and .bak recovery path untested** - window.py's _save_project stores project.tray_items = work_tray.save_state() (project_io.py:216) but tray.py (1,681 lines) has zero tests and a known drag-drop bug history (memory: known_bugs). Separately, _load_project_from at project_io.py:411-427 has a .bak fallback path - the corruption-recovery...
  - Fix: Two cheap tests: (1) tray save_state/restore roundtrip with a fixture tray offscreen; (2) write a corrupt .doxy + valid .bak to a temp dir, call the load path, assert recovery. Effort: 2-3 hours.  (touch: doxyedit/tray.py; doxyedit/project_io.py:411-455, 216)
- **[medium] platforms/ package (1,719 lines: bluesky, mastodon, native_input, panel) has zero tests** - grep shows no test imports doxyedit.platforms; only doxyedit/bridge.py and window.py use it. This is a second, parallel posting implementation (distinct from directpost.py's clients, which are tested). Any payload or auth regression here ships blind.
  - Fix: Mirror the existing directpost test pattern (mocked urlopen, assert URL/payload/multipart shape, error paths) for platforms/bluesky.py and platforms/mastodon.py. The pattern already exists in test_bluesky_client.py / test_discord_webhook.py to copy from. Effort: half a day.  (touch: doxyedit/platforms/bluesky.py; doxyedit/platforms/mastodon.py; doxyedit/platforms/panel.py)
- **[medium] Harness: headless driving already works; highest-ROI investments are conftest + project fixture fact...** - Verified working today: full suite (670 tests) passes offscreen in 8.5s on this machine; MainWindow constructs headless and cycles all 6 tabs (test_smoke.py:66-157); MainWindow(_skip_autoload=True) is a ready-made test hook; tools/design_manifest.py already does offscreen show-grab-hide screenshots ...
  - Fix: Ranked by payoff: (1) tests/conftest.py with session QApplication + offscreen env, switch CI to pytest, add pytest-qt - 2 hours, unlocks widget behavior tests everywhere. (2) Project fixture factory: temp dir, tiny Pillow PNGs, populated Project with assets/tags/posts - the missing prerequisite for ...  (touch: .github/workflows/checks.yml:24-28; tests/ (no conftest.py); tools/design_manifest.py; requirements.txt (no pytest/pytes...)
### ui-compliance
- **[low] Validators pass, CI enforces them - baseline compliance is good** - Ran both repo validators: E:/git/doxyedit/scripts/tokenize_validate.py reports 'TOKENIZATION: ALL CLEAN' and E:/git/doxyedit/scripts/check_theme_contrast.py passes all 21 themes. CI (.github/workflows/checks.yml:21-24) runs both on every push/PR. No apply_theme() methods exist anywhere in doxyedit/ ...
  - Fix: Nothing to fix. Recorded so the parent agent knows the validators were actually executed, not just read.  (touch: scripts/tokenize_validate.py, scripts/check_theme_contrast.py, .github/workflows/checks.yml:21-24)
- **[medium] DOXYEDIT_UI_SPEC.md 'Current Violations (TODO)' section is stale - the listed migrations shipped** - docs/ressources/uidocs/DOXYEDIT_UI_SPEC.md:148-157 claims kanban.py, infopanel.py, filebrowser.py, and preview.py still carry apply_theme() methods with inline hardcoded styles. All four were migrated (commit 617b731 'refactor(theme): migrate all v2.2 panels to centralized generate_stylesheet()'); z...
  - Fix: Delete lines 148-157 (or replace with 'Historical: migrated in 617b731'). Change '7 theme instances' to '21 theme instances in 3 brightness tiers'. Add one sentence to the Token Reference intro: 'core subset - themes.py Theme dataclass (155 fields) is authoritative'. ~15 minutes, docs only.  (touch: docs/ressources/uidocs/DOXYEDIT_UI_SPEC.md:17,57-107,148-157; doxyedit/themes.py:948-973)
- **[medium] Hardcoded semantic status colors bypass theme tokens (FITNESS_COLORS, stats platform bars, studio sw...** - Three genuine violations of the spec's DON'T rules ('use different colors for the same semantic role across panels' / no hardcoded hex in QSS), all invisible to the validator because they are hex strings in QSS/dicts rather than QColor(): (1) doxyedit/tagpanel.py:19-23 FITNESS_COLORS = {'green': '#4...
  - Fix: (1) Replace FITNESS_COLORS values with THEMES[DEFAULT_THEME].success/.warning/.error (or the live theme via QSettings like composer_right.py:37-39 does). (2) stats.py:174 -> use theme.error / theme.accent (a _dt = THEMES[DEFAULT_THEME] pattern already exists in stats.py). (3) studio.py:3863 -> f'bor...  (touch: doxyedit/tagpanel.py:19-23,308-311; doxyedit/stats.py:174; doxyedit/studio.py:3863; doxyedit/themes.py:51-53)
- **[medium] tokenize_validate.py has a blind spot: hex/rgba colors inside setStyleSheet strings are never checke...** - scripts/tokenize_validate.py PATTERNS (lines 22-58) catch QColor(...), QPen, QFont, setFixed* etc., but contain no pattern for color literals embedded in QSS strings. That is exactly how every surviving violation escaped: '#333' (studio.py:3863), FITNESS_COLORS hex dict (tagpanel.py:19-23), '#ff6b6b...
  - Fix: Add two patterns: (r'setStyleSheet\([^)]*#[0-9a-fA-F]{3}', 'hex color inside setStyleSheet') won't work for multi-line f-strings, so simpler: flag any line containing both a quote-delimited QSS fragment and '#[0-9a-fA-F]{3,8}' or 'rgba(' outside themes.py (SELF_TOKEN_FILES already excludes it), then...  (touch: scripts/tokenize_validate.py:22-58,61-122; doxyedit/tagpanel.py:267,310,414; doxyedit/infopanel.py:220)
- **[low] Minor hardcoded QSS values in dynamic-color inline styles (bare px paddings, radii, rgba borders)** - The dynamic per-tag-color inline setStyleSheet pattern itself is a justified spec deviation (CLAUDE.md notes property selectors are unreliable on dynamic properties), but several literal pixel/alpha values ride along inside those strings: doxyedit/browser.py:1801 and doxyedit/infopanel.py:44 'paddin...
  - Fix: Sweep pass: replace bare px with the existing derived locals (pad = max(4, f//3), radius = size//2). tagpanel.py:310 is a 1-line fix (use self._dot_size // 2). window.py:4778 -> import and call the themes.py:1091 helper. Fold the rgba borders into 1-2 new Theme alpha tokens (e.g. dot_border_rgba) wh...  (touch: doxyedit/browser.py:1183,1801; doxyedit/infopanel.py:44,220; doxyedit/tagpanel.py:310; doxyedit/window.py:4778-4780; dox...)
- **[low] TOKENIZATION_STATUS.md line references and exception list have drifted from the code** - docs/ressources/uidocs/TOKENIZATION_STATUS.md (last updated 2026-04-15) still describes the system accurately, but its 'Known Acceptable Items' table points at stale lines: infopanel.py:193 -> now infopanel.py:229 (SEPARATOR_HEIGHT, infopanel.py:18); browser.py:151 BATCH_SIZE -> now browser.py:163; ...
  - Fix: Refresh the Known Acceptable Items table from the current ACCEPTABLE list (the validator is now the source of truth - say so explicitly in the md and drop exact line numbers in favor of file + symbol). Either add the 'icon decisions' exception sentence to CLAUDE.md UI Rules or reword the validator c...  (touch: docs/ressources/uidocs/TOKENIZATION_STATUS.md:64-79; scripts/tokenize_validate.py:61-122; E:/git/doxyedit/CLAUDE.md (UI ...)
### agentic-infra
- **[low] Baseline (do not rebuild): CI, validators, headless smoke-launch, plugin system, CLI all exist** - Several items the assessment prompt suggests are already shipped. E:/git/doxyedit/.github/workflows/checks.yml runs on windows-latest/py3.11: tokenize validator (line 22), theme contrast validator (line 24), and the full 94-file unittest suite with QT_QPA_PLATFORM=offscreen (lines 26-28). Headless s...
  - Fix: No action. This is context so proposals below build on top instead of duplicating. Effort: 0.  (touch: .github/workflows/checks.yml, tests/test_smoke.py, scripts/tokenize_validate.py, scripts/check_theme_contrast.py, doxyed...)
- **[high] No golden fixture .doxyproj: full-schema round-trip is untested, rarely-touched sections can silentl...** - There is no tests/fixtures/ directory and no checked-in project file. Every test hand-builds a minimal synthetic project inline (e.g. tests/test_cli.py:_build_project makes 2 bare assets; test_smoke.py:108-132 makes 1 post + 1 tag, zero assets with crops/censors/overlays/assignments). The v2.3+ sche...
  - Fix: Add tests/fixtures/golden_full.doxyproj.json with every schema section populated (2-3 assets carrying crops/censors/overlays/assignments/specs/notes, posts with posting_log, campaigns, multi-identity, blackouts, templates, aliases, shortcuts, hidden_tags), generated once by a small scripts/make_gold...  (touch: tests/fixtures/ (new), tests/test_golden_fixture.py (new), scripts/make_golden_fixture.py (new))
- **[high] CLI surface has drifted from its own help text; no drift checker and no machine-checkable command re...** - doxyedit/__main__.py's module docstring (lines 1-33) documents ~30 commands, but the hand-rolled elif dispatch handles at least 8 more that the docstring omits: find-dupes, sync-tags, strip-tags, assign-slots, export-proxies, extract-thumbs, search-advanced, post-history (grep 'cmd == "..."' shows 2...
  - Fix: Two small steps: (1) refactor the elif chain into a COMMANDS dict of name -> (handler, usage, one-liner) and generate the docstring/usage output from it (mechanical, ~1h, 1768-line file but the change is localized to main()); (2) add tests/test_cli_docs_drift.py asserting every COMMANDS key appears ...  (touch: doxyedit/__main__.py (dispatch ~lines 1650-1768 + docstring), wiki/CLI Reference.md, tests/test_cli_docs_drift.py (new))
- **[medium] No perf regression gate: 70k-asset scale target has zero automated protection** - doxyedit/perf.py (lines 1-13) is runtime-only telemetry writing to ~/.doxyedit/perf.log with a 100ms threshold; nothing in CI or tests measures load/save/summary cost. The Scale Plan wiki targets 10k+ assets and the user runs a ~70k-asset folder. An agent introducing an accidental O(n^2) in Project....
  - Fix: tests/test_perf_budget.py: generate a 10k-asset project purely in memory (loop constructing Asset dicts with tags/crops), time Project.from_dict, to_dict, save+load to a temp file, and summary(); assert generous CI-safe budgets (e.g. from_dict < 5s, summary < 1s on windows-latest) so runner variance...  (touch: tests/test_perf_budget.py (new), doxyedit/models.py (read-only reference), .github/workflows/checks.yml (no change neede...)
- **[medium] CI workflow is unhardened: no job timeout, no pip cache, no concurrency cancel, no failure artifacts** - .github/workflows/checks.yml (28 lines total) has: no timeout-minutes, so a hung offscreen Qt test (a classic PySide6 failure mode: modal dialog or nested event loop under offscreen) burns the 6h default runner limit; no pip cache, so PySide6+psd-tools+pywin32 reinstall from scratch every push (~2-3...
  - Fix: Four-line-ish patch: add 'timeout-minutes: 20' on the smoke job, 'cache: pip' on setup-python, a concurrency block with cancel-in-progress, and an actions/upload-artifact@v4 step with if: failure() for ~/.doxyedit/*.log. Separately add a requirements-ci.lock (pip freeze from a known-good env) used o...  (touch: .github/workflows/checks.yml:9-28, requirements.txt, requirements-ci.lock (new))
- **[medium] Doc-drift checker missing: docs reference files and claims that go stale, the known #1 hazard for fu...** - The session context itself warns 'do NOT trust a doc's claim that something is open'. docs/BACKLOG.md relies on manual strikethrough (lines 8-30 show shipped H4 items struck by hand); the CLI docstring drift (separate finding) is a live instance; CLAUDE.md, docs/DOCS.md, and CONTRIBUTING.md referenc...
  - Fix: scripts/check_doc_drift.py doing two cheap mechanical checks: (1) extract path-like references (backticked strings matching known repo patterns) from CLAUDE.md, CONTRIBUTING.md, docs/DOCS.md, docs/BACKLOG.md and assert each exists on disk; (2) assert commit hashes cited in BACKLOG.md/CHANGELOG.md re...  (touch: scripts/check_doc_drift.py (new), .github/workflows/checks.yml (add step), CONTRIBUTING.md (one paragraph))
- **[medium] Screenshot capability exists but produces no CI artifact: UI regressions are invisible to headless a...** - tools/design_manifest.py (lines 1-13) already captures every major view/panel/dialog to PNG per theme and dumps token JSON, exactly the machinery a visual harness needs, but it is a local-only design tool: never run in CI, no golden comparison, no artifact. Agents working headless (the normal mode p...
  - Fix: Phase 1 (30m, do this): add a CI step running design_manifest.py offscreen and uploading design_mockups/manifest_default.png via upload-artifact on every PR - human or agent can eyeball a single grid image per change. Phase 2 (optional, ~2h, only if phase 1 proves used): loose perceptual gate compar...  (touch: tools/design_manifest.py, .github/workflows/checks.yml, tools/manifest_baseline.json (new, phase 2))
- **[low] No out-of-process launch smoke: in-process import tests miss run.py / log-redirect / plugin-dir boot...** - test_smoke.py builds MainWindow in-process, which catches class-body errors, but nothing in CI boots the app the way users do: a separate python process through run.py with the pythonw log redirect (tests/test_run_log_redirect.py tests the helper, not the boot path), missing config.yaml handling (co...
  - Fix: Add a --smoke flag to the run path: boot MainWindow, QTimer.singleShot(2000, app.quit), exit 0 on clean teardown, nonzero on any exception. Then tests/test_launch_smoke.py runs subprocess [sys.executable, 'run.py', '--smoke'] with QT_QPA_PLATFORM=offscreen and asserts returncode 0 and empty-ish stde...  (touch: run.py, doxyedit/main.py, tests/test_launch_smoke.py (new))
- **[low] Plugin dev loop lacks a lint/dry-run entry point** - Plugins load only at app launch (docs/plugins.md: 'Restart DoxyEdit. The plugin loads automatically'); failures surface post-hoc in ~/.doxyedit/plugins.log via failed_plugins() (doxyedit/plugins.py:201). There is no way for an agent (or the user) to validate a plugin file without booting the GUI, so...
  - Fix: Add 'python -m doxyedit plugins lint <file.py>' reusing _PluginRegistry.discover_and_load machinery against a single file in isolation: import it, call register() with a stub API, report subscribed events and any exception with traceback, exit nonzero on failure. ~40 lines since the loader logic alr...  (touch: doxyedit/__main__.py, doxyedit/plugins.py:147-198, tests/test_plugins_lint.py (new))


## Appendix C - Docs Said Open, Code Says Shipped (115)

These were listed as open somewhere in the April docs but are verified implemented.
Kept here so the Batch 4 doc-refresh can strike them from their source docs.

- 'Edit Project Config' UI for config.yaml
- 2026-04-09 bug fixes (preview position, tray drag, collections, folder overlap, theme audit)
- Add _demote_to_draft helper to centralize post status/oneup_post_id invariant
- Add nuitka-crash-report.xml to .gitignore
- Advisory readiness gate before queuing a post
- Align and distribute tools for multi-selection
- Asset groups: delegate corner dots and link highlight borders
- Asset groups: link mode state + duplicate/variant lookup indexes
- Auto-link variants by filename stem
- Batch export pipeline per platform requirements
- Bulk operations UI (multi-select batch tag/star/delete/export)
- By Folder header overlap and collapse-click issues (deferred fix)
- CLI commands for post management (schedule, gaps, suggest, post CRUD)
- Campaign assembly workflow (assets into platform templates)
- Collections: warn on missing projects + Reload Collection action
- Composer left column: ImagePreviewPanel with SFW/NSFW toggle and crop status
- Composer right column: extract ContentPanel module
- Consolidate campaign facets (campaigns/gantt/calendar/checklist/stats/health) into one surface
- Contrast lint workstream: contrast_lint.py + tokenize semantic-mismatch checks
- Copy/paste scene items across sessions/projects
- Delete ~1300 lines of dead code: kanban.py, censor.py, overlay_editor.py, project.py, canvas.py, imagehost.py
- Duplicate scanner: 'Link as Duplicate Groups' button
- E1: collapse resize/rotate handle items into inline paint decorators
- E3: off-thread overlay pixmap pre-render
- E4: setItemIndexMethod(NoIndex) on StudioScene
- Explicit non-goal: cloud sync stays out of scope
- Export-on-queue: prepare platform images before OneUp push
- Extend E3 off-thread overlay render cache to gradient fills
- File browser: asset count badge delegate on folder rows
- File browser: auto-expand to project folders on load
- File browser: dim empty folders and highlight active filter folder
- File browser: grid-to-tree sync on asset selection
- File browser: inline search/filter box
- File browser: refresh asset counts on project mutations
- File browser: subfolder-inclusive folder filtering
- File browser: theme-aware styling
- Fix Ctrl+D shortcut conflict (Select None vs Docked Preview)
- Fix folder view section height/width overflow
- Fix tray drag-drop in normal (flat) view
- GL plan explicit non-goals: tiled backing store, custom per-shape GLSL, replacing Qt input
- Identity dialog inner-widget tokenization
- ImageViewer unification: migrate PreviewPane to BaseImageViewer
- Info Panel: asset metadata sidebar
- Kanban board (reimagined)
- Kanban/Gantt posting schedule board
- Layer panel drag-reorder actually changes Z-order
- Manual variant linking + group management via right-click menu
- Menu hover font-size consistency fix
- Menu reorganization (split 22-item Tools menu into groups)
- Merge health scan into project details column on Overview tab
- Migrate kanban/infopanel/filebrowser/preview apply_theme() styles to generate_stylesheet()
- Move InfoPanel into left sidebar
- Narrow mode (responsive layout for vertical/narrow screens)
- Notes tab markdown preview styling improvements
- Notification center for posting results
- Onboarding walkthrough for first-time users
- OneUp REST API client (oneup.py)
- Open question: layer drag cross-band semantics
- Open question: smart guide color choice
- Panel minimum-width discipline so Info panel can shrink on narrow screens
- Per-post export history / posting log
- Platforms tab rebuild: compact campaign strip + working campaign filter
- Platforms tab rebuild: remove broken assigned-art hive section
- Platforms tab rebuild: slot thumbnails + per-card readiness badge
- Platforms tab: right-click assign gives no feedback (known issue)
- PostComposer dialog (create/edit posts)
- Posting entry points: right-click 'Prepare for Posting' + Studio 'Queue This'
- Preview dialog multi-monitor position validation
- Project color mode (per-project accent/border color)
- Quickbar right-sizing (default collapsed + smaller header)
- Raise tab bar contrast / focus signaling
- Rebuild composer.py as thin two-column shell
- Redesign plan header claims most catalogued UI issues shipped by v2.5
- Remove tray maximum width restriction
- Rotate handles on censor items
- Scale Plan Phase 1: quick perf wins (id index, filter cache, incremental/background save, dynamic LRU)
- Scale Plan Phase 2.5: progressive thumbnail loading with priority tiers
- Scriptable plugin surface (user Python hooks)
- Shape tool nested variants including future Line and Polygon
- Sidebar-first navigation restructure
- Similar scanner: 'Create Variant Sets' button
- Smart Folders: saved filter presets
- Smart snap guides while dragging
- SocialPost + CollectionIdentity data models
- SocialPost censor_mode + platform_censor fields
- SocialPost nsfw_platforms + sfw_asset_ids fields
- Splitter handle hover indicator + remove duplicate handle rule
- Stacked QListViews rebuild of 'By Folder' sort mode
- Standing directive: Studio stabilization over new features
- Sticky insertion tools with Escape-to-exit
- Studio Preferences dialog (Ctrl+,)
- Studio Tier-3: Blend modes per layer
- Studio Tier-3: Shape primitives as persistent overlays
- Subscription platform automation (quick-post for 6 platforms)
- Surface keyboard shortcuts to first-time users
- Surface the multi-tray system visually
- Tab buttons stretch across full menu bar width
- Tab switch rebuilds all 14 panels (~300ms stall)
- Tag panel vs filter bar clarification tooltips
- Text tool drag-to-size (click = auto-width, drag = width-locked box)
- Theme tokens + QSS for timeline and post status badges
- Theme tokens for composer left panel
- Threaded/atomic project save + async reload; debounce collection autosave
- TimelineStream widget (scrollable post feed with day headers and gap markers)
- Tokenization audit itself (PROJECT CLEAN claim)
- Toolbar 'Files' button to toggle the File Browser
- Tray thumbnail delayed display fix
- Verify censor tab data flows to composer + manual UI test checklist
- Wire timeline into Platforms tab, kanban becomes legacy toggle
- YAML config file for custom platform definitions
- check_readiness(): per-asset per-platform readiness scoring
- pipeline.py: prepare_for_platform export chain with coordinate transforms
- platforms.py:737 _on_file_dropped references undefined event (NameError on non-asset drop)
- v2.5.6 NEEDS USER VERIFY bundle: Escape clearing fix, right-click Delete crop fix, 6 rebalanced themes, plugin end-to-end
- window.py:3151 post asset export silently drops all but the first asset
