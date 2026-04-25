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


def _request_multipart(url: str, token: str, fields: dict,
                       file_field: str, file_bytes: bytes,
                       file_mime: str, file_name: str = "upload") -> dict:
    """POST a multipart/form-data body. Used by /api/v2/media because
    Mastodon expects a real file upload, not a JSON envelope. Hand-rolls
    the multipart body since stdlib has no built-in helper."""
    import uuid
    boundary = "----doxyedit" + uuid.uuid4().hex
    parts: list[bytes] = []
    for k, v in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
        parts.append(str(v).encode("utf-8"))
        parts.append(b"\r\n")
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        f'Content-Disposition: form-data; name="{file_field}"; '
        f'filename="{file_name}"\r\n'.encode())
    parts.append(f"Content-Type: {file_mime}\r\n\r\n".encode())
    parts.append(file_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        # Media uploads are slower than text - bump the timeout.
        with urllib.request.urlopen(req, timeout=60) as resp:
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


def upload_media(credentials: dict, image_bytes: bytes, mime_type: str,
                 description: str = "") -> dict:
    """Upload an image to Mastodon's media endpoint. Returns the media
    descriptor; callers attach the returned id to a status via
    media_ids. /api/v2 returns 202 + an id that's eventually ready;
    most servers process small images synchronously enough that the
    next create_status sees it ready, so we don't block on async
    polling here."""
    instance = credentials.get("instance")
    token = credentials.get("access_token")
    if not instance:
        raise MastodonError("no instance in credentials")
    if not token:
        raise MastodonError("no access_token in credentials")
    if not image_bytes:
        raise MastodonError("upload_media: empty image bytes")
    if not mime_type or not mime_type.startswith("image/"):
        raise MastodonError(
            f"upload_media: mime_type must start with image/, got {mime_type!r}")
    fields = {"description": description} if description else {}
    return _request_multipart(
        f"https://{instance}/api/v2/media",
        token,
        fields,
        file_field="file",
        file_bytes=image_bytes,
        file_mime=mime_type,
        file_name="image" + _ext_for_mime(mime_type),
    )


def _ext_for_mime(mime: str) -> str:
    if mime == "image/png": return ".png"
    if mime in ("image/jpeg", "image/jpg"): return ".jpg"
    if mime == "image/webp": return ".webp"
    if mime == "image/gif": return ".gif"
    return ""


def create_post(credentials: dict, text: str,
                images: list | None = None) -> dict:
    """Create a new top-level status. Returns {id, uri, url} where url
    is the user-facing https://<instance>/@<user>/<id> link.

    `images` is an optional list of `(bytes, mime_type, alt_text)`
    tuples. Each is uploaded via upload_media and attached via
    media_ids. Mastodon's per-status cap is 4 attachments; extras
    are silently dropped."""
    instance = credentials.get("instance")
    token = credentials.get("access_token")
    if not instance:
        raise MastodonError("no instance in credentials")
    if not token:
        raise MastodonError("no access_token in credentials")
    if not text or not text.strip():
        raise MastodonError("status text is empty")
    payload: dict = {"status": text, "visibility": "public"}
    if images:
        media_ids = []
        for img in images[:4]:  # mastodon cap
            if len(img) == 2:
                img_bytes, mime = img
                alt = ""
            else:
                img_bytes, mime, alt = img[0], img[1], img[2]
            media = upload_media(credentials, img_bytes, mime,
                                  description=alt or "")
            media_id = media.get("id")
            if media_id:
                media_ids.append(media_id)
        if media_ids:
            payload["media_ids"] = media_ids
    result = _request_json(
        f"https://{instance}/api/v1/statuses",
        token,
        payload,
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
