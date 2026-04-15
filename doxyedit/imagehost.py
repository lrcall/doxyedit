"""imagehost.py — Upload images to get public URLs for social media posting.

Supports Imgur (anonymous) and imgbb. Uses stdlib urllib only.
"""
from __future__ import annotations
import base64
import json
import hashlib
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError


@dataclass
class UploadResult:
    success: bool = False
    url: str = ""
    delete_hash: str = ""
    error: str = ""


# Module-level cache: file_hash -> url (avoids re-uploading same image)
_upload_cache: dict[str, str] = {}


def _file_hash(path: str) -> str:
    """Quick hash of file for cache key."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def upload_to_imgur(image_path: str, client_id: str = "") -> UploadResult:
    """Upload image to Imgur anonymously.

    Args:
        image_path: path to PNG/JPG file
        client_id: Imgur API client ID (register at https://api.imgur.com)
                   If empty, uses anonymous upload (rate limited)
    """
    if not client_id:
        client_id = "546c25a59c58ad7"  # DoxyEdit default (anonymous, rate limited)

    fhash = _file_hash(image_path)
    if fhash in _upload_cache:
        return UploadResult(success=True, url=_upload_cache[fhash])

    try:
        img_data = base64.b64encode(Path(image_path).read_bytes()).decode("utf-8")
        payload = json.dumps({"image": img_data, "type": "base64"}).encode("utf-8")

        req = Request(
            "https://api.imgur.com/3/image",
            data=payload,
            headers={
                "Authorization": f"Client-ID {client_id}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if data.get("success"):
            url = data["data"]["link"]
            delete_hash = data["data"].get("deletehash", "")
            _upload_cache[fhash] = url
            print(f"[Imgur] Uploaded: {url}")
            return UploadResult(success=True, url=url, delete_hash=delete_hash)
        return UploadResult(error=data.get("data", {}).get("error", "Unknown error"))

    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return UploadResult(error=f"HTTP {e.code}: {body[:100]}")
    except Exception as e:
        return UploadResult(error=str(e))


def upload_to_imgbb(image_path: str, api_key: str) -> UploadResult:
    """Upload image to imgbb.

    Get API key from https://api.imgbb.com/
    """
    fhash = _file_hash(image_path)
    if fhash in _upload_cache:
        return UploadResult(success=True, url=_upload_cache[fhash])

    try:
        img_data = base64.b64encode(Path(image_path).read_bytes()).decode("utf-8")

        from urllib.parse import urlencode
        payload = urlencode({"key": api_key, "image": img_data}).encode("utf-8")

        req = Request(
            "https://api.imgbb.com/1/upload",
            data=payload,
            method="POST",
        )
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if data.get("success"):
            url = data["data"]["url"]
            _upload_cache[fhash] = url
            print(f"[imgbb] Uploaded: {url}")
            return UploadResult(success=True, url=url)
        return UploadResult(error=data.get("error", {}).get("message", "Unknown error"))

    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return UploadResult(error=f"HTTP {e.code}: {body[:100]}")
    except Exception as e:
        return UploadResult(error=str(e))


def upload_image(image_path: str, project_dir: str = ".") -> UploadResult:
    """Upload an image using the configured provider.

    Reads config.yaml for provider + credentials:
        image_hosting:
            provider: "imgur"  # or "imgbb"
            imgur_client_id: "..."
            imgbb_api_key: "..."
    """
    from doxyedit.oneup import _find_config
    config_path = _find_config(project_dir)

    provider = "imgur"
    imgur_id = ""
    imgbb_key = ""

    if config_path.exists():
        try:
            import yaml
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            hosting = config.get("image_hosting", {})
            provider = hosting.get("provider", "imgur")
            imgur_id = hosting.get("imgur_client_id", "")
            imgbb_key = hosting.get("imgbb_api_key", "")
        except Exception:
            pass

    if provider == "imgbb" and imgbb_key:
        return upload_to_imgbb(image_path, imgbb_key)
    return upload_to_imgur(image_path, imgur_id)
