"""OneUp API client — schedules and syncs social media posts."""
from __future__ import annotations
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError


BASE_URL = "https://www.oneupapp.io/api"


@dataclass
class OneUpResult:
    success: bool
    data: dict
    error: str = ""


class OneUpClient:
    """Thin wrapper around OneUp REST API. Uses stdlib urllib — no extra deps."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def _url(self, endpoint: str) -> str:
        sep = "&" if "?" in endpoint else "?"
        return f"{BASE_URL}/{endpoint}{sep}apiKey={self.api_key}"

    def _request(self, method: str, endpoint: str, body: Optional[dict] = None) -> OneUpResult:
        url = self._url(endpoint)
        data = json.dumps(body).encode("utf-8") if body else None
        headers = {"Content-Type": "application/json"} if body else {}
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return OneUpResult(success=True, data=result)
        except HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            return OneUpResult(success=False, data={}, error=f"HTTP {e.code}: {error_body}")
        except Exception as e:
            return OneUpResult(success=False, data={}, error=str(e))

    def test_connection(self) -> OneUpResult:
        """Verify API key works by listing social accounts."""
        return self._request("GET", "social-accounts")

    def list_social_accounts(self) -> OneUpResult:
        """Get connected social media accounts."""
        return self._request("GET", "social-accounts")

    def create_post(self, *, image_urls: list[str], caption: str,
                    social_account_ids: list[str],
                    scheduled_time: Optional[str] = None) -> OneUpResult:
        """Create a scheduled post on OneUp."""
        body = {
            "type": "image",
            "mediaUrls": image_urls,
            "body": caption,
            "socialAccountIds": social_account_ids,
        }
        if scheduled_time:
            body["scheduledTime"] = scheduled_time
        return self._request("POST", "posts", body)

    def get_post(self, post_id: str) -> OneUpResult:
        """Get a single post by ID."""
        return self._request("GET", f"posts/{post_id}")

    def list_posts(self, status: str = "scheduled") -> OneUpResult:
        """List posts by status: scheduled, published, failed."""
        return self._request("GET", f"posts?status={status}")

    def delete_post(self, post_id: str) -> OneUpResult:
        """Cancel/delete a scheduled post."""
        return self._request("DELETE", f"posts/{post_id}")


def get_client_from_config(project_dir: str) -> Optional[OneUpClient]:
    """Load OneUp client from config.yaml or env var."""
    config_path = Path(project_dir) / "config.yaml"
    if config_path.exists():
        try:
            import yaml
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            key = (config.get("oneup") or {}).get("api_key", "")
            if key:
                return OneUpClient(key)
        except Exception:
            pass
    key = os.environ.get("ONEUP_API_KEY", "")
    if key:
        return OneUpClient(key)
    return None
