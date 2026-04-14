"""OneUp API client — schedules and syncs social media posts."""
from __future__ import annotations
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.parse import urlencode, quote
from urllib.error import HTTPError


BASE_URL = "https://www.oneupapp.io/api"


@dataclass
class OneUpResult:
    success: bool
    data: dict
    error: str = ""


class OneUpClient:
    """Thin wrapper around OneUp REST API. Uses stdlib urllib — no extra deps.

    OneUp API uses query-string params for everything:
      POST /api/scheduletextpost?apiKey=KEY&content=TEXT&social_network_id=ALL&...
      POST /api/scheduleimagepost?apiKey=KEY&content=TEXT&image_url=URL&...
    """

    def __init__(self, api_key: str, category_id: str = ""):
        self.api_key = api_key
        self.category_id = category_id  # OneUp category for organizing posts

    def _url(self, endpoint: str, params: dict | None = None) -> str:
        """Build URL with apiKey and optional extra query params."""
        p = {"apiKey": self.api_key}
        if self.category_id:
            p["category_id"] = self.category_id
        if params:
            p.update(params)
        qs = urlencode(p, quote_via=quote)
        return f"{BASE_URL}/{endpoint}?{qs}"

    def _request(self, method: str, endpoint: str,
                 params: dict | None = None,
                 body: Optional[dict] = None) -> OneUpResult:
        url = self._url(endpoint, params)
        data = json.dumps(body).encode("utf-8") if body else None
        headers = {"Content-Type": "application/json"} if body else {}
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                try:
                    result = json.loads(raw)
                except json.JSONDecodeError:
                    result = {"raw": raw}
                return OneUpResult(success=True, data=result)
        except HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            return OneUpResult(success=False, data={}, error=f"HTTP {e.code}: {error_body}")
        except Exception as e:
            return OneUpResult(success=False, data={}, error=str(e))

    # ---- Post scheduling ----

    def schedule_text_post(self, *, content: str,
                           social_network_id: str = "ALL",
                           scheduled_date_time: str = "") -> OneUpResult:
        """Schedule a text-only post.

        Args:
            content: Post text/caption
            social_network_id: "ALL" or specific network ID
            scheduled_date_time: "YYYY-MM-DD HH:MM" format
        """
        params = {
            "content": content,
            "social_network_id": social_network_id,
        }
        if scheduled_date_time:
            params["scheduled_date_time"] = scheduled_date_time
        return self._request("POST", "scheduletextpost", params)

    def schedule_image_post(self, *, content: str, image_url: str,
                            social_network_id: str = "ALL",
                            scheduled_date_time: str = "") -> OneUpResult:
        """Schedule an image post.

        Args:
            content: Post text/caption
            image_url: Public URL to the image
            social_network_id: "ALL" or specific network ID
            scheduled_date_time: "YYYY-MM-DD HH:MM" format
        """
        params = {
            "content": content,
            "image_url": image_url,
            "social_network_id": social_network_id,
        }
        if scheduled_date_time:
            params["scheduled_date_time"] = scheduled_date_time
        return self._request("POST", "scheduleimagepost", params)

    def schedule_post(self, *, content: str, image_urls: list[str] | None = None,
                      social_network_id: str = "ALL",
                      scheduled_date_time: str = "") -> OneUpResult:
        """Schedule a post — auto-selects text or image endpoint."""
        if image_urls and image_urls[0]:
            return self.schedule_image_post(
                content=content,
                image_url=image_urls[0],
                social_network_id=social_network_id,
                scheduled_date_time=scheduled_date_time,
            )
        return self.schedule_text_post(
            content=content,
            social_network_id=social_network_id,
            scheduled_date_time=scheduled_date_time,
        )

    # ---- Post management (these endpoints are guessed — adjust when confirmed) ----

    def get_post(self, post_id: str) -> OneUpResult:
        """Get a single post by ID."""
        return self._request("GET", f"posts/{post_id}")

    def list_posts(self, status: str = "scheduled") -> OneUpResult:
        """List posts by status."""
        return self._request("GET", "posts", {"status": status})

    def delete_post(self, post_id: str) -> OneUpResult:
        """Cancel/delete a scheduled post."""
        return self._request("DELETE", f"posts/{post_id}")

    def test_connection(self) -> OneUpResult:
        """Verify API key works."""
        return self._request("GET", "social-accounts")


def get_client_from_config(project_dir: str) -> Optional[OneUpClient]:
    """Load OneUp client from config.yaml or env var.

    Supports multi-account format:
        oneup:
          active_account: "main"
          accounts:
            main: { api_key: "...", category_id: "...", label: "Main" }

    Falls back to flat format: oneup: { api_key: "...", category_id: "..." }
    """
    config_path = Path(project_dir) / "config.yaml"
    api_key = ""
    category_id = ""
    if config_path.exists():
        try:
            import yaml
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            oneup = config.get("oneup") or {}

            # Multi-account format
            accounts = oneup.get("accounts")
            if accounts and isinstance(accounts, dict):
                active = oneup.get("active_account", "")
                acct = accounts.get(active) or next(iter(accounts.values()), {})
                api_key = acct.get("api_key", "")
                category_id = str(acct.get("category_id", ""))
            else:
                # Flat format (legacy)
                api_key = oneup.get("api_key", "")
                category_id = str(oneup.get("category_id", ""))
        except Exception:
            pass
    if not api_key:
        api_key = os.environ.get("ONEUP_API_KEY", "")
    if api_key:
        return OneUpClient(api_key, category_id)
    return None


def get_active_account_label(project_dir: str) -> str:
    """Return the label of the currently active OneUp account."""
    config_path = Path(project_dir) / "config.yaml"
    if not config_path.exists():
        return ""
    try:
        import yaml
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        oneup = config.get("oneup") or {}
        accounts = oneup.get("accounts")
        if accounts and isinstance(accounts, dict):
            active = oneup.get("active_account", "")
            acct = accounts.get(active, {})
            return acct.get("label", active)
        return ""
    except Exception:
        return ""


def get_connected_platforms(project_dir: str) -> list[dict]:
    """Return connected platforms for the active OneUp account.
    Each entry: {"id": "twitter", "name": "Twitter/X"}
    Falls back to default list if not configured."""
    config_path = Path(project_dir) / "config.yaml"
    if config_path.exists():
        try:
            import yaml
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            oneup = config.get("oneup") or {}
            accounts = oneup.get("accounts")
            if accounts and isinstance(accounts, dict):
                active = oneup.get("active_account", "")
                acct = accounts.get(active) or next(iter(accounts.values()), {})
                connected = acct.get("connected", [])
                if connected:
                    return connected
        except Exception:
            pass
    # Default fallback
    return [
        {"id": p, "name": p} for p in
        ["twitter", "instagram", "bluesky", "reddit", "patreon", "discord", "tiktok", "pinterest"]
    ]


def list_account_names(project_dir: str) -> list[tuple[str, str]]:
    """Return [(id, label), ...] of all configured OneUp accounts."""
    config_path = Path(project_dir) / "config.yaml"
    if not config_path.exists():
        return []
    try:
        import yaml
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        oneup = config.get("oneup") or {}
        accounts = oneup.get("accounts")
        if accounts and isinstance(accounts, dict):
            return [(k, v.get("label", k)) for k, v in accounts.items()]
        return []
    except Exception:
        return []


def sync_accounts_from_mcp(project_dir: str) -> list[dict]:
    """Fetch connected accounts from OneUp MCP server and save to config.yaml.
    Returns the list of accounts, or empty list on failure."""
    import json as _json
    from urllib.request import Request, urlopen

    config_path = Path(project_dir) / "config.yaml"
    if not config_path.exists():
        return []

    try:
        import yaml
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []

    oneup = config.get("oneup") or {}
    accounts_cfg = oneup.get("accounts") or {}
    active = oneup.get("active_account", "")
    acct = accounts_cfg.get(active) or next(iter(accounts_cfg.values()), {})
    api_key = acct.get("api_key", "")
    if not api_key:
        return []

    mcp_url = f"https://feed.oneupapp.io/mcp/oneup?apiKey={api_key}"

    try:
        # Initialize MCP session
        init = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "doxyedit", "version": "1.0"},
            },
        }
        req = Request(mcp_url, data=_json.dumps(init).encode(),
                      headers={"Content-Type": "application/json"})
        resp = urlopen(req, timeout=15)
        resp.read()
        sid = resp.headers.get("MCP-Session-Id", "")

        # Fetch accounts
        call = {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "list-social-accounts-tool", "arguments": {}},
        }
        headers = {"Content-Type": "application/json"}
        if sid:
            headers["MCP-Session-Id"] = sid
        req2 = Request(mcp_url, data=_json.dumps(call).encode(), headers=headers)
        resp2 = urlopen(req2, timeout=15)
        data = _json.loads(resp2.read().decode())
        text = data.get("result", {}).get("content", [{}])[0].get("text", "")
        raw_accounts = _json.loads(text).get("accounts", [])

        # Convert to config format
        connected = []
        for a in raw_accounts:
            connected.append({
                "id": a["social_account_id"],
                "name": f"{a['full_name']} (@{a['username']})",
                "platform": a["social_network_type"],
            })

        # Save to config.yaml
        if active and active in accounts_cfg:
            accounts_cfg[active]["connected"] = connected
        config["oneup"] = oneup
        config["oneup"]["accounts"] = accounts_cfg
        config_path.write_text(
            yaml.dump(config, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

        return connected
    except Exception:
        return []
