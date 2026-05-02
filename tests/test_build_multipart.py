"""directpost._build_multipart — assembles multipart/form-data
bodies for Telegram / Discord uploads. Pin the boundary placement,
field encoding, and file attachment so a regression doesn't silently
corrupt every direct post upload."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestBuildMultipart(unittest.TestCase):
    def test_text_fields_only(self):
        from doxyedit.directpost import _build_multipart
        body, ct = _build_multipart({"a": "alpha", "b": "beta"})
        self.assertTrue(ct.startswith("multipart/form-data; boundary="))
        boundary = ct.split("boundary=", 1)[1]
        # Each field appears with its boundary delimiter.
        self.assertIn(f"--{boundary}".encode(), body)
        self.assertIn(b'name="a"', body)
        self.assertIn(b"alpha", body)
        self.assertIn(b'name="b"', body)
        self.assertIn(b"beta", body)
        # Closing boundary present.
        self.assertIn(f"--{boundary}--".encode(), body)

    def test_unicode_field_value(self):
        from doxyedit.directpost import _build_multipart
        body, _ = _build_multipart({"caption": "夢のキャラ"})
        # UTF-8 bytes for 夢 must be in the body.
        self.assertIn("夢のキャラ".encode("utf-8"), body)

    def test_file_attachment(self):
        from doxyedit.directpost import _build_multipart
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\nfake")
            path = f.name
        try:
            body, ct = _build_multipart({"chat_id": "1"},
                                         file_path=path,
                                         file_field="photo")
            # Form name + filename + raw bytes all present.
            self.assertIn(b'name="photo"', body)
            self.assertIn(Path(path).name.encode(), body)
            self.assertIn(b"\x89PNG", body)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_no_file_means_no_content_type_line(self):
        from doxyedit.directpost import _build_multipart
        body, _ = _build_multipart({"a": "1"})
        # Without a file, no embedded Content-Type header.
        self.assertNotIn(b"Content-Type: image/", body)

    def test_unique_boundary_per_call(self):
        """Each call should pick a fresh boundary so concurrent uploads
        don't collide."""
        from doxyedit.directpost import _build_multipart
        _, ct1 = _build_multipart({"a": "1"})
        _, ct2 = _build_multipart({"a": "1"})
        b1 = ct1.split("boundary=", 1)[1]
        b2 = ct2.split("boundary=", 1)[1]
        self.assertNotEqual(b1, b2)


if __name__ == "__main__":
    unittest.main()
