"""reminders.py — Scans project posts for pending release steps and surfaces alerts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from doxyedit.models import Project, SocialPost, EngagementWindow


@dataclass
class Reminder:
    """A pending action that needs the user's attention."""
    post_id: str = ""
    platform: str = ""
    identity: str = ""
    due_at: str = ""          # ISO datetime when the action is due
    message: str = ""
    urgency: str = "normal"   # "normal", "urgent", "overdue"
    step_index: int = 0       # index into release_chain


def generate_engagement_windows(post: SocialPost, connected_accounts: list[dict]) -> list[EngagementWindow]:
    """Generate engagement follow-up windows for a newly-posted post."""
    windows = []
    now = datetime.now()

    _URL_PATTERNS = {
        "twitter": "https://x.com/{username}",
        "reddit": "https://reddit.com/user/{username}/submitted",
        "bluesky": "https://bsky.app/profile/{handle}",
        "instagram": "https://instagram.com/{username}",
    }

    _SCHEDULE = [
        (15, "first_reactions", "Check first reactions, reply to early comments"),
        (60, "peak_engagement", "Peak engagement window, respond and boost"),
        (240, "follow_up", "Follow-up wave, engage with shares and late comments"),
        (1440, "next_day", "Next day check, thank followers, final replies"),
        (2880, "metrics", "Metrics review, note what worked for future posts"),
    ]

    for platform in post.platforms:
        username = ""
        for acct in connected_accounts:
            if acct.get("id") == platform:
                username = acct.get("name", "").split("@")[-1].rstrip(")")
                break

        url = ""
        for pattern_key, pattern in _URL_PATTERNS.items():
            if pattern_key in platform.lower():
                url = pattern.format(username=username, handle=username)
                break

        for delay_min, action, description in _SCHEDULE:
            windows.append(EngagementWindow(
                post_id=post.id,
                platform=platform,
                account_id=platform,
                check_at=(now + timedelta(minutes=delay_min)).isoformat(),
                action=action,
                url=url,
                notes=description,
            ))

    return windows


def scan_pending_reminders(project: Project) -> list[Reminder]:
    """Scan all posts for pending release chain steps and return reminders.

    A reminder is generated when:
    1. The post has a release_chain with 2+ steps
    2. The anchor step (index 0) has been posted (status="posted")
    3. A later step is still "pending"
    4. The step's due time (anchor posted_at + delay_hours) is approaching or past
    """
    reminders = []
    now = datetime.now()

    for post in project.posts:
        if not post.release_chain or len(post.release_chain) < 2:
            continue

        anchor = post.release_chain[0]
        if anchor.status != "posted" or not anchor.posted_at:
            continue

        try:
            anchor_time = datetime.fromisoformat(anchor.posted_at.rstrip("Z"))
        except (ValueError, TypeError):
            continue

        for i, step in enumerate(post.release_chain[1:], start=1):
            if step.status != "pending":
                continue

            due_time = anchor_time + timedelta(hours=step.delay_hours)
            hours_until = (due_time - now).total_seconds() / 3600

            if hours_until > 24:
                continue  # not due yet, skip

            if hours_until < 0:
                urgency = "overdue"
                msg = f"OVERDUE: {step.platform} post was due {abs(int(hours_until))}h ago"
            elif hours_until < 1:
                urgency = "urgent"
                msg = f"DUE NOW: {step.platform} post due in {int(hours_until * 60)}m"
            else:
                urgency = "normal"
                msg = f"Upcoming: {step.platform} post due in {int(hours_until)}h"

            # Try to find identity from post
            identity = post.collection or ""

            reminders.append(Reminder(
                post_id=post.id,
                platform=step.platform,
                identity=identity,
                due_at=due_time.isoformat(),
                message=msg,
                urgency=urgency,
                step_index=i,
            ))

    # Also scan for general Patreon cadence reminders from identities
    for name, identity_data in (project.identities or {}).items():
        schedule = identity_data.get("patreon_schedule")
        if not schedule:
            continue
        cadence = schedule.get("cadence_days", 0)
        if cadence <= 0:
            continue

        # Find last Patreon post for this identity
        last_patreon = None
        for post in sorted(project.posts, key=lambda p: p.scheduled_time or "", reverse=True):
            if post.collection == name and "patreon" in (post.platforms or []):
                if post.status in ("posted", "queued"):
                    try:
                        last_patreon = datetime.fromisoformat(
                            (post.scheduled_time or post.updated_at or "").rstrip("Z"))
                    except (ValueError, TypeError):
                        pass
                    break

        if last_patreon:
            next_due = last_patreon + timedelta(days=cadence)
            hours_until = (next_due - now).total_seconds() / 3600
            reminder_hours = schedule.get("reminder_hours_before", 24)

            if hours_until <= reminder_hours:
                if hours_until < 0:
                    urgency = "overdue"
                    msg = f"OVERDUE: {name} Patreon post was due {abs(int(hours_until))}h ago"
                else:
                    urgency = "normal" if hours_until > 6 else "urgent"
                    msg = f"{name}: Patreon post due in {int(hours_until)}h (every {cadence}d)"

                reminders.append(Reminder(
                    post_id="",
                    platform="patreon",
                    identity=name,
                    due_at=next_due.isoformat(),
                    message=msg,
                    urgency=urgency,
                ))

    # Scan engagement checks
    for post in project.posts:
        if not post.engagement_checks:
            continue
        for check_dict in post.engagement_checks:
            check = EngagementWindow.from_dict(check_dict)
            if check.done:
                continue
            try:
                check_time = datetime.fromisoformat(check.check_at)
            except (ValueError, TypeError):
                continue
            minutes_until = (check_time - now).total_seconds() / 60
            if minutes_until > 15:
                continue  # not due yet
            if minutes_until < 0:
                urgency = "overdue"
                msg = f"OVERDUE: {check.action} for {check.platform} ({abs(int(minutes_until))}m ago)"
            elif minutes_until < 5:
                urgency = "urgent"
                msg = f"NOW: {check.action} for {check.platform}"
            else:
                urgency = "normal"
                msg = f"Soon: {check.action} for {check.platform} in {int(minutes_until)}m"
            reminders.append(Reminder(
                post_id=post.id,
                platform=check.platform,
                identity=post.collection or "",
                due_at=check.check_at,
                message=msg,
                urgency=urgency,
            ))

    # Sort by urgency then due time
    urgency_order = {"overdue": 0, "urgent": 1, "normal": 2}
    reminders.sort(key=lambda r: (urgency_order.get(r.urgency, 3), r.due_at))

    return reminders


def format_reminders_table(reminders: list[Reminder]) -> str:
    """Format reminders as a human-readable table for CLI output."""
    if not reminders:
        return "No pending reminders."

    lines = ["REMINDERS", "=" * 60]
    for r in reminders:
        icon = {"overdue": "!!", "urgent": "!", "normal": " "}[r.urgency]
        identity = f"[{r.identity}] " if r.identity else ""
        lines.append(f"  {icon} {identity}{r.message}")
        if r.due_at:
            lines.append(f"      Due: {r.due_at[:16]}")
    return "\n".join(lines)
