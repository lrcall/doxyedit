# Post state machine

Audit output for Batch G4. Confirms the contract across the four state fields reviewers flagged. All findings verified against `doxyedit/` at commit `7ad6d37`.

## Four state fields

| Field | Type | Scope | Meaning |
|---|---|---|---|
| `SocialPost.status` | enum (DRAFT / QUEUED / POSTED / FAILED / PARTIAL) | per post | Overall posting lifecycle for OneUp-managed platforms |
| `SocialPost.sub_platform_status[pid]` | dict | per post per subscription/direct platform | Per-platform result for non-OneUp pipelines (Telegram, Discord, Bluesky, subscription sites) |
| `SocialPost.engagement_checks[].done` | bool | per post per check window | Whether a scheduled engagement reminder has been dismissed |
| `PlatformAssignment.status` | str (PENDING / READY / POSTED / SKIP) | per asset per platform slot | Export readiness tracking at the asset level — unrelated to post pipeline |

Two pipelines, two authoritative fields:

- **OneUp pipeline**: owns `post.status` and `post.oneup_post_id`.
- **Direct/browser pipeline**: owns `post.sub_platform_status[pid]`.

They do not overlap. A post with multi-platform targets can be simultaneously `status=QUEUED` (for its OneUp accounts) and have `sub_platform_status["telegram"]={status: posted}` (for its direct targets). This is by design.

## post.status transitions

```
            (user action)            (user action)
  DRAFT ──────────────────> QUEUED ──────────────────> DRAFT
  │                          │    (_cancel_oneup_if_demoted)
  │                          │
  │                          ├──> POSTED  (sync: OneUp reports published)
  │                          ├──> FAILED  (push failed OR sync: OneUp reports failed)
  │                          └──> DRAFT   (sync: post gone from OneUp, oneup_post_id cleared)
  │
  └──> QUEUED  (push to OneUp succeeds)
  └──> FAILED  (push to OneUp fails with no successes)
```

**Writers (6 sites, all in `window.py`):**
- `3298` → DRAFT (push aborted: no schedule time)
- `3378` → QUEUED (push succeeded)
- `3382` → FAILED (push failed entirely)
- `3622` → POSTED (sync: OneUp reports published)
- `3638` → FAILED (sync: OneUp reports failed)
- `3657` → DRAFT (sync: CLEAN — post gone from OneUp)

Additional writers in `__main__.py` (CLI path) at 805, 836, 838, 873, 876 — parallel to `window.py` but for batch CLI operations.

**Readers:**
- `quickpost.py:145, 197` — skip if already posted per sub-platform
- `directpost.py:498-500` — skip direct platforms with status=posted
- Timeline / composer / stats display

## sub_platform_status transitions

```
  (initial: missing key)
         │
         ├──> {status: posted, posted_at: ts}  (direct or browser post succeeds)
         └──> {status: failed, error: msg}     (direct or browser post fails)
```

**Writers (4 sites, all in `window.py`):**
- `3677` → `posted` (direct-post path: Telegram/Discord/Bluesky success)
- `3680` → `failed` (direct-post path fails)
- `4979` → `posted` (browser-post auto-post success)
- `4983` → `failed` (browser-post auto-post fails)

**Readers:**
- `quickpost.py:145, 197` — skip already-posted sub-platforms
- `directpost.py:498-500` — early-exit if all three direct platforms already posted

## engagement_checks[].done transitions

```
  engagement_checks: [{check_at, done: false}, ...]
           │
           └──> done: true  (user clicks "Done" in timeline)
```

**Writer:** `timeline.py:285` — `_eng_done_direct` on user click.
**Readers:** `timeline.py:210, 630` — skip done checks when rendering pending engagement windows.

The field IS wired. Reviewer's "orphaned" claim was wrong.

## PlatformAssignment.status transitions

Unrelated to the post pipeline. Belongs to the asset-platform-slot assignment model.

**Writers:** `browser.py:3302` (user context menu), `platforms.py:800` (batch update).
**Readers:** `browser.py:2189` (grid filter), `exporter.py:216` (export report), `models.py:1011` (count).

## Double-post guards

Two independent guards, one per pipeline:

1. **OneUp side.** `window.py:3272` in `_push_post_to_oneup`:
   ```python
   if post.oneup_post_id:
       return
   ```
   Any path that clears `oneup_post_id` also updates `post.status` in the same code block:
   - `window.py:3205` — `_cancel_oneup_if_demoted` (requires `post.status == "draft"` as entry guard)
   - `window.py:3658` — sync CLEAN path (sets both `status = DRAFT` and `oneup_post_id = ""` together)

2. **Direct-post side.** `directpost.py:498-500` in `push_to_direct`:
   ```python
   tg_done = already.get("telegram", {}).get("status") == "posted"
   ...
   if not has_tg and not has_dc and not has_bs:
       return results
   ```
   Uses `sub_platform_status` as the source of truth. No path clears these entries without a reason (they are append-only under normal operation).

## Conclusion

No double-post risk found. The four fields have distinct scopes, non-overlapping writers, and consistent readers. The exploration agent was partially wrong about `engagement_checks[].done`; it is actually wired.

One minor improvement opportunity (not a bug): `post.status` transitions from a non-drafted state back to DRAFT happen in two places (3657, 3205). A `_demote_to_draft` helper method would centralize the invariant "clear oneup_post_id when setting status to DRAFT." Worth refactoring if future changes to that contract are expected; skipping for now.
