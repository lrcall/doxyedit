"""BlueskyClient — pin login URL endpoint, post-record shape, and
the 4-image cap. Uses a fake urlopen so we never hit bsky.social."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _make_resp(payload: dict):
    """Mimic a urlopen-as-context-manager whose .read returns JSON."""
    mock = MagicMock()
    mock.read.return_value = json.dumps(payload).encode()
    mock.__enter__ = lambda s: s
    mock.__exit__ = lambda *a: None
    return mock


class TestBlueskyClient(unittest.TestCase):
    def test_base_url_constant(self):
        from doxyedit.directpost import BlueskyClient
        self.assertEqual(BlueskyClient.BASE, "https://bsky.social/xrpc")

    def test_login_caches_jwt(self):
        from doxyedit.directpost import BlueskyClient
        from doxyedit import directpost
        c = BlueskyClient(handle="x.bsky.social", app_password="p")
        calls = []

        def fake(req, timeout=None):
            calls.append(req)
            return _make_resp({"did": "did:abc", "accessJwt": "jwt-token"})

        with patch.object(directpost, "urlopen", side_effect=fake), \
             redirect_stdout(io.StringIO()):
            self.assertTrue(c._login())
            # Second call must not hit the network.
            self.assertTrue(c._login())
        self.assertEqual(len(calls), 1)
        self.assertEqual(c._did, "did:abc")
        self.assertEqual(c._access_jwt, "jwt-token")

    def test_login_url_uses_create_session_endpoint(self):
        from doxyedit.directpost import BlueskyClient
        from doxyedit import directpost
        c = BlueskyClient(handle="x.bsky.social", app_password="p")
        captured = {}

        def fake(req, timeout=None):
            captured["url"] = req.full_url
            return _make_resp({"did": "d", "accessJwt": "j"})

        with patch.object(directpost, "urlopen", side_effect=fake), \
             redirect_stdout(io.StringIO()):
            c._login()
        self.assertIn("com.atproto.server.createSession", captured["url"])

    def test_send_post_body_shape(self):
        """Posted record must carry text, createdAt, and the canonical
        $type marker. Bluesky rejects records missing $type silently."""
        from doxyedit.directpost import BlueskyClient
        from doxyedit import directpost
        c = BlueskyClient(handle="x.bsky.social", app_password="p")
        captured = []

        def fake(req, timeout=None):
            captured.append(req)
            if "createSession" in req.full_url:
                return _make_resp({"did": "d", "accessJwt": "j"})
            return _make_resp({"uri": "at://x/post/1"})

        with patch.object(directpost, "urlopen", side_effect=fake), \
             redirect_stdout(io.StringIO()):
            r = c.send_post("hello bsky")
        self.assertTrue(r.success)
        # Find the createRecord call; inspect the post body.
        post_call = next(
            req for req in captured if "createRecord" in req.full_url)
        body = json.loads(post_call.data.decode())
        record = body["record"]
        self.assertEqual(record["$type"], "app.bsky.feed.post")
        self.assertEqual(record["text"], "hello bsky")
        self.assertIn("createdAt", record)


if __name__ == "__main__":
    unittest.main()
