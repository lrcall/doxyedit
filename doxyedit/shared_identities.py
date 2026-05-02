"""Cross-project identity sync.

Each Project carries its own .identities dict (name -> identity payload).
Without a shared store, updating Doxy's bio in one project leaves stale
copies in other projects with the same identity name.

This module provides a single shared file at
~/.doxyedit/identities.json that holds the canonical identity
definitions. On project load callers can call merge_into_project() to
fold the shared values into project.identities (project-local edits
still win until explicitly published). On identity save the user can
opt to publish back to the shared file.

Format:
    {
      "version": 1,
      "identities": {
          "<name>": { ... CollectionIdentity dict ... },
          ...
      }
    }
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_VERSION = 1


def shared_path() -> Path:
    """Resolve the shared identities file path. Created on first write."""
    return Path.home() / ".doxyedit" / "identities.json"


def load_shared() -> dict[str, dict]:
    """Return {name: identity_dict} from disk; empty dict if missing or
    corrupt. Never raises - a bad shared file should never block project
    load."""
    p = shared_path()
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    ids = raw.get("identities") or {}
    return ids if isinstance(ids, dict) else {}


def save_shared(identities: dict[str, dict]) -> bool:
    """Persist {name: identity_dict} to disk atomically. Creates the
    parent dir if missing. Returns True on success, False on any
    exception (caller can surface a status message)."""
    p = shared_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(
                {"version": _VERSION, "identities": identities},
                ensure_ascii=False, indent=2),
            encoding="utf-8")
        tmp.replace(p)
        return True
    except OSError:
        return False


def publish_one(name: str, identity_dict: dict) -> bool:
    """Write a single identity into the shared store, preserving
    other names. Returns True on success."""
    if not name:
        return False
    current = load_shared()
    current[name] = dict(identity_dict)
    return save_shared(current)


def merge_into_project(project_identities: dict[str, dict],
                       *, strategy: str = "fill_missing") -> dict[str, dict]:
    """Fold shared identities into a project's identities map.

    strategy:
      - "fill_missing" (default): only add identities the project
        doesn't already have. Project-local edits are never overwritten.
      - "shared_wins": shared values override project-local values
        for keys that exist in both. Use only after a user opts in.
      - "project_wins": project values override shared. Useful for
        export workflows.

    Returns a new dict (does not mutate inputs).
    """
    shared = load_shared()
    out: dict[str, dict] = {}
    if strategy == "shared_wins":
        for name, payload in project_identities.items():
            out[name] = dict(payload)
        for name, payload in shared.items():
            base = dict(out.get(name) or {})
            base.update(payload)
            out[name] = base
    elif strategy == "project_wins":
        for name, payload in shared.items():
            out[name] = dict(payload)
        for name, payload in project_identities.items():
            base = dict(out.get(name) or {})
            base.update(payload)
            out[name] = base
    else:  # fill_missing
        for name, payload in project_identities.items():
            out[name] = dict(payload)
        for name, payload in shared.items():
            if name not in out:
                out[name] = dict(payload)
    return out


def known_names() -> list[str]:
    """Return all identity names in the shared store, sorted."""
    return sorted(load_shared().keys())
