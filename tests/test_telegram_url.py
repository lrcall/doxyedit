"""TelegramBotClient._url + send_media_group dispatch — pin URL
construction and the single-image short-circuit. send_media_group
with one image must fall back to send_photo, not assemble a
multipart body."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestTelegramURL(unittest.TestCase):
    def test_method_url_format(self):
        from doxyedit.directpost import TelegramBotClient
        c = TelegramBotClient(bot_token="123:abc", chat_id="-100456")
        self.assertEqual(
            c._url("sendPhoto"),
            "https://api.telegram.org/bot123:abc/sendPhoto",
        )

    def test_url_uses_bot_prefix(self):
        from doxyedit.directpost import TelegramBotClient
        c = TelegramBotClient(bot_token="X", chat_id="Y")
        self.assertIn("/botX/", c._url("getMe"))


class TestMediaGroupDispatch(unittest.TestCase):
    def test_empty_image_list_falls_back_to_send_message(self):
        from doxyedit.directpost import TelegramBotClient
        c = TelegramBotClient(bot_token="t", chat_id="1")
        with patch.object(c, "send_message") as fake_msg, \
             patch.object(c, "send_photo") as fake_photo:
            from doxyedit.directpost import DirectPostResult
            fake_msg.return_value = DirectPostResult(success=True,
                                                       platform="telegram",
                                                       data={})
            c.send_media_group("hi", [])
            fake_msg.assert_called_once_with("hi")
            fake_photo.assert_not_called()

    def test_single_image_falls_back_to_send_photo(self):
        from doxyedit.directpost import TelegramBotClient, DirectPostResult
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        try:
            c = TelegramBotClient(bot_token="t", chat_id="1")
            with patch.object(c, "send_photo") as fake_photo, \
                 patch.object(c, "send_message") as fake_msg:
                fake_photo.return_value = DirectPostResult(
                    success=True, platform="telegram", data={})
                c.send_media_group("hi", [path])
                fake_photo.assert_called_once()
                fake_msg.assert_not_called()
        finally:
            Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
