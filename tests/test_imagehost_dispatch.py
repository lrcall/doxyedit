"""imagehost.upload_image — config-driven provider dispatch +
cache-hit short-circuit. Tests use a tempdir-backed config.yaml and
mock the provider functions so we never hit the network."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _make_config(td: Path, content: str) -> Path:
    cfg = td / "config.yaml"
    cfg.write_text(content, encoding="utf-8")
    return cfg


class TestUploadImageDispatch(unittest.TestCase):
    def test_default_provider_is_imgur(self):
        from doxyedit import imagehost
        with tempfile.TemporaryDirectory() as td:
            tmp_img = Path(td) / "x.png"
            tmp_img.write_bytes(b"fake")
            with patch.object(imagehost, "upload_to_imgur") as fake_imgur, \
                 patch.object(imagehost, "upload_to_imgbb") as fake_imgbb:
                fake_imgur.return_value = imagehost.UploadResult(
                    success=True, url="x")
                imagehost.upload_image(str(tmp_img), project_dir=td)
                fake_imgur.assert_called_once()
                fake_imgbb.assert_not_called()

    def test_imgbb_chosen_when_configured(self):
        from doxyedit import imagehost
        with tempfile.TemporaryDirectory() as td:
            _make_config(Path(td), """
image_hosting:
  provider: imgbb
  imgbb_api_key: K123
""")
            tmp_img = Path(td) / "x.png"
            tmp_img.write_bytes(b"fake")
            with patch.object(imagehost, "upload_to_imgur") as fake_imgur, \
                 patch.object(imagehost, "upload_to_imgbb") as fake_imgbb:
                fake_imgbb.return_value = imagehost.UploadResult(
                    success=True, url="x")
                imagehost.upload_image(str(tmp_img), project_dir=td)
                fake_imgbb.assert_called_once()
                fake_imgur.assert_not_called()
                # Verify api key passed through.
                args, _ = fake_imgbb.call_args
                self.assertEqual(args[1], "K123")

    def test_imgbb_provider_without_key_falls_back_to_imgur(self):
        """Selecting imgbb without an API key shouldn't try to upload
        with an empty key — fall back to imgur (rate limited but works)."""
        from doxyedit import imagehost
        with tempfile.TemporaryDirectory() as td:
            _make_config(Path(td), """
image_hosting:
  provider: imgbb
""")
            tmp_img = Path(td) / "x.png"
            tmp_img.write_bytes(b"fake")
            with patch.object(imagehost, "upload_to_imgur") as fake_imgur, \
                 patch.object(imagehost, "upload_to_imgbb") as fake_imgbb:
                fake_imgur.return_value = imagehost.UploadResult(
                    success=True, url="x")
                imagehost.upload_image(str(tmp_img), project_dir=td)
                fake_imgur.assert_called_once()
                fake_imgbb.assert_not_called()

    def test_corrupt_yaml_falls_back_to_imgur(self):
        from doxyedit import imagehost
        with tempfile.TemporaryDirectory() as td:
            _make_config(Path(td), "image_hosting:\n  - bad: structure\n")
            tmp_img = Path(td) / "x.png"
            tmp_img.write_bytes(b"fake")
            with patch.object(imagehost, "upload_to_imgur") as fake_imgur:
                fake_imgur.return_value = imagehost.UploadResult(
                    success=True, url="x")
                imagehost.upload_image(str(tmp_img), project_dir=td)
                fake_imgur.assert_called_once()

    def test_imgur_client_id_passed_through(self):
        from doxyedit import imagehost
        with tempfile.TemporaryDirectory() as td:
            _make_config(Path(td), """
image_hosting:
  provider: imgur
  imgur_client_id: ABCDEF
""")
            tmp_img = Path(td) / "x.png"
            tmp_img.write_bytes(b"fake")
            with patch.object(imagehost, "upload_to_imgur") as fake_imgur:
                fake_imgur.return_value = imagehost.UploadResult(
                    success=True, url="x")
                imagehost.upload_image(str(tmp_img), project_dir=td)
                args, _ = fake_imgur.call_args
                self.assertEqual(args[1], "ABCDEF")


if __name__ == "__main__":
    unittest.main()
