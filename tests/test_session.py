"""AsyncLoadHandle — opaque cancel handle the splash uses without
knowing whether a single-project or collection load is in flight.

The contract these tests pin: cancel() flips the flag AND forwards the
cancel to whatever loader is currently active. If the inner loader's
cancel() raises, the handle must swallow it (the splash can't recover
from a thread-shutdown error during cancel).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestAsyncLoadHandle(unittest.TestCase):
    def test_default_not_cancelled(self):
        from doxyedit.session import AsyncLoadHandle
        h = AsyncLoadHandle(loader=None)
        self.assertFalse(h.cancelled)

    def test_cancel_sets_flag(self):
        from doxyedit.session import AsyncLoadHandle
        h = AsyncLoadHandle(loader=None)
        h.cancel()
        self.assertTrue(h.cancelled)

    def test_cancel_forwards_to_loader(self):
        from doxyedit.session import AsyncLoadHandle
        loader = MagicMock()
        h = AsyncLoadHandle(loader=loader)
        h.cancel()
        loader.cancel.assert_called_once()
        self.assertTrue(h.cancelled)

    def test_cancel_swallows_loader_exception(self):
        """The splash calls cancel() blindly during shutdown; if the
        underlying QThread is already torn down its cancel() may raise.
        The handle must absorb that so the splash never crashes."""
        from doxyedit.session import AsyncLoadHandle

        class Bad:
            def cancel(self):
                raise RuntimeError("thread already gone")

        h = AsyncLoadHandle(loader=Bad())
        h.cancel()  # must not raise
        self.assertTrue(h.cancelled)

    def test_cancel_with_no_loader_is_noop(self):
        from doxyedit.session import AsyncLoadHandle
        h = AsyncLoadHandle(loader=None)
        h.cancel()
        h.cancel()  # idempotent
        self.assertTrue(h.cancelled)

    def test_state_attribute_exposed(self):
        """Handle carries an optional `_state` dict for collection loads.
        Splash / restore code reaches in to attach it; if this attribute
        ever vanishes, collection-load cancel breaks silently."""
        from doxyedit.session import AsyncLoadHandle
        h = AsyncLoadHandle(loader=None)
        self.assertIsNone(h._state)
        h._state = {"phase": "loading_assets"}
        self.assertEqual(h._state["phase"], "loading_assets")


if __name__ == "__main__":
    unittest.main()
