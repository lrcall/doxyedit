"""Pure decision logic for OneUp sync reconciliation (D2 semantics).

No Qt, no network, no side effects: plain data in, a list of actions
out. The window layer applies the actions (status writes, engagement
window generation, dirty flag, logging).

D2 semantics (user-approved):
- Local posts match remote entries by stored ``oneup_post_id`` ONLY.
  No caption-fingerprint matching, so two posts with identical
  captions can never cross-match.
- A pushed post whose id is NOT in the remote listing keeps its
  status unchanged. No DRAFT reset, no silent state clearing -
  manual re-queue is the accepted recovery.
- Remote "published" -> set_posted; "failed" -> set_failed;
  "scheduled" -> no action.
- Posts with no ``oneup_post_id`` are untouched by sync.
- Only QUEUED posts are considered at all.

``oneup_post_id`` may hold several remote ids (comma-separated, one
per account/subreddit push). Aggregation for multi-id posts:
- any id reported "failed"      -> set_failed (failure surfaces first)
- every id reported "published" -> set_posted
- anything else (still scheduled, partially published, or ids
  missing from the remote listing) -> no action, post stays queued.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

ACTION_SET_POSTED = "set_posted"
ACTION_SET_FAILED = "set_failed"


@dataclass(frozen=True)
class SyncAction:
    """One state change the caller should apply to a local post.

    needs_engagement is only meaningful for ACTION_SET_POSTED: True
    when the post has no engagement_checks yet, so the caller should
    generate engagement windows after flipping the status.
    """
    post_id: str
    action: str
    needs_engagement: bool = False


def _status_value(status) -> str:
    """Normalize SocialPostStatus (str Enum) or a raw string."""
    return getattr(status, "value", status) or ""


def _split_ids(raw: str) -> list[str]:
    """Split a comma-separated oneup_post_id into clean id tokens."""
    return [tok.strip() for tok in (raw or "").split(",") if tok.strip()]


def decide_sync_actions(
    local_posts_view: Iterable,
    remote_state: Optional[Mapping[str, str]],
) -> list[SyncAction]:
    """Decide which local posts change state given remote OneUp state.

    Args:
        local_posts_view: iterable of post-like objects exposing
            ``id``, ``status``, ``oneup_post_id`` and
            ``engagement_checks`` (truthiness only). Read-only - the
            objects are never mutated here.
        remote_state: mapping of remote OneUp post id -> status string
            ("scheduled" | "published" | "failed"). May be None/empty.

    Returns:
        Actions in local post order, one per post that must change.
        Posts needing no change produce no action.
    """
    remote = remote_state or {}
    actions: list[SyncAction] = []
    for post in local_posts_view:
        if _status_value(getattr(post, "status", "")) != "queued":
            continue
        ids = _split_ids(getattr(post, "oneup_post_id", ""))
        if not ids:
            # Never pushed (or legacy-empty): untouched by sync.
            continue
        statuses = [remote.get(rid) for rid in ids]
        if any(s == "failed" for s in statuses):
            actions.append(SyncAction(post.id, ACTION_SET_FAILED))
        elif all(s == "published" for s in statuses):
            actions.append(SyncAction(
                post.id, ACTION_SET_POSTED,
                needs_engagement=not getattr(
                    post, "engagement_checks", None)))
        # else: scheduled, partially published, or missing from the
        # remote listing - leave the post exactly as it is.
    return actions
