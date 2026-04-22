"""Direct-post clients — Telegram Bot API and Discord Webhooks.

Bypasses OneUp for platforms that support direct API posting.
Uses stdlib only (no requests library).
"""
from __future__ import annotations
import json
import mimetypes
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen


@dataclass
class DirectPostResult:
    """Outcome of a direct post attempt."""
    success: bool
    platform: str
    data: dict
    error: str = ""


# ---------------------------------------------------------------------------
# Multipart form-data builder (stdlib only)
# ---------------------------------------------------------------------------

def _build_multipart(
    fields: dict[str, str],
    file_path: str = "",
    file_field: str = "file",
) -> tuple[bytes, str]:
    """Build a multipart/form-data body from text fields + optional file.

    Args:
        fields: name -> value text fields.
        file_path: path to a binary file to attach (empty = no file).
        file_field: the form field name for the file attachment.

    Returns:
        (body_bytes, content_type_header_with_boundary)
    """
    boundary = uuid.uuid4().hex
    lines: list[bytes] = []

    for name, value in fields.items():
        lines.append(f"--{boundary}".encode())
        lines.append(
            f'Content-Disposition: form-data; name="{name}"'.encode()
        )
        lines.append(b"")
        lines.append(value.encode("utf-8"))

    if file_path:
        p = Path(file_path)
        mime = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        lines.append(f"--{boundary}".encode())
        lines.append(
            f'Content-Disposition: form-data; name="{file_field}"; '
            f'filename="{p.name}"'.encode()
        )
        lines.append(f"Content-Type: {mime}".encode())
        lines.append(b"")
        lines.append(p.read_bytes())

    lines.append(f"--{boundary}--".encode())
    lines.append(b"")

    body = b"\r\n".join(lines)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


# ---------------------------------------------------------------------------
# Telegram Bot API
# ---------------------------------------------------------------------------

class TelegramBotClient:
    """Post via Telegram Bot API. Requires a bot token and chat ID."""

    BASE = "https://api.telegram.org"

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id

    def _url(self, method: str) -> str:
        return f"{self.BASE}/bot{self.bot_token}/{method}"

    def send_photo(self, caption: str, image_path: str) -> DirectPostResult:
        """Send a photo with caption to the configured chat."""
        fields = {"chat_id": self.chat_id, "caption": caption}
        body, ct = _build_multipart(fields, file_path=image_path, file_field="photo")
        req = Request(self._url("sendPhoto"), data=body, headers={"Content-Type": ct}, method="POST")
        return self._execute(req)

    def send_message(self, text: str) -> DirectPostResult:
        """Send a text-only message to the configured chat."""
        payload = json.dumps({"chat_id": self.chat_id, "text": text}).encode("utf-8")
        req = Request(
            self._url("sendMessage"),
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._execute(req)

    def send_media_group(self, caption: str, image_paths: list[str]) -> DirectPostResult:
        """Send multiple photos as an album."""
        if len(image_paths) <= 1:
            return self.send_photo(caption, image_paths[0]) if image_paths else self.send_message(caption)

        boundary = uuid.uuid4().hex
        lines: list[bytes] = []

        media = []
        for i, path in enumerate(image_paths[:10]):
            media.append({
                "type": "photo",
                "media": f"attach://photo{i}",
                "caption": caption if i == 0 else "",
            })

        # Add media JSON field
        lines.append(f"--{boundary}".encode())
        lines.append(b'Content-Disposition: form-data; name="chat_id"')
        lines.append(b"")
        lines.append(self.chat_id.encode())

        lines.append(f"--{boundary}".encode())
        lines.append(b'Content-Disposition: form-data; name="media"')
        lines.append(b"Content-Type: application/json")
        lines.append(b"")
        lines.append(json.dumps(media).encode())

        # Add each photo file
        for i, path in enumerate(image_paths[:10]):
            p = Path(path)
            lines.append(f"--{boundary}".encode())
            lines.append(f'Content-Disposition: form-data; name="photo{i}"; filename="{p.name}"'.encode())
            lines.append(b"Content-Type: image/png")
            lines.append(b"")
            lines.append(p.read_bytes())

        lines.append(f"--{boundary}--".encode())
        lines.append(b"")

        body = b"\r\n".join(lines)
        ct = f"multipart/form-data; boundary={boundary}"
        req = Request(self._url("sendMediaGroup"), data=body, headers={"Content-Type": ct}, method="POST")
        return self._execute(req)

    def _execute(self, req: Request) -> DirectPostResult:
        try:
            with urlopen(req, timeout=30) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            if raw.get("ok"):
                print(f"[Telegram] OK  chat_id={self.chat_id}")
                return DirectPostResult(success=True, platform="telegram", data=raw)
            print(f"[Telegram] API error: {raw.get('description', raw)}")
            return DirectPostResult(
                success=False, platform="telegram", data=raw,
                error=raw.get("description", "Unknown Telegram error"),
            )
        except HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"[Telegram] HTTP {e.code}: {body}")
            return DirectPostResult(success=False, platform="telegram", data={}, error=f"HTTP {e.code}: {body}")
        except Exception as e:
            print(f"[Telegram] Exception: {e}")
            return DirectPostResult(success=False, platform="telegram", data={}, error=str(e))


# ---------------------------------------------------------------------------
# Discord Webhook
# ---------------------------------------------------------------------------

class DiscordWebhookClient:
    """Post via Discord webhook URL. Supports embeds + file attachment."""

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def send_message(
        self,
        content: str,
        image_path: str = "",
        embed_color: int = 0,
    ) -> DirectPostResult:
        """Send a message (with optional image and embed) to the webhook.

        Args:
            content: text body of the message.
            image_path: path to an image file to attach.
            embed_color: Discord embed sidebar color as an integer (0 = no embed).
        """
        # Build payload_json — Discord reads this alongside the file upload
        payload: dict = {"content": content}

        if embed_color and image_path:
            filename = Path(image_path).name
            payload["embeds"] = [
                {
                    "color": embed_color,
                    "image": {"url": f"attachment://{filename}"},
                }
            ]

        fields = {"payload_json": json.dumps(payload, ensure_ascii=False)}
        file = image_path if image_path else ""
        body, ct = _build_multipart(fields, file_path=file, file_field="file")

        req = Request(self.webhook_url, data=body, headers={"Content-Type": ct}, method="POST")
        return self._execute(req)

    def _execute(self, req: Request) -> DirectPostResult:
        try:
            with urlopen(req, timeout=30) as resp:
                raw_bytes = resp.read()
                # Discord returns 204 No Content on success for some webhook calls
                if not raw_bytes:
                    data: dict = {}
                else:
                    data = json.loads(raw_bytes.decode("utf-8"))
            print(f"[Discord] OK  webhook posted")
            return DirectPostResult(success=True, platform="discord", data=data)
        except HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"[Discord] HTTP {e.code}: {body}")
            return DirectPostResult(success=False, platform="discord", data={}, error=f"HTTP {e.code}: {body}")
        except Exception as e:
            print(f"[Discord] Exception: {e}")
            return DirectPostResult(success=False, platform="discord", data={}, error=str(e))


# ---------------------------------------------------------------------------
# Bluesky (AT Protocol)
# ---------------------------------------------------------------------------

class BlueskyClient:
    """Post via Bluesky AT Protocol. Requires handle + app password."""

    BASE = "https://bsky.social/xrpc"

    def __init__(self, handle: str, app_password: str) -> None:
        self.handle = handle
        self.app_password = app_password
        self._did: str = ""
        self._access_jwt: str = ""

    def _login(self) -> bool:
        """Create a session and get JWT token."""
        if self._access_jwt:
            return True
        payload = json.dumps({
            "identifier": self.handle,
            "password": self.app_password,
        }).encode("utf-8")
        req = Request(
            f"{self.BASE}/com.atproto.server.createSession",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            self._did = data.get("did", "")
            self._access_jwt = data.get("accessJwt", "")
            print(f"[Bluesky] Logged in as {self._did}")
            return True
        except Exception as e:
            print(f"[Bluesky] Login failed: {e}")
            return False

    def _upload_image(self, image_path: str) -> Optional[dict]:
        """Upload an image blob, return the blob reference."""
        p = Path(image_path)
        if not p.exists():
            return None
        mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
        data = p.read_bytes()
        req = Request(
            f"{self.BASE}/com.atproto.repo.uploadBlob",
            data=data,
            headers={
                "Content-Type": mime,
                "Authorization": f"Bearer {self._access_jwt}",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            return result.get("blob")
        except Exception as e:
            print(f"[Bluesky] Image upload failed: {e}")
            return None

    def send_post(self, text: str, image_path: str | list[str] = "") -> DirectPostResult:
        """Create a post on Bluesky with optional image(s)."""
        if not self._login():
            return DirectPostResult(
                success=False, platform="bluesky", data={},
                error="Login failed — check handle and app password",
            )

        # Build the post record
        record: dict = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }

        # Upload and attach image(s) if provided
        image_paths = image_path if isinstance(image_path, list) else ([image_path] if image_path else [])
        if image_paths:
            images = []
            for ip in image_paths:
                blob = self._upload_image(ip)
                if blob:
                    images.append({"alt": text[:100], "image": blob})
            if images:
                record["embed"] = {
                    "$type": "app.bsky.embed.images",
                    "images": images[:4],  # Bluesky max 4
                }

        payload = json.dumps({
            "repo": self._did,
            "collection": "app.bsky.feed.post",
            "record": record,
        }).encode("utf-8")

        req = Request(
            f"{self.BASE}/com.atproto.repo.createRecord",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._access_jwt}",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            print(f"[Bluesky] Posted: {data.get('uri', '')[:60]}")
            return DirectPostResult(success=True, platform="bluesky", data=data)
        except HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"[Bluesky] HTTP {e.code}: {body}")
            return DirectPostResult(success=False, platform="bluesky", data={}, error=f"HTTP {e.code}: {body}")
        except Exception as e:
            print(f"[Bluesky] Exception: {e}")
            return DirectPostResult(success=False, platform="bluesky", data={}, error=str(e))


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def get_direct_clients(project_dir: str) -> dict[str, list]:
    """Load all direct-post clients from config.yaml.

    Returns dict mapping platform name to list of client instances:
        {"telegram": [TelegramBotClient, ...], "discord": [DiscordWebhookClient, ...]}

    Config structure expected:
        telegram:
          bot_token: "..."
          channels:
            art: { label: "Art Updates", chat_id: "-100..." }
        discord_webhooks:
          art: { label: "Art Channel", webhook_url: "https://discord.com/api/webhooks/..." }
    """
    from doxyedit.oneup import _find_config
    config_path = _find_config(project_dir)
    clients: dict[str, list] = {"telegram": [], "discord": [], "bluesky": []}

    if not config_path.exists():
        return clients

    try:
        import yaml
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return clients

    # Telegram
    tg = config.get("telegram") or {}
    bot_token = tg.get("bot_token", "")
    if bot_token:
        channels = tg.get("channels") or {}
        for key, ch in channels.items():
            chat_id = str(ch.get("chat_id", ""))
            if chat_id:
                clients["telegram"].append(TelegramBotClient(bot_token, chat_id))
                label = ch.get("label", key)
                print(f"[Telegram] Loaded channel: {label} ({chat_id})")

    # Discord webhooks
    dw = config.get("discord_webhooks") or {}
    for key, wh in dw.items():
        url = wh.get("webhook_url", "")
        if url:
            clients["discord"].append(DiscordWebhookClient(url))
            label = wh.get("label", key)
            print(f"[Discord] Loaded webhook: {label}")

    # Bluesky
    bs = config.get("bluesky") or {}
    handle = bs.get("handle", "")
    app_pw = bs.get("app_password", "")
    if handle and app_pw:
        clients["bluesky"].append(BlueskyClient(handle, app_pw))
        print(f"[Bluesky] Loaded account: {handle}")

    return clients


# ---------------------------------------------------------------------------
# High-level dispatch
# ---------------------------------------------------------------------------

def _export_assets(post, project, max_images: int = 4, cache=None) -> list[str]:
    """Export assets from a SocialPost with censors + overlays.
    Returns list of temp file paths (up to max_images).

    Pass an ExportCache to reuse decoded images across consecutive calls.
    """
    paths = []
    for aid in post.asset_ids[:max_images]:
        asset = project.get_asset(aid)
        if not asset or not asset.source_path:
            continue
        try:
            from doxyedit.quickpost import _export_for_platform
            from doxyedit.models import SubPlatform
            stub = SubPlatform(id="direct", name="Direct", needs_censor=True)
            path = _export_for_platform(asset, stub, project, cache=cache)
            if path:
                paths.append(path)
        except Exception as e:
            print(f"[DirectPost] Export failed for {aid}: {e}")
    return paths


def push_to_direct(
    post,
    project,
    project_dir: str,
    cache=None,
) -> list[DirectPostResult]:
    """Send a SocialPost to all configured Telegram channels and Discord webhooks.

    Args:
        post: SocialPost instance.
        project: Project instance (for asset lookup).
        project_dir: directory containing config.yaml.

    Returns:
        List of DirectPostResult — one per channel/webhook attempted.
    """
    clients = get_direct_clients(project_dir)

    # Check identity for per-identity API credentials (Bluesky, Discord, Telegram)
    col = getattr(post, 'collection', '')
    identity_data = {}
    if col and project and hasattr(project, 'identities'):
        identity_data = project.identities.get(col, {})

    if not clients["bluesky"] and identity_data:
        handle = identity_data.get("bluesky_handle", "")
        app_pw = identity_data.get("bluesky_app_password", "")
        if handle and app_pw:
            clients["bluesky"].append(BlueskyClient(handle, app_pw))
            print(f"[Bluesky] Using identity credentials: {handle}")

    if not clients["discord"] and identity_data:
        webhook = identity_data.get("discord_webhook_url", "")
        if webhook:
            clients["discord"].append(DiscordWebhookClient(webhook))
            print(f"[Discord] Using identity webhook")

    if not clients["telegram"] and identity_data:
        bot_token = identity_data.get("telegram_bot_token", "")
        chat_id = identity_data.get("telegram_chat_id", "")
        if bot_token and chat_id:
            clients["telegram"].append(TelegramBotClient(bot_token, chat_id))
            print(f"[Telegram] Using identity credentials")

    results: list[DirectPostResult] = []

    # Skip platforms already posted
    already = getattr(post, "sub_platform_status", {}) or {}
    tg_done = already.get("telegram", {}).get("status") == "posted"
    dc_done = already.get("discord", {}).get("status") == "posted"
    bs_done = already.get("bluesky", {}).get("status") == "posted"

    has_tg = clients["telegram"] and not tg_done
    has_dc = clients["discord"] and not dc_done
    has_bs = clients["bluesky"] and not bs_done

    if not has_tg and not has_dc and not has_bs:
        return results

    # Export image only if we have something to send to
    image_paths = _export_assets(post, project, cache=cache)
    image_path = image_paths[0] if image_paths else ""

    # Telegram
    if has_tg:
        tg_caption = post.captions.get("telegram", post.caption_default)
        for tg in clients["telegram"]:
            if len(image_paths) > 1:
                r = tg.send_media_group(tg_caption, image_paths)
            elif image_path:
                r = tg.send_photo(tg_caption, image_path)
            else:
                r = tg.send_message(tg_caption)
            results.append(r)

    # Discord
    if has_dc:
        dc_caption = post.captions.get("discord", post.caption_default)
        for dc in clients["discord"]:
            r = dc.send_message(dc_caption, image_path=image_path)
            results.append(r)

    # Bluesky
    if has_bs:
        bs_caption = post.captions.get("bluesky", post.caption_default)
        for bs in clients["bluesky"]:
            r = bs.send_post(bs_caption, image_path=image_paths if len(image_paths) > 1 else image_path)
            results.append(r)

    return results
