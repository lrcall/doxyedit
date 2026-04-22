"""crossproject.py — Cross-project schedule awareness and conflict detection.

Lets multiple DoxyEdit projects see each other's posting schedules
to avoid conflicts and coordinate releases.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path


_REGISTRY_DIR = Path.home() / ".doxyedit"
_REGISTRY_PATH = _REGISTRY_DIR / "project_registry.json"


@dataclass
class ConflictWarning:
    date: str = ""
    severity: str = "info"       # info, warning, conflict
    message: str = ""
    current_post_id: str = ""
    other_project: str = ""
    other_project_path: str = ""
    conflict_type: str = ""      # same_day, same_platform_same_day, blackout, saturation


def load_registry() -> dict:
    """Load or create the project registry."""
    if _REGISTRY_PATH.exists():
        try:
            return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"projects": [], "groups": {}}


def save_registry(data: dict) -> None:
    """Write the registry back."""
    _REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    _REGISTRY_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def sync_registry_from_settings(settings) -> None:
    """Merge QSettings recent_projects into the registry."""
    reg = load_registry()
    known_paths = {p["path"] for p in reg["projects"]}

    recent = settings.value("recent_projects", []) or []
    for path in recent:
        path = str(path)
        if path and path not in known_paths and Path(path).exists():
            reg["projects"].append({
                "path": path,
                "alias": Path(path).stem.replace(".doxyproj", ""),
                "group": "",
                "enabled": True,
            })
            known_paths.add(path)

    save_registry(reg)


def register_project(path: str, alias: str = "", group: str = "") -> None:
    """Add or update a project in the registry."""
    reg = load_registry()
    for p in reg["projects"]:
        if p["path"] == path:
            if alias:
                p["alias"] = alias
            if group:
                p["group"] = group
            save_registry(reg)
            return
    reg["projects"].append({
        "path": path,
        "alias": alias or Path(path).stem.replace(".doxyproj", ""),
        "group": group,
        "enabled": True,
    })
    save_registry(reg)


def peek_project_schedule(path: str) -> list[dict]:
    """Lightweight read — extracts only posts + name from a project file.
    Does NOT load assets (avoids loading 3800+ assets into memory)."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        name = raw.get("name", Path(path).stem)
        posts = []
        for p in raw.get("posts", []):
            posts.append({
                "id": p.get("id", ""),
                "scheduled_time": p.get("scheduled_time", ""),
                "status": p.get("status", "draft"),
                "platforms": p.get("platforms", []),
                "caption_preview": (p.get("caption_default", "") or "")[:60],
                "project_name": name,
                "project_path": path,
            })
        return posts
    except Exception:
        return []


def peek_project_blackouts(path: str) -> list[dict]:
    """Read blackout periods from a project file without full load."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return raw.get("blackout_periods", [])
    except Exception:
        return []


class CrossProjectCache:
    """Caches peeked schedule data with mtime-based invalidation."""

    def __init__(self):
        self._cache: dict[str, tuple[float, list[dict]]] = {}  # path -> (mtime, posts)
        self._blackout_cache: dict[str, tuple[float, list[dict]]] = {}

    def refresh(self) -> None:
        """Invalidate entries whose files have changed."""
        for path in list(self._cache.keys()):
            try:
                current_mtime = os.path.getmtime(path)
                if current_mtime != self._cache[path][0]:
                    del self._cache[path]
            except (OSError, KeyError):
                self._cache.pop(path, None)

    def _collect(self, exclude_path: str, cache: dict, peek_fn):
        """Shared helper: iterate enabled registry entries, serve from cache
        or peek in parallel for uncached paths. Returns a flat list."""
        from concurrent.futures import ThreadPoolExecutor
        reg = load_registry()
        results: list = []
        to_peek: list[tuple[str, float]] = []

        for entry in reg["projects"]:
            if not entry.get("enabled", True):
                continue
            path = entry["path"]
            if path == exclude_path or not Path(path).exists():
                continue
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            cached = cache.get(path)
            if cached and cached[0] == mtime:
                results.extend(cached[1])
            else:
                to_peek.append((path, mtime))

        # Concurrent disk reads for cache misses. 4 workers is a reasonable
        # balance for HDD/SSD without thrashing. Each task is pure I/O + parse.
        if to_peek:
            with ThreadPoolExecutor(max_workers=min(4, len(to_peek))) as pool:
                for (path, mtime), data in zip(
                    to_peek, pool.map(lambda pm: peek_fn(pm[0]), to_peek)
                ):
                    cache[path] = (mtime, data)
                    results.extend(data)
        return results

    def get_all_schedules(self, exclude_path: str = "") -> list[dict]:
        """Return all posts from all enabled registry projects."""
        return self._collect(exclude_path, self._cache, peek_project_schedule)

    def get_all_blackouts(self, exclude_path: str = "") -> list[dict]:
        """Return all blackout periods from all enabled projects."""
        return self._collect(exclude_path, self._blackout_cache, peek_project_blackouts)


def detect_conflicts(
    current_posts: list,  # list of SocialPost
    other_schedules: list[dict],
    blackouts: list[dict] | None = None,
) -> list[ConflictWarning]:
    """Find scheduling conflicts between current project and others."""
    warnings = []

    # Build day -> posts map for other projects
    other_by_day: dict[str, list[dict]] = {}
    for p in other_schedules:
        day = (p.get("scheduled_time") or "")[:10]
        if day:
            other_by_day.setdefault(day, []).append(p)

    for post in current_posts:
        day = (post.scheduled_time or "")[:10]
        if not day:
            continue

        # Check same-day conflicts
        others_on_day = other_by_day.get(day, [])
        if others_on_day:
            # Group by project
            by_project: dict[str, list[dict]] = {}
            for o in others_on_day:
                by_project.setdefault(o["project_name"], []).append(o)

            for proj_name, proj_posts in by_project.items():
                # Check same platform same day
                my_plats = set(post.platforms) if post.platforms else set()
                other_plats = set()
                for op in proj_posts:
                    other_plats.update(op.get("platforms", []))

                overlap = my_plats & other_plats
                if overlap:
                    warnings.append(ConflictWarning(
                        date=day,
                        severity="warning",
                        message=f"{proj_name} also posting to {', '.join(overlap)} on {day}",
                        current_post_id=post.id,
                        other_project=proj_name,
                        other_project_path=proj_posts[0].get("project_path", ""),
                        conflict_type="same_platform_same_day",
                    ))
                else:
                    warnings.append(ConflictWarning(
                        date=day,
                        severity="info",
                        message=f"{proj_name} has {len(proj_posts)} post(s) on {day}",
                        current_post_id=post.id,
                        other_project=proj_name,
                        other_project_path=proj_posts[0].get("project_path", ""),
                        conflict_type="same_day",
                    ))

        # Check blackout periods
        for bo in (blackouts or []):
            bo_start = bo.get("start", "")
            bo_end = bo.get("end", "")
            bo_label = bo.get("label", "blackout")
            if bo_start <= day <= bo_end:
                warnings.append(ConflictWarning(
                    date=day,
                    severity="conflict",
                    message=f"Post falls in blackout: {bo_label} ({bo_start} to {bo_end})",
                    current_post_id=post.id,
                    conflict_type="blackout",
                ))

        # Check saturation (>3 total posts on one day)
        total_on_day = len(others_on_day) + 1  # +1 for current post
        if total_on_day > 3:
            warnings.append(ConflictWarning(
                date=day,
                severity="warning",
                message=f"{total_on_day} total posts across all projects on {day}",
                current_post_id=post.id,
                conflict_type="saturation",
            ))
