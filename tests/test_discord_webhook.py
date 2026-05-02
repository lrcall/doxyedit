"""DiscordWebhookClient.send_message — assembles the payload_json
+ multipart body for Discord webhook posts. Pin the embed-only-with-
color+image rule and the payload structure so a regression doesn't
silently drop the image attachment or send the wrong content key."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class _CapturedRequest:
    """Helper: intercepts the Request urlopen sees so we can inspect
    the payload_json without making a network call."""

    def __init__(self):
        self.captured = None

    def __enter__(self):
        from doxyedit import directpost

        def fake_urlopen(req, timeout=None):
            # Save the request for inspection.
            self.captured = req
            # Mimic the urlopen context manager.
            mock_resp = MagicMock()
            mock_resp.read.return_value = b""
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = lambda *a: None
            return mock_resp

        self._patch = patch.object(directpost, "urlopen",
                                    side_effect=fake_urlopen)
        self._patch.start()
        # Silence print spam from the [Discord] OK lines.
        self._stdout_ctx = redirect_stdout(io.StringIO())
        self._stdout_ctx.__enter__()
        return self

    def __exit__(self, *args):
        self._stdout_ctx.__exit__(*args)
        self._patch.stop()


def _extract_payload_json(req) -> dict:
    """Pull the payload_json field out of a multipart body."""
    body = req.data
    # Find the payload_json section between boundaries.
    chunk = body.split(b'name="payload_json"', 1)[1]
    chunk = chunk.split(b"\r\n\r\n", 1)[1]
    chunk = chunk.split(b"\r\n--", 1)[0]
    return json.loads(chunk.decode("utf-8"))


class TestDiscordSendMessage(unittest.TestCase):
    def test_text_only_no_embed(self):
        from doxyedit.directpost import DiscordWebhookClient
        c = DiscordWebhookClient(webhook_url="https://discord/webhook")
        with _CapturedRequest() as cap:
            c.send_message("hello world")
        payload = _extract_payload_json(cap.captured)
        self.assertEqual(payload["content"], "hello world")
        self.assertNotIn("embeds", payload)

    def test_image_without_color_no_embed(self):
        """image_path alone (no embed_color) must not create an embed —
        the image still attaches but Discord renders it inline."""
        from doxyedit.directpost import DiscordWebhookClient
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"fake")
            img_path = f.name
        try:
            c = DiscordWebhookClient(webhook_url="https://x")
            with _CapturedRequest() as cap:
                c.send_message("hi", image_path=img_path, embed_color=0)
            payload = _extract_payload_json(cap.captured)
            self.assertNotIn("embeds", payload)
            # The file is still attached — body contains the image
            # form field name.
            self.assertIn(b'name="file"', cap.captured.data)
        finally:
            Path(img_path).unlink(missing_ok=True)

    def test_image_with_color_creates_embed(self):
        from doxyedit.directpost import DiscordWebhookClient
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"fake")
            img_path = f.name
        try:
            c = DiscordWebhookClient(webhook_url="https://x")
            with _CapturedRequest() as cap:
                c.send_message("hi", image_path=img_path,
                                embed_color=0xff0000)
            payload = _extract_payload_json(cap.captured)
            self.assertIn("embeds", payload)
            embed = payload["embeds"][0]
            self.assertEqual(embed["color"], 0xff0000)
            self.assertTrue(
                embed["image"]["url"].startswith("attachment://"))
        finally:
            Path(img_path).unlink(missing_ok=True)

    def test_unicode_content_survives(self):
        """ensure_ascii=False on payload_json — unicode body must round-trip."""
        from doxyedit.directpost import DiscordWebhookClient
        c = DiscordWebhookClient(webhook_url="https://x")
        with _CapturedRequest() as cap:
            c.send_message("夢の朝")
        payload = _extract_payload_json(cap.captured)
        self.assertEqual(payload["content"], "夢の朝")


if __name__ == "__main__":
    unittest.main()
