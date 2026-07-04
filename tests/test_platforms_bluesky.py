"""doxyedit/platforms/bluesky.py - stdlib ATProto client. Pin the
endpoint URLs, auth headers, createRecord payload shapes, the reply
thread-root inheritance rule, the 300-char / 4-image caps, and the
HTTPError / URLError -> BlueskyError translation. Uses a fake
urllib.request.urlopen so we never hit bsky.social.

NOT the same module as doxyedit.directpost.BlueskyClient (covered by
tests/test_bluesky_client.py) - this file covers the module-level
function client used by bridge.py reply posting."""
from __future__ import annotations

import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from doxyedit.platforms import bluesky
from doxyedit.platforms.bluesky import BlueskyError


SESSION = {"did": "did:plc:me", "accessJwt": "jwt-123"}


def _make_resp(payload: dict):
    """Mimic a urlopen-as-context-manager whose .read returns JSON."""
    mock = MagicMock()
    mock.read.return_value = json.dumps(payload).encode()
    mock.__enter__ = lambda s: s
    mock.__exit__ = lambda *a: None
    return mock


def _headers(req) -> dict:
    """Case-insensitive view of a Request's headers."""
    return {k.lower(): v for k, v in req.header_items()}


def _http_error(code: int, reason: str, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", code, reason, {}, io.BytesIO(body))


def _no_network():
    """urlopen replacement that fails the test if any request is made.
    Used around validation guards so a regressed guard surfaces as an
    assertion instead of a real network call."""
    return patch("urllib.request.urlopen",
                 side_effect=AssertionError("unexpected network call"))


class TestParsePostUrl(unittest.TestCase):
    def test_handle_url(self):
        self.assertEqual(
            bluesky.parse_post_url(
                "https://bsky.app/profile/alice.bsky.social/post/3kabc"),
            ("alice.bsky.social", "3kabc"))

    def test_did_url(self):
        self.assertEqual(
            bluesky.parse_post_url(
                "https://bsky.app/profile/did:plc:xyz/post/3kdef"),
            ("did:plc:xyz", "3kdef"))

    def test_query_and_fragment_stripped_from_rkey(self):
        self.assertEqual(
            bluesky.parse_post_url(
                "https://bsky.app/profile/a.b/post/3k?ref=1#top"),
            ("a.b", "3k"))

    def test_http_scheme_accepted(self):
        self.assertEqual(
            bluesky.parse_post_url("http://bsky.app/profile/a.b/post/rk"),
            ("a.b", "rk"))

    def test_non_bluesky_url_raises(self):
        with self.assertRaises(BlueskyError):
            bluesky.parse_post_url("https://twitter.com/x/status/1")

    def test_profile_url_without_post_raises(self):
        with self.assertRaises(BlueskyError):
            bluesky.parse_post_url("https://bsky.app/profile/alice.bsky.social")


class TestPostUrlFor(unittest.TestCase):
    def test_builds_url_from_uri_rkey_and_session_did(self):
        resp = {"uri": "at://did:plc:me/app.bsky.feed.post/3kfoo", "cid": "c"}
        self.assertEqual(
            bluesky.post_url_for(SESSION, resp),
            "https://bsky.app/profile/did:plc:me/post/3kfoo")

    def test_missing_uri_gives_empty_rkey(self):
        self.assertEqual(
            bluesky.post_url_for(SESSION, {}),
            "https://bsky.app/profile/did:plc:me/post/")


class TestValidation(unittest.TestCase):
    """Guards that must reject before any network call is attempted.
    Each runs under a fail-on-network urlopen patch."""

    def test_post_reply_empty_text(self):
        with _no_network(), self.assertRaises(BlueskyError):
            bluesky.post_reply(SESSION, "https://bsky.app/profile/a.b/post/r", "   ")

    def test_post_reply_over_300_chars(self):
        with _no_network(), self.assertRaises(BlueskyError) as ctx:
            bluesky.post_reply(
                SESSION, "https://bsky.app/profile/a.b/post/r", "x" * 301)
        self.assertIn("300", str(ctx.exception))

    def test_create_post_empty_text(self):
        with _no_network(), self.assertRaises(BlueskyError):
            bluesky.create_post(SESSION, "")

    def test_create_post_over_300_chars(self):
        with _no_network(), self.assertRaises(BlueskyError):
            bluesky.create_post(SESSION, "y" * 301)

    def test_upload_blob_empty_bytes(self):
        with _no_network(), self.assertRaises(BlueskyError):
            bluesky.upload_blob(SESSION, b"", "image/png")

    def test_upload_blob_non_image_mime(self):
        with _no_network(), self.assertRaises(BlueskyError):
            bluesky.upload_blob(SESSION, b"data", "video/mp4")

    def test_upload_blob_empty_mime(self):
        with _no_network(), self.assertRaises(BlueskyError):
            bluesky.upload_blob(SESSION, b"data", "")


class TestCreateSession(unittest.TestCase):
    def test_endpoint_method_and_body(self):
        captured = {}

        def fake(req, timeout=None):
            captured["req"] = req
            return _make_resp({"did": "did:plc:me", "accessJwt": "jwt-123"})

        with patch("urllib.request.urlopen", side_effect=fake):
            session = bluesky.create_session("alice.bsky.social", "app-pass")

        req = captured["req"]
        self.assertEqual(
            req.full_url,
            "https://bsky.social/xrpc/com.atproto.server.createSession")
        self.assertEqual(req.get_method(), "POST")
        body = json.loads(req.data.decode())
        self.assertEqual(body, {"identifier": "alice.bsky.social",
                                "password": "app-pass"})
        self.assertEqual(_headers(req)["content-type"], "application/json")
        # Login itself carries no auth header.
        self.assertNotIn("authorization", _headers(req))
        self.assertEqual(session["accessJwt"], "jwt-123")


class TestResolveHandle(unittest.TestCase):
    def test_uses_public_appview_get_no_auth(self):
        captured = {}

        def fake(req, timeout=None):
            captured["req"] = req
            return _make_resp({"did": "did:plc:resolved"})

        with patch("urllib.request.urlopen", side_effect=fake):
            did = bluesky.resolve_handle("foo.bsky.social")

        req = captured["req"]
        self.assertEqual(
            req.full_url,
            "https://public.api.bsky.app/xrpc/com.atproto.identity."
            "resolveHandle?handle=foo.bsky.social")
        self.assertEqual(req.get_method(), "GET")
        self.assertIsNone(req.data)
        self.assertNotIn("authorization", _headers(req))
        self.assertEqual(did, "did:plc:resolved")


class TestGetPostRecord(unittest.TestCase):
    def test_url_params_and_auth_header(self):
        captured = {}

        def fake(req, timeout=None):
            captured["req"] = req
            return _make_resp({"uri": "at://u", "cid": "c", "value": {}})

        with patch("urllib.request.urlopen", side_effect=fake):
            rec = bluesky.get_post_record(SESSION, "did:plc:author", "3krk")

        req = captured["req"]
        self.assertIn("com.atproto.repo.getRecord", req.full_url)
        self.assertIn("repo=did:plc:author", req.full_url)
        self.assertIn("collection=app.bsky.feed.post", req.full_url)
        self.assertIn("rkey=3krk", req.full_url)
        self.assertEqual(_headers(req)["authorization"], "Bearer jwt-123")
        self.assertEqual(rec["uri"], "at://u")


class TestPostReply(unittest.TestCase):
    PARENT_URI = "at://did:plc:author/app.bsky.feed.post/3kparent"

    def _run(self, parent_url: str, parent_value: dict):
        """Drive post_reply through resolve/getRecord/createRecord and
        return the list of captured Requests."""
        captured = []

        def fake(req, timeout=None):
            captured.append(req)
            url = req.full_url
            if "resolveHandle" in url:
                return _make_resp({"did": "did:plc:author"})
            if "getRecord" in url:
                return _make_resp({"uri": self.PARENT_URI,
                                   "cid": "cid-parent",
                                   "value": parent_value})
            if "createRecord" in url:
                return _make_resp({"uri": "at://did:plc:me/app.bsky.feed.post/3knew",
                                   "cid": "cid-new"})
            raise AssertionError(f"unexpected url {url}")

        with patch("urllib.request.urlopen", side_effect=fake):
            result = bluesky.post_reply(SESSION, parent_url, "hi there")
        return captured, result

    def test_handle_is_resolved_then_record_created(self):
        captured, result = self._run(
            "https://bsky.app/profile/author.bsky.social/post/3kparent", {})
        urls = [r.full_url for r in captured]
        self.assertTrue(any("resolveHandle" in u for u in urls))
        self.assertTrue(any("getRecord" in u for u in urls))
        create = next(r for r in captured if "createRecord" in r.full_url)
        self.assertEqual(create.get_method(), "POST")
        self.assertEqual(_headers(create)["authorization"], "Bearer jwt-123")
        body = json.loads(create.data.decode())
        self.assertEqual(body["repo"], "did:plc:me")
        self.assertEqual(body["collection"], "app.bsky.feed.post")
        record = body["record"]
        self.assertEqual(record["$type"], "app.bsky.feed.post")
        self.assertEqual(record["text"], "hi there")
        self.assertTrue(record["createdAt"].endswith("Z"))
        self.assertEqual(result["cid"], "cid-new")

    def test_did_in_url_skips_resolve_handle(self):
        captured, _ = self._run(
            "https://bsky.app/profile/did:plc:author/post/3kparent", {})
        urls = [r.full_url for r in captured]
        self.assertFalse(any("resolveHandle" in u for u in urls))

    def test_non_reply_parent_is_thread_root(self):
        captured, _ = self._run(
            "https://bsky.app/profile/did:plc:author/post/3kparent", {})
        create = next(r for r in captured if "createRecord" in r.full_url)
        reply = json.loads(create.data.decode())["record"]["reply"]
        self.assertEqual(reply["parent"],
                         {"uri": self.PARENT_URI, "cid": "cid-parent"})
        self.assertEqual(reply["root"],
                         {"uri": self.PARENT_URI, "cid": "cid-parent"})

    def test_reply_parent_inherits_its_root(self):
        parent_value = {"reply": {"root": {"uri": "at://root-uri",
                                           "cid": "cid-root"}}}
        captured, _ = self._run(
            "https://bsky.app/profile/did:plc:author/post/3kparent",
            parent_value)
        create = next(r for r in captured if "createRecord" in r.full_url)
        reply = json.loads(create.data.decode())["record"]["reply"]
        self.assertEqual(reply["root"],
                         {"uri": "at://root-uri", "cid": "cid-root"})
        self.assertEqual(reply["parent"],
                         {"uri": self.PARENT_URI, "cid": "cid-parent"})

    def test_malformed_root_falls_back_to_parent(self):
        # root present but missing cid -> parent is used as root.
        parent_value = {"reply": {"root": {"uri": "at://root-uri"}}}
        captured, _ = self._run(
            "https://bsky.app/profile/did:plc:author/post/3kparent",
            parent_value)
        create = next(r for r in captured if "createRecord" in r.full_url)
        reply = json.loads(create.data.decode())["record"]["reply"]
        self.assertEqual(reply["root"],
                         {"uri": self.PARENT_URI, "cid": "cid-parent"})


class TestUploadBlob(unittest.TestCase):
    def test_raw_body_mime_auth_and_blob_return(self):
        captured = {}
        blob = {"$type": "blob", "ref": {"$link": "abc"},
                "mimeType": "image/png", "size": 4}

        def fake(req, timeout=None):
            captured["req"] = req
            return _make_resp({"blob": blob})

        with patch("urllib.request.urlopen", side_effect=fake):
            result = bluesky.upload_blob(SESSION, b"\x89PNG", "image/png")

        req = captured["req"]
        self.assertEqual(
            req.full_url, "https://bsky.social/xrpc/com.atproto.repo.uploadBlob")
        self.assertEqual(req.get_method(), "POST")
        # Body is the raw image bytes, not a JSON envelope.
        self.assertEqual(req.data, b"\x89PNG")
        self.assertEqual(_headers(req)["content-type"], "image/png")
        self.assertEqual(_headers(req)["authorization"], "Bearer jwt-123")
        self.assertEqual(result, blob)


class TestCreatePost(unittest.TestCase):
    def test_exactly_300_chars_allowed(self):
        """The cap is > 300, not >= 300 - a 300-char post must go out."""
        sent = []

        def fake(req, timeout=None):
            sent.append(req)
            return _make_resp({"uri": "at://x/app.bsky.feed.post/3k",
                               "cid": "c"})

        with patch("urllib.request.urlopen", side_effect=fake):
            bluesky.create_post(SESSION, "x" * 300)
        self.assertEqual(len(sent), 1)

    def test_text_only_no_embed(self):
        captured = {}

        def fake(req, timeout=None):
            captured["req"] = req
            return _make_resp({"uri": "at://did:plc:me/app.bsky.feed.post/3k",
                               "cid": "c"})

        with patch("urllib.request.urlopen", side_effect=fake):
            bluesky.create_post(SESSION, "hello world")

        body = json.loads(captured["req"].data.decode())
        self.assertEqual(body["record"]["text"], "hello world")
        self.assertNotIn("embed", body["record"])

    def test_images_embedded_and_capped_at_four(self):
        captured = []
        blob_n = [0]

        def fake(req, timeout=None):
            captured.append(req)
            if "uploadBlob" in req.full_url:
                blob_n[0] += 1
                return _make_resp({"blob": {"ref": {"$link": f"b{blob_n[0]}"}}})
            return _make_resp({"uri": "at://x/app.bsky.feed.post/3k", "cid": "c"})

        images = [(b"img%d" % i, "image/png", f"alt {i}") for i in range(5)]
        with patch("urllib.request.urlopen", side_effect=fake):
            bluesky.create_post(SESSION, "with pics", images=images)

        uploads = [r for r in captured if "uploadBlob" in r.full_url]
        self.assertEqual(len(uploads), 4)  # 5th image silently dropped
        create = next(r for r in captured if "createRecord" in r.full_url)
        embed = json.loads(create.data.decode())["record"]["embed"]
        self.assertEqual(embed["$type"], "app.bsky.embed.images")
        self.assertEqual(len(embed["images"]), 4)
        self.assertEqual(embed["images"][0]["alt"], "alt 0")
        self.assertEqual(embed["images"][0]["image"],
                         {"ref": {"$link": "b1"}})

    def test_two_tuple_image_defaults_alt_to_empty(self):
        captured = []

        def fake(req, timeout=None):
            captured.append(req)
            if "uploadBlob" in req.full_url:
                return _make_resp({"blob": {"ref": {"$link": "b1"}}})
            return _make_resp({"uri": "at://x/app.bsky.feed.post/3k", "cid": "c"})

        with patch("urllib.request.urlopen", side_effect=fake):
            bluesky.create_post(SESSION, "pic", images=[(b"img", "image/jpeg")])

        create = next(r for r in captured if "createRecord" in r.full_url)
        embed = json.loads(create.data.decode())["record"]["embed"]
        self.assertEqual(embed["images"][0]["alt"], "")


class TestLikePost(unittest.TestCase):
    def test_like_record_shape(self):
        captured = []

        def fake(req, timeout=None):
            captured.append(req)
            url = req.full_url
            if "getRecord" in url:
                return _make_resp({"uri": "at://parent-uri", "cid": "cid-p",
                                   "value": {}})
            if "createRecord" in url:
                return _make_resp({"uri": "at://like-uri", "cid": "cid-l"})
            raise AssertionError(f"unexpected url {url}")

        with patch("urllib.request.urlopen", side_effect=fake):
            bluesky.like_post(
                SESSION, "https://bsky.app/profile/did:plc:author/post/3k")

        create = next(r for r in captured if "createRecord" in r.full_url)
        body = json.loads(create.data.decode())
        self.assertEqual(body["collection"], "app.bsky.feed.like")
        record = body["record"]
        self.assertEqual(record["$type"], "app.bsky.feed.like")
        self.assertEqual(record["subject"],
                         {"uri": "at://parent-uri", "cid": "cid-p"})
        self.assertTrue(record["createdAt"].endswith("Z"))


class TestErrorTranslation(unittest.TestCase):
    def test_http_error_with_json_body(self):
        err = _http_error(400, "Bad Request", json.dumps(
            {"error": "InvalidRequest", "message": "boom"}).encode())
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(BlueskyError) as ctx:
                bluesky.create_session("h", "p")
        msg = str(ctx.exception)
        self.assertIn("HTTP 400", msg)
        self.assertIn("InvalidRequest", msg)
        self.assertIn("boom", msg)

    def test_http_error_with_non_json_body(self):
        err = _http_error(500, "Server Error", b"<html>oops</html>")
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(BlueskyError) as ctx:
                bluesky.create_session("h", "p")
        self.assertIn("HTTP 500", str(ctx.exception))
        self.assertIn("Server Error", str(ctx.exception))

    def test_url_error_becomes_network_error(self):
        err = urllib.error.URLError("connection refused")
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(BlueskyError) as ctx:
                bluesky.resolve_handle("foo.bsky.social")
        self.assertIn("network error", str(ctx.exception))
        self.assertIn("connection refused", str(ctx.exception))

    def test_upload_blob_http_error_via_raw_path(self):
        # _request_raw has its own copy of the error translation.
        err = _http_error(413, "Payload Too Large", json.dumps(
            {"error": "BlobTooLarge", "message": "too big"}).encode())
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(BlueskyError) as ctx:
                bluesky.upload_blob(SESSION, b"data", "image/png")
        msg = str(ctx.exception)
        self.assertIn("HTTP 413", msg)
        self.assertIn("BlobTooLarge", msg)

    def test_upload_blob_url_error_via_raw_path(self):
        err = urllib.error.URLError("conn reset")
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(BlueskyError) as ctx:
                bluesky.upload_blob(SESSION, b"data", "image/png")
        self.assertIn("network error", str(ctx.exception))

    def test_malformed_success_body_escapes_error_contract(self):
        """BUG (pinned, documented): a 2xx response whose body is not
        JSON escapes _request_json as a raw json.JSONDecodeError instead
        of being wrapped in BlueskyError. Callers that catch only
        BlueskyError (bridge.py reply posting) will NOT catch this.
        If the module is later fixed to wrap decode failures, flip this
        to assertRaises(BlueskyError)."""
        def fake(req, timeout=None):
            mock = MagicMock()
            mock.read.return_value = b"<html>not json</html>"
            mock.__enter__ = lambda s: s
            mock.__exit__ = lambda *a: None
            return mock

        with patch("urllib.request.urlopen", side_effect=fake):
            with self.assertRaises(json.JSONDecodeError):
                bluesky.create_session("h", "p")

    def test_malformed_success_body_escapes_raw_path_too(self):
        """BUG (pinned): same json.JSONDecodeError leak in _request_raw
        (upload_blob path)."""
        def fake(req, timeout=None):
            mock = MagicMock()
            mock.read.return_value = b"not json"
            mock.__enter__ = lambda s: s
            mock.__exit__ = lambda *a: None
            return mock

        with patch("urllib.request.urlopen", side_effect=fake):
            with self.assertRaises(json.JSONDecodeError):
                bluesky.upload_blob(SESSION, b"data", "image/png")


if __name__ == "__main__":
    unittest.main()
