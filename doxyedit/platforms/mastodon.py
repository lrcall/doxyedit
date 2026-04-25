"""
mastodon.py - Mastodon REST API client. Post replies without touching the DOM.

Stdlib only. User creates an app at Settings → Development → New application
(enable write:statuses scope), copies the generated access token, stores under
credentials.mastodon.{instance, access_token}.

Public surface:
    post_reply(credentials, parent_url, text) -> {uri, id}
"""

import json
import re
import urllib.request
import urllib.error
from typing import Any


class MastodonError(Exception):
    pass


_URL_RE = re.compile(r"^https?://([^/]+)/@[^/]+/(\d+)")


def _request_json(url: str, token: str, data: dict | None = None, method: str = "GET") -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8"))
            raise MastodonError(f"HTTP {e.code}: {err.get('error', e.reason)}") from e
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise MastodonError(f"HTTP {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise MastodonError(f"network error: {e.reason}") from e


def parse_status_url(url: str) -> tuple[str, str]:
    """Extract (instance_host, status_id) from a Mastodon status URL.

    Supports:
    - https://<instance>/@<user>/<id>
    - https://<instance>/<@user>/<id> (some variants)
    """
    m = _URL_RE.match(url)
    if not m:
        raise MastodonError(f"not a mastodon status URL: {url!r}")
    return m.group(1), m.group(2)


def post_reply(credentials: dict, parent_url: str, text: str) -> dict:
    """Post a reply to the parent status. Returns {id, uri, url}."""
    instance = credentials.get("instance") or parse_status_url(parent_url)[0]
    token = credentials.get("access_token")
    if not token:
        raise MastodonError("no access_token in credentials")
    _, status_id = parse_status_url(parent_url)
    result = _request_json(
        f"https://{instance}/api/v1/statuses",
        token,
        {
            "status": text,
            "in_reply_to_id": status_id,
            "visibility": "public",
        },
        method="POST",
    )
    return {"id": result.get("id"), "uri": result.get("uri"), "url": result.get("url")}


def create_post(credentials: dict, text: str) -> dict:
    """Create a new top-level status. Returns {id, uri, url} where url
    is the user-facing https://<instance>/@<user>/<id> link."""
    instance = credentials.get("instance")
    token = credentials.get("access_token")
    if not instance:
        raise MastodonError("no instance in credentials")
    if not token:
        raise MastodonError("no access_token in credentials")
    if not text or not text.strip():
        raise MastodonError("status text is empty")
    result = _request_json(
        f"https://{instance}/api/v1/statuses",
        token,
        {"status": text, "visibility": "public"},
        method="POST",
    )
    return {"id": result.get("id"), "uri": result.get("uri"),
            "url": result.get("url")}


def favourite(credentials: dict, status_url: str) -> dict:
    """Favourite (like) a status."""
    instance = credentials.get("instance") or parse_status_url(status_url)[0]
    token = credentials.get("access_token")
    if not token:
        raise MastodonError("no access_token in credentials")
    _, status_id = parse_status_url(status_url)
    return _request_json(
        f"https://{instance}/api/v1/statuses/{status_id}/favourite",
        token,
        {},
        method="POST",
    )
