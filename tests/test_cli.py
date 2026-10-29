"""CLI contract: one JSON object per call, non-zero exit on failure."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import cli
from test_windows import FakeNiri
from windows import Parking


class Cli(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = mock.patch.dict(os.environ, {"XDG_STATE_HOME": self.temp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.niri = FakeNiri()

    def call(self, *argv):
        factory = lambda: Parking(self.niri, None, "s", legacy_path=False)
        return cli.run(cli.parser().parse_args(list(argv)), parking_factory=factory)

    def test_minimize_then_restore_all_keeps_focus(self):
        self.call("minimize")
        self.call("minimize", "--id", "11")
        self.niri.calls.clear()
        result = self.call("restore-all")
        self.assertEqual(result["minimized"], [])
        self.assertFalse(any(name == "FocusWindow" for name, _ in self.niri.calls))

    def test_minimize_all_and_restore_last(self):
        self.call("minimize-all")
        result = self.call("restore-last")
        self.assertEqual(len(result["minimized"]), 2)

    def test_restore_requires_id(self):
        with self.assertRaises(ValueError):
            self.call("restore")

    def test_restore_focused_skips_untracked_windows(self):
        self.assertEqual(self.call("restore-focused", "--id", "10"), {"skipped": True})

    def test_errors_are_json_with_nonzero_exit(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"NIRI_SOCKET": "/nonexistent/niri.sock"}), contextlib.redirect_stdout(out):
            code = cli.main(["status"])
        self.assertEqual(code, 1)
        self.assertIn("Niri socket", json.loads(out.getvalue())["error"])


if __name__ == "__main__":
    unittest.main()
