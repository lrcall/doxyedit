"""OneUpClient._url — URL builder. Pin the apiKey + category_id +
extra-params layout because every API call depends on it. A
regression posts to the wrong category or drops the api key
silently."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _qs(url):
    return parse_qs(urlparse(url).query)


class TestOneUpURLBuilder(unittest.TestCase):
    def test_api_key_always_present(self):
        from doxyedit.oneup import OneUpClient
        c = OneUpClient(api_key="K123")
        url = c._url("scheduletextpost")
        self.assertIn("apiKey=K123", url)

    def test_category_id_included_when_set(self):
        from doxyedit.oneup import OneUpClient
        c = OneUpClient(api_key="K", category_id="86698")
        url = c._url("scheduletextpost")
        self.assertEqual(_qs(url)["category_id"], ["86698"])

    def test_no_category_when_blank(self):
        from doxyedit.oneup import OneUpClient
        c = OneUpClient(api_key="K", category_id="")
        url = c._url("scheduletextpost")
        self.assertNotIn("category_id", _qs(url))

    def test_extra_params_appended(self):
        from doxyedit.oneup import OneUpClient
        c = OneUpClient(api_key="K")
        url = c._url("scheduleimagepost",
                     {"content": "hello world", "image_url": "u"})
        q = _qs(url)
        self.assertEqual(q["content"], ["hello world"])
        self.assertEqual(q["image_url"], ["u"])

    def test_special_chars_quoted(self):
        """Spaces and special chars in caption must be URL-encoded —
        OneUp's parser doesn't accept raw spaces/&/?/etc."""
        from doxyedit.oneup import OneUpClient
        c = OneUpClient(api_key="K")
        url = c._url("scheduletextpost", {"content": "hello & goodbye"})
        # Round-trip: parse_qs should give back the original string.
        self.assertEqual(_qs(url)["content"], ["hello & goodbye"])
        # And the raw URL should NOT contain a literal & inside content.
        # (The query separator & still appears; we want the encoded one
        # for the embedded ampersand.)
        self.assertIn("hello%20%26%20goodbye", url.replace("+", "%20"))

    def test_endpoint_in_path(self):
        from doxyedit.oneup import OneUpClient
        c = OneUpClient(api_key="K")
        url = c._url("scheduletextpost")
        self.assertIn("/scheduletextpost?", url)


if __name__ == "__main__":
    unittest.main()
