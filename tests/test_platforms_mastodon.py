"""doxyedit/platforms/mastodon.py - stdlib Mastodon REST client. Pin
the statuses/media/favourite endpoint URLs, Bearer auth, JSON payload
shapes, the hand-rolled multipart body, the 4-image cap, credential
validation, and HTTPError / URLError -> MastodonError translation.
Uses a fake urllib.request.urlopen so we never hit a real instance."""
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

from doxyedit.platforms import mastodon
from doxyedit.platforms.mastodon import MastodonError


CREDS = {"instance": "mstdn.example", "access_token": "tok-abc"}


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


class TestParseStatusUrl(unittest.TestCase):
    def test_standard_status_url(self):
        self.assertEqual(
            mastodon.parse_status_url("https://mstdn.example/@alice/112233"),
            ("mstdn.example", "112233"))

    def test_http_scheme_accepted(self):
        self.assertEqual(
            mastodon.parse_status_url("http://mstdn.example/@bob/9"),
            ("mstdn.example", "9"))

    def test_trailing_path_ignored(self):
        self.assertEqual(
            mastodon.parse_status_url(
                "https://mstdn.example/@alice/112233/embed"),
            ("mstdn.example", "112233"))

    def test_non_status_url_raises(self):
        with self.assertRaises(MastodonError):
            mastodon.parse_status_url("https://mstdn.example/about")

    def test_non_numeric_id_raises(self):
        with self.assertRaises(MastodonError):
            mastodon.parse_status_url("https://mstdn.example/@alice/notanid")


class TestExtForMime(unittest.TestCase):
    def test_known_mimes(self):
        self.assertEqual(mastodon._ext_for_mime("image/png"), ".png")
        self.assertEqual(mastodon._ext_for_mime("image/jpeg"), ".jpg")
        self.assertEqual(mastodon._ext_for_mime("image/jpg"), ".jpg")
        self.assertEqual(mastodon._ext_for_mime("image/webp"), ".webp")
        self.assertEqual(mastodon._ext_for_mime("image/gif"), ".gif")

    def test_unknown_mime_empty(self):
        self.assertEqual(mastodon._ext_for_mime("image/tiff"), "")


class TestValidation(unittest.TestCase):
    """Credential / input guards that must reject before any HTTP.
    Each runs under a fail-on-network urlopen patch."""

    def test_post_reply_requires_token(self):
        with _no_network(), self.assertRaises(MastodonError):
            mastodon.post_reply({"instance": "mstdn.example"},
                                "https://mstdn.example/@a/1", "hi")

    def test_upload_media_requires_instance(self):
        with _no_network(), self.assertRaises(MastodonError):
            mastodon.upload_media({"access_token": "t"}, b"x", "image/png")

    def test_upload_media_requires_token(self):
        with _no_network(), self.assertRaises(MastodonError):
            mastodon.upload_media({"instance": "i"}, b"x", "image/png")

    def test_upload_media_empty_bytes(self):
        with _no_network(), self.assertRaises(MastodonError):
            mastodon.upload_media(CREDS, b"", "image/png")

    def test_upload_media_non_image_mime(self):
        with _no_network(), self.assertRaises(MastodonError):
            mastodon.upload_media(CREDS, b"x", "video/mp4")

    def test_create_post_requires_instance(self):
        with _no_network(), self.assertRaises(MastodonError):
            mastodon.create_post({"access_token": "t"}, "hi")

    def test_create_post_requires_token(self):
        with _no_network(), self.assertRaises(MastodonError):
            mastodon.create_post({"instance": "i"}, "hi")

    def test_create_post_empty_text(self):
        with _no_network(), self.assertRaises(MastodonError):
            mastodon.create_post(CREDS, "   ")

    def test_favourite_requires_token(self):
        with _no_network(), self.assertRaises(MastodonError):
            mastodon.favourite({"instance": "mstdn.example"},
                               "https://mstdn.example/@a/1")


class TestPostReply(unittest.TestCase):
    def test_endpoint_payload_and_auth(self):
        captured = {}

        def fake(req, timeout=None):
            captured["req"] = req
            return _make_resp({"id": "42", "uri": "tag:x", "url": "https://u",
                               "extra": "dropped"})

        with patch("urllib.request.urlopen", side_effect=fake):
            result = mastodon.post_reply(
                CREDS, "https://mstdn.example/@alice/112233", "nice art")

        req = captured["req"]
        self.assertEqual(req.full_url, "https://mstdn.example/api/v1/statuses")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(_headers(req)["authorization"], "Bearer tok-abc")
        self.assertEqual(_headers(req)["content-type"], "application/json")
        body = json.loads(req.data.decode())
        self.assertEqual(body, {"status": "nice art",
                                "in_reply_to_id": "112233",
                                "visibility": "public"})
        # Result trimmed to id/uri/url only.
        self.assertEqual(result, {"id": "42", "uri": "tag:x", "url": "https://u"})

    def test_instance_falls_back_to_parent_url_host(self):
        captured = {}

        def fake(req, timeout=None):
            captured["req"] = req
            return _make_resp({"id": "1", "uri": "u", "url": "w"})

        creds = {"access_token": "tok-abc"}  # no instance
        with patch("urllib.request.urlopen", side_effect=fake):
            mastodon.post_reply(
                creds, "https://other.instance/@bob/777", "hey")

        self.assertEqual(captured["req"].full_url,
                         "https://other.instance/api/v1/statuses")

    def test_empty_text_not_validated_locally(self):
        """BUG (pinned, documented): unlike create_post, post_reply has
        no local empty-text guard - an empty reply is sent to the server
        and only rejected remotely. Inconsistent validation contract
        within the same module. If a guard is added later, flip this to
        assertRaises(MastodonError) under _no_network()."""
        captured = {}

        def fake(req, timeout=None):
            captured["req"] = req
            return _make_resp({"id": "1", "uri": "u", "url": "w"})

        with patch("urllib.request.urlopen", side_effect=fake):
            mastodon.post_reply(
                CREDS, "https://mstdn.example/@alice/112233", "")

        body = json.loads(captured["req"].data.decode())
        self.assertEqual(body["status"], "")  # request went out anyway


class TestUploadMedia(unittest.TestCase):
    def _capture(self, description=""):
        captured = {}

        def fake(req, timeout=None):
            captured["req"] = req
            return _make_resp({"id": "m1"})

        with patch("urllib.request.urlopen", side_effect=fake):
            result = mastodon.upload_media(
                CREDS, b"\x89PNGDATA", "image/png", description=description)
        return captured["req"], result

    def test_endpoint_and_auth(self):
        req, result = self._capture()
        self.assertEqual(req.full_url, "https://mstdn.example/api/v2/media")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(_headers(req)["authorization"], "Bearer tok-abc")
        self.assertEqual(result, {"id": "m1"})

    def test_multipart_body_shape(self):
        req, _ = self._capture()
        ctype = _headers(req)["content-type"]
        self.assertTrue(ctype.startswith(
            "multipart/form-data; boundary=----doxyedit"))
        boundary = ctype.split("boundary=", 1)[1]
        body = req.data
        # Boundary from the header must frame the body.
        self.assertIn(f"--{boundary}\r\n".encode(), body)
        self.assertTrue(body.endswith(f"--{boundary}--\r\n".encode()))
        # File part: field name, filename with mime-derived extension,
        # part Content-Type, and the raw bytes.
        self.assertIn(b'Content-Disposition: form-data; name="file"; '
                      b'filename="image.png"\r\n', body)
        self.assertIn(b"Content-Type: image/png\r\n\r\n", body)
        self.assertIn(b"\x89PNGDATA", body)

    def test_description_field_included_when_given(self):
        req, _ = self._capture(description="alt text here")
        body = req.data
        self.assertIn(b'Content-Disposition: form-data; name="description"',
                      body)
        self.assertIn(b"alt text here", body)

    def test_description_field_omitted_when_empty(self):
        req, _ = self._capture(description="")
        self.assertNotIn(b'name="description"', req.data)


class TestCreatePost(unittest.TestCase):
    def test_text_only_payload(self):
        captured = {}

        def fake(req, timeout=None):
            captured["req"] = req
            return _make_resp({"id": "9", "uri": "u", "url": "w"})

        with patch("urllib.request.urlopen", side_effect=fake):
            result = mastodon.create_post(CREDS, "hello fediverse")

        req = captured["req"]
        self.assertEqual(req.full_url, "https://mstdn.example/api/v1/statuses")
        body = json.loads(req.data.decode())
        self.assertEqual(body, {"status": "hello fediverse",
                                "visibility": "public"})
        self.assertEqual(result, {"id": "9", "uri": "u", "url": "w"})

    def test_images_uploaded_then_attached_capped_at_four(self):
        captured = []
        media_n = [0]

        def fake(req, timeout=None):
            captured.append(req)
            if "/api/v2/media" in req.full_url:
                media_n[0] += 1
                return _make_resp({"id": f"m{media_n[0]}"})
            return _make_resp({"id": "9", "uri": "u", "url": "w"})

        images = [(b"img%d" % i, "image/png", f"alt {i}") for i in range(5)]
        with patch("urllib.request.urlopen", side_effect=fake):
            mastodon.create_post(CREDS, "with pics", images=images)

        uploads = [r for r in captured if "/api/v2/media" in r.full_url]
        self.assertEqual(len(uploads), 4)  # 5th image silently dropped
        # Alt text flows into the multipart description field.
        self.assertIn(b'name="description"', uploads[0].data)
        self.assertIn(b"alt 0", uploads[0].data)
        status = next(r for r in captured
                      if r.full_url.endswith("/api/v1/statuses"))
        body = json.loads(status.data.decode())
        self.assertEqual(body["media_ids"], ["m1", "m2", "m3", "m4"])

    def test_media_without_id_is_skipped(self):
        captured = []

        def fake(req, timeout=None):
            captured.append(req)
            if "/api/v2/media" in req.full_url:
                return _make_resp({})  # no id -> not attached
            return _make_resp({"id": "9", "uri": "u", "url": "w"})

        with patch("urllib.request.urlopen", side_effect=fake):
            mastodon.create_post(CREDS, "pic", images=[(b"img", "image/png")])

        status = next(r for r in captured
                      if r.full_url.endswith("/api/v1/statuses"))
        body = json.loads(status.data.decode())
        self.assertNotIn("media_ids", body)


class TestFavourite(unittest.TestCase):
    def test_endpoint_and_empty_body(self):
        captured = {}

        def fake(req, timeout=None):
            captured["req"] = req
            return _make_resp({"id": "112233", "favourited": True})

        with patch("urllib.request.urlopen", side_effect=fake):
            mastodon.favourite(CREDS, "https://mstdn.example/@alice/112233")

        req = captured["req"]
        self.assertEqual(
            req.full_url,
            "https://mstdn.example/api/v1/statuses/112233/favourite")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(_headers(req)["authorization"], "Bearer tok-abc")
        self.assertEqual(json.loads(req.data.decode()), {})

    def test_instance_falls_back_to_status_url_host(self):
        captured = {}

        def fake(req, timeout=None):
            captured["req"] = req
            return _make_resp({"id": "5"})

        with patch("urllib.request.urlopen", side_effect=fake):
            mastodon.favourite({"access_token": "tok-abc"},
                               "https://other.host/@x/5")

        self.assertEqual(captured["req"].full_url,
                         "https://other.host/api/v1/statuses/5/favourite")


class TestErrorTranslation(unittest.TestCase):
    def test_http_error_with_json_error_field(self):
        err = _http_error(422, "Unprocessable Entity", json.dumps(
            {"error": "Text limit exceeded"}).encode())
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(MastodonError) as ctx:
                mastodon.create_post(CREDS, "hi")
        msg = str(ctx.exception)
        self.assertIn("HTTP 422", msg)
        self.assertIn("Text limit exceeded", msg)

    def test_http_error_with_non_json_body(self):
        err = _http_error(502, "Bad Gateway", b"<html>nope</html>")
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(MastodonError) as ctx:
                mastodon.create_post(CREDS, "hi")
        self.assertIn("HTTP 502", str(ctx.exception))
        self.assertIn("Bad Gateway", str(ctx.exception))

    def test_url_error_becomes_network_error(self):
        err = urllib.error.URLError("timed out")
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(MastodonError) as ctx:
                mastodon.create_post(CREDS, "hi")
        self.assertIn("network error", str(ctx.exception))
        self.assertIn("timed out", str(ctx.exception))

    def test_multipart_http_error_translated(self):
        # _request_multipart has its own copy of the error translation.
        err = _http_error(413, "Payload Too Large", json.dumps(
            {"error": "File too big"}).encode())
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(MastodonError) as ctx:
                mastodon.upload_media(CREDS, b"data", "image/png")
        msg = str(ctx.exception)
        self.assertIn("HTTP 413", msg)
        self.assertIn("File too big", msg)

    def test_multipart_url_error_translated(self):
        err = urllib.error.URLError("refused")
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(MastodonError) as ctx:
                mastodon.upload_media(CREDS, b"data", "image/png")
        self.assertIn("network error", str(ctx.exception))

    def test_http_error_json_body_without_error_key_uses_reason(self):
        # JSON body but no "error" field -> falls back to the HTTP reason.
        err = _http_error(403, "Forbidden", json.dumps({"detail": "x"}).encode())
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(MastodonError) as ctx:
                mastodon.create_post(CREDS, "hi")
        self.assertEqual(str(ctx.exception), "HTTP 403: Forbidden")

    def test_malformed_success_body_escapes_error_contract(self):
        """BUG (pinned, documented): a 2xx response whose body is not
        JSON escapes _request_json as a raw json.JSONDecodeError instead
        of being wrapped in MastodonError. Callers that catch only
        MastodonError (bridge.py reply posting) will NOT catch this.
        If the module is later fixed to wrap decode failures, flip this
        to assertRaises(MastodonError)."""
        def fake(req, timeout=None):
            mock = MagicMock()
            mock.read.return_value = b"<html>not json</html>"
            mock.__enter__ = lambda s: s
            mock.__exit__ = lambda *a: None
            return mock

        with patch("urllib.request.urlopen", side_effect=fake):
            with self.assertRaises(json.JSONDecodeError):
                mastodon.create_post(CREDS, "hi")

    def test_malformed_success_body_escapes_multipart_path_too(self):
        """BUG (pinned): same json.JSONDecodeError leak in
        _request_multipart (upload_media path)."""
        def fake(req, timeout=None):
            mock = MagicMock()
            mock.read.return_value = b"not json"
            mock.__enter__ = lambda s: s
            mock.__exit__ = lambda *a: None
            return mock

        with patch("urllib.request.urlopen", side_effect=fake):
            with self.assertRaises(json.JSONDecodeError):
                mastodon.upload_media(CREDS, b"data", "image/png")


if __name__ == "__main__":
    unittest.main()
