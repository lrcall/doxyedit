#!/usr/bin/env python3
"""doxyedit_mcp.py - MCP server exposing DoxyEdit projects to Claude.

Lets an AI agent (Claude Desktop, Claude Code, etc) read posts from
DoxyEdit project files without the DoxyEdit GUI needing to run.
Useful for drafting content in a chat session or checking "what was
my last post on r/indiedev" without opening the editor.

Storage: the MCP reads `.doxyproj.json` project files from the
directories configured via the DOXYEDIT_PROJECT_DIRS environment
variable (semicolon-separated). If unset, defaults to the repo's
own checkout so at least the development copy works out of the
box.

The currently-active browser page (POSTed by the userscript to
/doxyedit-feedback) is exposed via get_active_page by tailing the
persistent bridge log at %TEMP%/doxyedit_bridge.log for the most
recent "feedback.received" entry with a pageUrl. That read is
non-destructive; DoxyEdit's own feedback consumer sees the same
events.

Setup:

    1. pip install mcp
    2. Add to Claude Desktop config (usually
       %APPDATA%\\Claude\\claude_desktop_config.json on Windows,
       ~/Library/Application Support/Claude/claude_desktop_config.json on mac):

       {
         "mcpServers": {
           "doxyedit": {
             "command": "python",
             "args": ["E:/git/doxyedit/bin/doxyedit_mcp.py"],
             "env": {
               "DOXYEDIT_PROJECT_DIRS": "C:/path/to/projects;D:/other/path"
             }
           }
         }
       }

    3. Restart Claude Desktop.

Tools exposed:
    list_projects()                  -> [{name, path}]
    get_project_summary(name)        -> identity + post keys summary
    list_posts(name)                 -> [{id, platforms, status, ...}]
    get_post(name, post_id)          -> full SocialPost dict
    get_active_page()                -> {host, pageUrl, t} or null
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print("ERROR: mcp package not installed. Run: pip install mcp",
          file=sys.stderr)
    sys.exit(1)


# Directories to scan for *.doxyproj.json. Environment override wins;
# fallback is the repo the MCP server ships from, which at least
# covers the dev copy.
def _project_dirs() -> list[Path]:
    env = os.environ.get("DOXYEDIT_PROJECT_DIRS", "")
    if env:
        return [Path(p).expanduser() for p in env.split(";") if p.strip()]
    here = Path(__file__).resolve().parent
    return [here.parent]


def _list_project_files() -> list[Path]:
    out: list[Path] = []
    for d in _project_dirs():
        if not d.exists():
            continue
        for p in d.rglob("*.doxyproj.json"):
            out.append(p)
        for p in d.rglob("*.doxy"):
            out.append(p)
    return out


def _resolve_project(name: str) -> Path | None:
    """Match `name` against project basenames (with or without
    the .doxyproj.json suffix). First exact match wins."""
    for p in _list_project_files():
        if p.name == name:
            return p
        if p.stem == name:
            return p
        if p.stem.rstrip(".doxyproj") == name:
            return p
    return None


def _load_project(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _summarize_post(post: dict) -> dict:
    """Trim a SocialPost dict to the fields that matter in a tool
    response - avoids spamming the model with full dataclass dumps."""
    return {
        "id": post.get("id", ""),
        "platforms": post.get("platforms", []),
        "status": post.get("status", ""),
        "caption_default": (post.get("caption_default") or "")[:200],
        "captions_set": sorted(
            k for k, v in (post.get("captions") or {}).items() if v),
        "scheduled_time": post.get("scheduled_time", ""),
        "published_urls": post.get("published_urls", {}),
    }


def _active_page_from_log() -> dict | None:
    """Tail the bridge log for the most recent posted/page event
    and return host + pageUrl if found. No-op when DoxyEdit has
    never been run or no feedback has been POSTed yet."""
    log_path = Path(tempfile.gettempdir()) / "doxyedit_bridge.log"
    if not log_path.exists():
        return None
    try:
        with log_path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return None
    # Walk newest->oldest, return first entry with a pageUrl.
    for line in reversed(lines[-500:]):
        try:
            ev = json.loads(line.strip())
        except Exception:
            continue
        if ev.get("pageUrl"):
            return {
                "host": ev.get("host", ""),
                "pageUrl": ev.get("pageUrl"),
                "t": ev.get("t", 0),
            }
    return None


# ── MCP SERVER ──────────────────────────────────────────────────────

app = Server("doxyedit")


@app.list_tools()
async def list_tools_handler() -> list[Tool]:
    return [
        Tool(
            name="list_projects",
            description=(
                "List DoxyEdit project files discoverable under the "
                "configured directories. Returns objects with name "
                "(stem) and absolute path."),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_project_summary",
            description=(
                "Return identity fields (name, bio_blurb, hashtags) "
                "and a summarized list of posts for a project. Does "
                "not return the full post bodies - use list_posts + "
                "get_post for that."),
            inputSchema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        ),
        Tool(
            name="list_posts",
            description=(
                "Return a summarized list of all posts in a project. "
                "Each entry has id, platforms, status, caption "
                "preview, which platforms have custom captions, "
                "scheduled_time, and published_urls."),
            inputSchema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        ),
        Tool(
            name="get_post",
            description=(
                "Return the full SocialPost dict for a specific post "
                "id within a project."),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "post_id": {"type": "string"},
                },
                "required": ["name", "post_id"],
            },
        ),
        Tool(
            name="get_active_page",
            description=(
                "Return the most recent browser page the userscript "
                "reported (via /doxyedit-feedback) - host + pageUrl. "
                "Null if no page has been reported yet this session."),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@app.call_tool()
async def call_tool_handler(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    def _reply(obj: Any) -> list[TextContent]:
        return [TextContent(
            type="text",
            text=json.dumps(obj, ensure_ascii=False, indent=2))]

    if name == "list_projects":
        files = _list_project_files()
        return _reply([
            {"name": p.stem.replace(".doxyproj", ""),
             "path": str(p), "size": p.stat().st_size}
            for p in files])

    if name == "get_project_summary":
        path = _resolve_project(arguments.get("name", ""))
        if path is None:
            return _reply({"error": f"project not found: {arguments.get('name')}"})
        data = _load_project(path)
        if data is None:
            return _reply({"error": f"could not parse {path}"})
        identity = data.get("identity") or {}
        posts = data.get("posts") or []
        return _reply({
            "path": str(path),
            "name": identity.get("name", ""),
            "bio_blurb": (identity.get("bio_blurb") or "")[:300],
            "hashtags": identity.get("hashtags") or [],
            "platforms": data.get("platforms") or [],
            "post_count": len(posts),
            "post_ids": [p.get("id", "") for p in posts][:50],
        })

    if name == "list_posts":
        path = _resolve_project(arguments.get("name", ""))
        if path is None:
            return _reply({"error": f"project not found: {arguments.get('name')}"})
        data = _load_project(path)
        if data is None:
            return _reply({"error": f"could not parse {path}"})
        posts = data.get("posts") or []
        return _reply([_summarize_post(p) for p in posts])

    if name == "get_post":
        path = _resolve_project(arguments.get("name", ""))
        if path is None:
            return _reply({"error": f"project not found: {arguments.get('name')}"})
        data = _load_project(path)
        if data is None:
            return _reply({"error": f"could not parse {path}"})
        pid = arguments.get("post_id", "")
        for post in (data.get("posts") or []):
            if post.get("id") == pid:
                return _reply(post)
        return _reply({"error": f"post not found: {pid}"})

    if name == "get_active_page":
        return _reply(_active_page_from_log() or {"page": None})

    return _reply({"error": f"unknown tool: {name}"})


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
