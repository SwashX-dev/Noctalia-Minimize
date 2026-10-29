"""Mocked Niri IPC tests. No compositor or real window is touched."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from windows import Parking, PARKING


class FakeNiri:
    identity = "test-socket"

    def __init__(self):
        self.spaces = [
            {"id": 1, "idx": 1, "name": None, "output": "eDP-1", "is_focused": True, "active_window_id": 10},
            {"id": 2, "idx": 2, "name": None, "output": "eDP-1", "is_focused": False, "active_window_id": None},
            {"id": 3, "idx": 1, "name": None, "output": "HDMI-A-1", "is_focused": False, "active_window_id": 20},
            {"id": 4, "idx": 2, "name": None, "output": "HDMI-A-1", "is_focused": False, "active_window_id": None},
        ]
        self.items = [
            {"id": 10, "workspace_id": 1, "title": "Test window", "app_id": "test", "is_focused": True},
            {"id": 11, "workspace_id": 1, "title": "Other", "app_id": "test", "is_focused": False},
            {"id": 20, "workspace_id": 3, "title": "Second monitor", "app_id": "viewer", "is_focused": False},
        ]
        self.calls = []
        self.fail = None

    def windows(self):
        if self.fail == "read":
            raise RuntimeError("Niri did not answer; no window was closed")
        return copy.deepcopy(self.items)

    def workspaces(self):
        if self.fail == "read":
            raise RuntimeError("Niri did not answer; no window was closed")
        return copy.deepcopy(self.spaces)

    def action(self, operation, **fields):
        if self.fail == operation:
            raise RuntimeError("Niri rejected the action: test failure")
        self.calls.append((operation, fields))
        if operation in ["SetWorkspaceName", "UnsetWorkspaceName"]:
            identity = (fields.get("workspace") or fields.get("reference"))["Id"]
            space = next(x for x in self.spaces if x["id"] == identity)
            space["name"] = fields.get("name")
        elif operation == "MoveWindowToWorkspace":
            item = next(x for x in self.items if x["id"] == fields["window_id"])
            item["workspace_id"] = fields["reference"]["Id"]
            if fields.get("focus"):
                raise AssertionError("parking must never move focus")
        elif operation == "FocusWindow":
            for item in self.items:
                item["is_focused"] = item["id"] == fields["id"]


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.niri = FakeNiri()
        self.path = Path(self.temp.name) / "windows.json"
        self.parking = Parking(self.niri, self.path, "test-session", legacy_path=False)

    def workspace_of(self, identity):
        return next(w for w in self.niri.items if w["id"] == identity)["workspace_id"]


class MinimizeRestore(Base):
    def test_minimize_active_and_restore_original_workspace(self):
        state = self.parking.minimize()
        self.assertEqual([w["id"] for w in state["minimized"]], [10])
        self.assertEqual(self.niri.spaces[1]["name"], PARKING)
        self.assertEqual(self.niri.spaces[0]["name"], "Restore 1")
        self.parking.restore([10])
        self.assertEqual(self.workspace_of(10), 1)
        self.assertIsNone(self.niri.spaces[0]["name"])
        self.assertIsNone(self.niri.spaces[1]["name"])

    def test_restore_individual_window_leaves_others_parked(self):
        self.parking.minimize([10, 11])
        state = self.parking.restore([11])
        self.assertEqual(self.workspace_of(11), 1)
        self.assertEqual([w["id"] for w in state["minimized"]], [10])

    def test_multiple_windows_survive_and_return(self):
        state = self.parking.minimize([10, 11])
        self.assertEqual(len(state["minimized"]), 2)
        self.parking.restore([10, 11])
        self.assertEqual({self.workspace_of(10), self.workspace_of(11)}, {1})
        self.assertFalse(any(name == "CloseWindow" for name, _ in self.niri.calls))

    def test_multiple_outputs_restore_to_each_origin(self):
        self.parking.minimize([10, 20])
        self.assertEqual(self.workspace_of(20), 2)  # parked on the focused output's spare workspace
        self.parking.restore([10, 20], focus=False)
        self.assertEqual(self.workspace_of(10), 1)
        self.assertEqual(self.workspace_of(20), 3)

    def test_restore_all_without_focus_change(self):
        self.parking.minimize([10, 11])
        self.niri.calls.clear()
        self.parking.restore([10, 11], focus=False)
        self.assertFalse(any(name == "FocusWindow" for name, _ in self.niri.calls))

    def test_single_restore_focuses_restored_window(self):
        self.parking.minimize([11])
        self.parking.restore([11])
        self.assertEqual(self.niri.calls[-1], ("FocusWindow", {"id": 11}))

    def test_restore_last_uses_most_recent(self):
        self.parking.minimize([11])
        self.parking.minimize([10])
        self.assertEqual([w["id"] for w in self.parking.snapshot()["minimized"]], [10, 11])
        self.parking.restore_last()
        self.assertEqual(self.workspace_of(10), 1)
        self.assertEqual(self.workspace_of(11), 2)

    def test_restore_last_with_nothing_parked(self):
        with self.assertRaises(RuntimeError):
            self.parking.restore_last()

    def test_minimize_all_targets_only_visible_windows(self):
        self.parking.minimize([11])
        state = self.parking.snapshot()
        self.parking.minimize([w["id"] for w in state["windows"]])
        self.assertEqual(len(self.parking.snapshot()["windows"]), 0)


class Robustness(Base):
    def test_state_survives_noctalia_restart(self):
        self.parking.minimize([11])
        restarted = Parking(self.niri, self.path, "test-session", legacy_path=False)
        self.assertEqual(restarted.snapshot()["minimized"][0]["id"], 11)
        restarted.restore([11])

    def test_new_niri_session_discards_stale_ids(self):
        self.parking.minimize([11])
        other = Parking(self.niri, self.path, "another-session", legacy_path=False)
        self.assertEqual(other.state["windows"], {})

    def test_closed_minimized_window_is_pruned_and_names_released(self):
        self.parking.minimize([11])
        self.niri.items = [w for w in self.niri.items if w["id"] != 11]
        self.assertEqual(self.parking.snapshot()["minimized"], [])
        self.assertIsNone(self.niri.spaces[0]["name"])
        self.assertIsNone(self.niri.spaces[1]["name"])

    def test_new_application_window_is_not_treated_as_minimized(self):
        self.parking.minimize([11])
        self.niri.items.append({"id": 30, "workspace_id": 1, "title": "New", "app_id": "x", "is_focused": False})
        snap = self.parking.snapshot()
        self.assertIn(30, [w["id"] for w in snap["windows"]])
        self.assertNotIn(30, [w["id"] for w in snap["minimized"]])

    def test_window_moved_out_manually_is_forgotten(self):
        self.parking.minimize([11])
        next(w for w in self.niri.items if w["id"] == 11)["workspace_id"] = 1
        self.assertEqual(self.parking.snapshot()["minimized"], [])

    def test_other_window_is_not_moved(self):
        self.parking.minimize([11])
        self.assertEqual(self.workspace_of(10), 1)

    def test_unknown_window_never_moves_anything(self):
        with self.assertRaises(RuntimeError):
            self.parking.minimize([999])
        self.assertEqual(self.niri.calls, [])

    def test_user_renamed_origin_is_not_overwritten(self):
        self.parking.minimize([11])
        self.niri.spaces[0]["name"] = "My work"
        self.parking.restore([11])
        self.assertEqual(self.niri.spaces[0]["name"], "My work")

    def test_deleted_origin_falls_back_to_focused_workspace(self):
        self.parking.minimize([20])
        self.niri.spaces = [s for s in self.niri.spaces if s["id"] != 3]
        self.parking.restore([20], focus=False)
        self.assertEqual(self.workspace_of(20), 1)

    def test_state_is_private(self):
        self.parking.minimize([11])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_existing_parking_name_is_not_hijacked(self):
        self.niri.spaces[1]["name"] = PARKING
        with self.assertRaises(RuntimeError):
            self.parking.minimize([11])
        self.assertEqual(self.workspace_of(11), 1)

    def test_no_empty_workspace_reports_error(self):
        self.niri.spaces = [self.niri.spaces[0]]
        with self.assertRaises(RuntimeError):
            self.parking.minimize([11])
        self.assertEqual(self.workspace_of(11), 1)


class IpcFailures(Base):
    def test_unreachable_niri_raises_cleanly(self):
        self.niri.fail = "read"
        with self.assertRaises(RuntimeError):
            self.parking.minimize()

    def test_failed_move_is_reported_and_window_stays(self):
        self.niri.fail = "MoveWindowToWorkspace"
        state = self.parking.minimize([11])
        self.assertIn("warning", state)
        self.assertEqual(self.workspace_of(11), 1)
        self.assertEqual(state["minimized"], [])

    def test_failed_restore_keeps_window_parked(self):
        self.parking.minimize([11])
        self.niri.fail = "MoveWindowToWorkspace"
        with self.assertRaises(RuntimeError):
            self.parking.restore([11])
        self.assertEqual(self.workspace_of(11), 2)
        self.niri.fail = None
        self.assertEqual([w["id"] for w in self.parking.snapshot()["minimized"]], [11])


class LegacyImport(unittest.TestCase):
    def test_desk_tools_state_is_adopted_once_for_same_session(self):
        with tempfile.TemporaryDirectory() as temp:
            niri = FakeNiri()
            niri.spaces[1]["name"] = PARKING
            niri.items[1]["workspace_id"] = 2
            legacy = Path(temp) / "legacy.json"
            legacy.write_text(json.dumps({"session": "s", "parking_id": 2,
                "origins": {"1": {"id": 1, "pin_name": None, "display": "Workspace 1"}},
                "windows": {"11": {"origin_id": 1}}}))
            parking = Parking(niri, Path(temp) / "own.json", "s", legacy_path=legacy)
            self.assertEqual([w["id"] for w in parking.snapshot()["minimized"]], [11])
            parking.restore([11])
            self.assertEqual(niri.items[1]["workspace_id"], 1)
            self.assertIn("11", json.loads(legacy.read_text())["windows"])  # legacy file untouched

    def test_legacy_state_from_other_session_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            legacy = Path(temp) / "legacy.json"
            legacy.write_text(json.dumps({"session": "old", "parking_id": 2, "origins": {}, "windows": {"11": {}}}))
            parking = Parking(FakeNiri(), Path(temp) / "own.json", "new", legacy_path=legacy)
            self.assertEqual(parking.state["windows"], {})


if __name__ == "__main__":
    unittest.main()
