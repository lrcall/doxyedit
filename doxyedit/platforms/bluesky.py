"""
bluesky.py - ATProto API client for Bluesky. Post replies without touching the DOM.

Stdlib only (urllib + json). User generates an app password at
Settings → Advanced → App passwords, stores it in projects/<name>.json under
credentials.bluesky.{handle, app_password}, then this module can post as them.

Public surface:
    session = create_session(handle, app_password)
    post_reply(session, parent_url, text) -> {uri, cid}
"""

import json
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any


BSKY_BASE = "https://bsky.social/xrpc"
PUBLIC_APPVIEW = "https://public.api.bsky.app/xrpc"
DEFAULT_TIMEOUT = 15


class BlueskyError(Exception):
    pass


def _request_json(url: str, data: dict | None = None, headers: dict | None = None,
                  method: str = "GET") -> dict:
    headers = dict(headers or {})
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            err_data = json.loads(err_body)
            raise BlueskyError(
                f"HTTP {e.code} {err_data.get('error', '?')}: {err_data.get('message', err_body)}"
            ) from e
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise BlueskyError(f"HTTP {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise BlueskyError(f"network error: {e.reason}") from e


def _request_raw(url: str, body: bytes, content_type: str,
                 headers: dict | None = None, method: str = "POST") -> dict:
    """POST raw bytes with a non-JSON Content-Type. Used by uploadBlob
    where the body is the image file itself, not a JSON envelope."""
    headers = dict(headers or {})
    headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            err_data = json.loads(err_body)
            raise BlueskyError(
                f"HTTP {e.code} {err_data.get('error', '?')}: {err_data.get('message', err_body)}"
            ) from e
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise BlueskyError(f"HTTP {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise BlueskyError(f"network error: {e.reason}") from e


def create_session(identifier: str, password: str) -> dict:
    """Login. `identifier` is handle or email. `password` is an app password."""
    return _request_json(
        f"{BSKY_BASE}/com.atproto.server.createSession",
        {"identifier": identifier, "password": password},
        method="POST",
    )


def resolve_handle(handle: str) -> str:
    """Resolve a handle like 'foo.bsky.social' to a DID. No auth needed."""
    # Public AppView doesn't require auth for this one
    data = _request_json(
        f"{PUBLIC_APPVIEW}/com.atproto.identity.resolveHandle?handle={handle}"
    )
    return data["did"]


def get_post_record(session: dict, author_did: str, rkey: str) -> dict:
    """Fetch a post record by (author_did, rkey). Returns {uri, cid, value}."""
    url = (f"{BSKY_BASE}/com.atproto.repo.getRecord"
           f"?repo={author_did}&collection=app.bsky.feed.post&rkey={rkey}")
    return _request_json(
        url,
        headers={"Authorization": f"Bearer {session['accessJwt']}"},
    )


_POST_URL_RE = re.compile(
    r"^https?://bsky\.app/profile/([^/]+)/post/([^/?#]+)"
)


def parse_post_url(url: str) -> tuple[str, str]:
    """Extract (handle_or_did, rkey) from a bsky.app post URL."""
    m = _POST_URL_RE.match(url)
    if not m:
        raise BlueskyError(f"not a bluesky post URL: {url!r}")
    return m.group(1), m.group(2)


def post_reply(session: dict, parent_url: str, text: str) -> dict:
    """Post a reply to the given parent post URL.

    Returns {uri, cid} of the created reply.
    """
    if not text or not text.strip():
        raise BlueskyError("reply text is empty")
    if len(text) > 300:
        # Bluesky hard cap is 300 graphemes. Close enough at char level for our use.
        raise BlueskyError(f"reply is {len(text)} chars; bluesky max is 300")

    author_ref, rkey = parse_post_url(parent_url)
    author_did = author_ref if author_ref.startswith("did:") else resolve_handle(author_ref)

    parent = get_post_record(session, author_did, rkey)
    parent_uri = parent["uri"]
    parent_cid = parent["cid"]

    # Thread root: if parent itself is a reply, inherit its root; otherwise
    # parent IS the root of the thread.
    reply_ref = parent.get("value", {}).get("reply") or {}
    root = reply_ref.get("root")
    if root and root.get("uri") and root.get("cid"):
        root_uri = root["uri"]
        root_cid = root["cid"]
    else:
        root_uri = parent_uri
        root_cid = parent_cid

    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    record: dict[str, Any] = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": now,
        "reply": {
            "root": {"uri": root_uri, "cid": root_cid},
            "parent": {"uri": parent_uri, "cid": parent_cid},
        },
    }

    return _request_json(
        f"{BSKY_BASE}/com.atproto.repo.createRecord",
        {
            "repo": session["did"],
            "collection": "app.bsky.feed.post",
            "record": record,
        },
        headers={"Authorization": f"Bearer {session['accessJwt']}"},
        method="POST",
    )


def upload_blob(session: dict, image_bytes: bytes, mime_type: str) -> dict:
    """Upload a binary blob (image) to the user's repo. Returns the
    blob descriptor `{$type:"blob", ref:{$link}, mimeType, size}` that
    callers embed in a post record under app.bsky.embed.images.

    Bluesky's documented per-blob cap is ~1MB for images; larger blobs
    are rejected with a clear error from the upstream API which we
    surface verbatim as BlueskyError.
    """
    if not image_bytes:
        raise BlueskyError("upload_blob: empty image bytes")
    if not mime_type or not mime_type.startswith("image/"):
        raise BlueskyError(
            f"upload_blob: mime_type must start with image/, got {mime_type!r}")
    resp = _request_raw(
        f"{BSKY_BASE}/com.atproto.repo.uploadBlob",
        image_bytes,
        mime_type,
        headers={"Authorization": f"Bearer {session['accessJwt']}"},
        method="POST",
    )
    return resp["blob"]


def create_post(session: dict, text: str,
                images: list | None = None) -> dict:
    """Create a new top-level post (no reply parent). Returns {uri, cid}.

    Same 300-grapheme cap as replies; raise BlueskyError if over. Posts
    show up at https://bsky.app/profile/<handle>/post/<rkey> where rkey
    is the trailing segment of the returned uri.

    `images` is an optional list of `(bytes, mime_type, alt_text)`
    tuples. Each is uploaded via upload_blob and embedded as
    app.bsky.embed.images. Bluesky allows up to 4 images per post -
    extras are silently dropped.
    """
    if not text or not text.strip():
        raise BlueskyError("post text is empty")
    if len(text) > 300:
        raise BlueskyError(f"post is {len(text)} chars; bluesky max is 300")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    record: dict[str, Any] = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": now,
    }
    if images:
        embed_images = []
        for img in images[:4]:  # bsky cap
            if len(img) == 2:
                img_bytes, mime = img
                alt = ""
            else:
                img_bytes, mime, alt = img[0], img[1], img[2]
            blob = upload_blob(session, img_bytes, mime)
            embed_images.append({"alt": alt or "", "image": blob})
        record["embed"] = {
            "$type": "app.bsky.embed.images",
            "images": embed_images,
        }
    return _request_json(
        f"{BSKY_BASE}/com.atproto.repo.createRecord",
        {
            "repo": session["did"],
            "collection": "app.bsky.feed.post",
            "record": record,
        },
        headers={"Authorization": f"Bearer {session['accessJwt']}"},
        method="POST",
    )


def post_url_for(session: dict, create_record_response: dict) -> str:
    """Build a bsky.app URL from the {uri, cid} returned by create_post.

    The createRecord response uri looks like
        at://did:plc:abc/app.bsky.feed.post/3kxyz...
    bsky.app needs the user's handle (or did) and the trailing rkey,
    so we extract the rkey and build the public URL using the
    session's did. Caller can resolve did -> handle if a friendlier
    URL is wanted later.
    """
    uri = create_record_response.get("uri", "")
    rkey = uri.rsplit("/", 1)[-1] if "/" in uri else ""
    did = session.get("did", "")
    return f"https://bsky.app/profile/{did}/post/{rkey}"


def like_post(session: dict, post_url: str) -> dict:
    """Create a like record for the given post URL. Returns {uri, cid}."""
    author_ref, rkey = parse_post_url(post_url)
    author_did = author_ref if author_ref.startswith("did:") else resolve_handle(author_ref)
    parent = get_post_record(session, author_did, rkey)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    record = {
        "$type": "app.bsky.feed.like",
        "subject": {"uri": parent["uri"], "cid": parent["cid"]},
        "createdAt": now,
    }
    return _request_json(
        f"{BSKY_BASE}/com.atproto.repo.createRecord",
        {
            "repo": session["did"],
            "collection": "app.bsky.feed.like",
            "record": record,
        },
        headers={"Authorization": f"Bearer {session['accessJwt']}"},
        method="POST",
    )
