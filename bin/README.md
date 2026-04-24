# DoxyEdit MCP server

Read-only MCP server that exposes DoxyEdit project data (identity, posts, the currently-active browser page) to any MCP-aware client — Claude Desktop, Claude Code, Cowork.

## What you get

Tools the agent can call from any chat:

| Tool | Purpose |
|------|---------|
| `list_projects` | Discover `*.doxyproj.json` files under configured dirs. |
| `get_project_summary(name)` | Identity + post-ids summary for a project. |
| `list_posts(name)` | All posts in a project, each trimmed to id, platforms, status, caption preview, published URLs. |
| `get_post(name, post_id)` | Full SocialPost dict for one post. |
| `get_active_page` | Most recent browser page the userscript reported via the bridge. |

## Setup

```
pip install mcp
```

Add to Claude Desktop config (Windows: `%APPDATA%\Claude\claude_desktop_config.json`; mac: `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "doxyedit": {
      "command": "python",
      "args": ["E:/git/doxyedit/bin/doxyedit_mcp.py"],
      "env": {
        "DOXYEDIT_PROJECT_DIRS": "C:/path/to/projects;D:/other/projects"
      }
    }
  }
}
```

Restart the client. Ask something like "list my doxyedit projects" — the agent calls `list_projects`.

`DOXYEDIT_PROJECT_DIRS` takes a semicolon-separated list; each directory is scanned recursively for `*.doxyproj.json` and `*.doxy`. When unset, falls back to the repo root this MCP ships from so the dev copy works out of the box.

## Read-only for now

This first cut is intentionally read-only. Future tools could add `add_post`, `update_identity`, etc. — but mutations have to land through DoxyEdit's own `_save_project_silently` to keep autosave invariants + Qt signals consistent, so they're better deferred until the MCP can talk to a running DoxyEdit instance (over the HTTP bridge).

## Active-page tool

`get_active_page` tails `%TEMP%/doxyedit_bridge.log` for the most recent userscript feedback entry with a `pageUrl`. Works whenever DoxyEdit has been running and the userscript has hit the bridge at least once in the current session. When the log is empty (fresh machine) it returns `{"page": null}` — the agent can use that as the signal to ask the user where they are.
