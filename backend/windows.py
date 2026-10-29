"""Niri IPC workspace parking. No root, no window closing, no permanent daemon.

Niri has no native minimize/hidden state. A window is "minimized" by moving it,
without focus, to one reserved, named workspace and remembering its original
workspace. Restoring moves it back. Applications keep running throughout.
"""
import json
import os
from pathlib import Path
import socket

from common import boot_id, read_json, state_dir, state_root, write_json

PARKING = os.environ.get("NOCTALIA_MINIMIZER_PARKING_NAME") or "Noctalia Minimized"
LEGACY_STATE = "noctalia-desk-tools/windows.json"


class Niri:
    """Minimal JSON client for the Niri IPC socket of the current session."""

    def __init__(self):
        candidate = os.environ.get("NIRI_SOCKET")
        if not candidate:
            runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
            matches = [p for p in runtime.glob("niri.*.sock") if p.is_socket() and p.stat().st_uid == os.getuid()]
            if len(matches) != 1:
                raise RuntimeError("Window parking requires a running Niri session (set NIRI_SOCKET). "
                                   "Other compositors are not supported.")
            candidate = str(matches[0])
        path = Path(candidate)
        try:
            usable = path.is_socket() and path.stat().st_uid == os.getuid()
        except OSError:
            usable = False
        if not usable:
            raise RuntimeError("The Niri socket is unavailable or belongs to another user")
        self.identity = str(path)

    def request(self, request):
        try:
            with socket.socket(socket.AF_UNIX) as stream:
                stream.settimeout(3)
                stream.connect(self.identity)
                stream.sendall(json.dumps(request).encode() + b"\n")
                raw = stream.makefile("rb").readline(4 * 1024 * 1024)
            reply = json.loads(raw)
        except (OSError, ValueError) as exc:
            raise RuntimeError("Niri did not answer; no window was closed") from exc
        if not isinstance(reply, dict):
            raise RuntimeError("Unsupported Niri IPC reply")
        if "Err" in reply:
            raise RuntimeError("Niri rejected the action: " + str(reply["Err"]))
        if "Ok" not in reply:
            raise RuntimeError("Unsupported Niri IPC reply")
        result = reply["Ok"]
        if isinstance(request, str):
            return result.get(request) if isinstance(result, dict) else result
        return result

    def action(self, operation, **fields):
        return self.request({"Action": {operation: fields}})

    def windows(self):
        return self.request("Windows")

    def workspaces(self):
        return self.request("Workspaces")


def empty_state(session):
    return {"session": session, "parking_id": None, "origins": {}, "windows": {}, "seq": 0}


class Parking:
    def __init__(self, niri=None, path=None, session=None, legacy_path=None):
        self.niri = niri or Niri()
        self.path = path or state_dir() / "windows.json"
        self.session = session or boot_id() + ":" + self.niri.identity
        if legacy_path is None and path is None:
            legacy_path = state_root() / LEGACY_STATE
        self.state = read_json(self.path, {})
        if not self.state and legacy_path:
            # One-time adoption of windows parked by the original Desk Tools
            # plugin in this same Niri session. The legacy file is not changed.
            legacy = read_json(legacy_path, {})
            if legacy.get("session") == self.session and legacy.get("windows"):
                self.state = dict(legacy, imported_from=str(legacy_path))
        if self.state.get("session") != self.session:
            self.state = empty_state(self.session)
        self.state.setdefault("seq", 0)

    def save(self):
        write_json(self.path, self.state)

    def cleanup(self, workspaces, windows):
        spaces = {w["id"]: w for w in workspaces}
        records = self.state["windows"]
        parking = self.state.get("parking_id")
        live = {w["id"]: w for w in windows}
        for key in list(records):
            window = live.get(int(key))
            if window is None or window.get("workspace_id") != parking:
                del records[key]
        referenced = {str(r.get("origin_id")) for r in records.values()}
        for key, origin in list(self.state["origins"].items()):
            if key in referenced:
                continue
            current = spaces.get(int(key))
            if current and origin.get("pin_name") and current.get("name") == origin["pin_name"]:
                self.niri.action("UnsetWorkspaceName", reference={"Id": current["id"]})
            del self.state["origins"][key]
        # Never unname a workspace that still holds a window, including a window
        # the user manually moved into the parking workspace.
        if parking is not None and not any(w.get("workspace_id") == parking for w in windows):
            current = spaces.get(parking)
            if current and current.get("name") == PARKING:
                self.niri.action("UnsetWorkspaceName", reference={"Id": parking})
            self.state["parking_id"] = None
        self.save()

    def snapshot(self):
        windows, workspaces = self.niri.windows(), self.niri.workspaces()
        self.cleanup(workspaces, windows)
        parking = self.state.get("parking_id")
        records = self.state["windows"]
        normal, minimized = [], []
        focused_space = next((w for w in workspaces if w.get("is_focused")), None)
        active_id = focused_space.get("active_window_id") if focused_space else None
        for window in windows:
            item = {"id": window["id"], "title": str(window.get("title") or "Untitled window")[:180],
                    "app_id": str(window.get("app_id") or "")[:160],
                    "workspace_id": window.get("workspace_id"), "focused": bool(window.get("is_focused"))}
            if parking is not None and window.get("workspace_id") == parking:
                record = records.get(str(window["id"]), {})
                origin = self.state["origins"].get(str(record.get("origin_id")), {})
                item["origin"] = origin.get("display", "Restore to current workspace")
                item["seq"] = record.get("seq", 0)
                minimized.append(item)
            else:
                normal.append(item)
        # Most recently minimized first, so "restore last" and the list agree.
        minimized.sort(key=lambda w: -w["seq"])
        focused = next((w for w in normal if w["focused"]), None)
        if focused is None:
            focused = next((w for w in normal if w["id"] == active_id), None)
        return {"supported": True, "compositor": "Niri", "mode": "workspace parking",
                "parking_name": PARKING, "focused": focused, "windows": normal, "minimized": minimized,
                "message": "Parked windows stay running. Restore returns them to their original workspace."}

    def ensure_parking(self):
        if self.state.get("parking_id") is not None:
            return self.state["parking_id"]
        windows, spaces = self.niri.windows(), self.niri.workspaces()
        if any(w.get("name") == PARKING for w in spaces):
            raise RuntimeError(f"A workspace named '{PARKING}' already exists without this session's state. "
                               "Inspect it before renaming it; no windows were moved.")
        focused = next((w for w in spaces if w.get("is_focused")), None)
        empty = [w for w in spaces if not w.get("name") and not w.get("is_focused")
                 and not any(x.get("workspace_id") == w["id"] for x in windows)
                 and (focused is None or w.get("output") == focused.get("output"))]
        if not empty:
            raise RuntimeError("No empty Niri workspace is available for parking. Create an empty workspace and try again.")
        target = max(empty, key=lambda w: w["idx"])
        self.state["parking_id"] = target["id"]
        self.save()  # durable intent before modifying the compositor
        self.niri.action("SetWorkspaceName", name=PARKING, workspace={"Id": target["id"]})
        return target["id"]

    def minimize(self, ids=None):
        snapshot = self.snapshot()
        if ids is None:
            focused = snapshot["focused"]
            if not focused:
                raise RuntimeError("No active application window is available to minimize")
            ids = [focused["id"]]
        eligible = {w["id"] for w in snapshot["windows"]}
        if not ids:
            return dict(snapshot, result="There are no windows to minimize")
        if any(i not in eligible for i in ids):
            raise RuntimeError("A selected window disappeared or is already minimized; refresh the list")
        target = self.ensure_parking()
        count, failures = 0, []
        for identity in ids:
            try:
                window = next((w for w in self.niri.windows() if w["id"] == identity), None)
                if not window:
                    raise RuntimeError("Window was closed before it could be parked")
                origin_id = window.get("workspace_id")
                origin = next((w for w in self.niri.workspaces() if w["id"] == origin_id), None)
                if not origin:
                    raise RuntimeError("The original workspace is unavailable")
                key = str(origin_id)
                if key not in self.state["origins"]:
                    pin = None if origin.get("name") else f"Restore {origin_id}"
                    self.state["origins"][key] = {"id": origin_id, "pin_name": pin,
                        "display": origin.get("name") or f"Workspace {origin['idx']} · {origin.get('output', '')}"}
                self.state["seq"] += 1
                self.state["windows"][str(identity)] = {"origin_id": origin_id, "seq": self.state["seq"]}
                self.save()
                pin = self.state["origins"][key].get("pin_name")
                if pin and not origin.get("name"):
                    if any(w.get("name") == pin and w["id"] != origin_id for w in self.niri.workspaces()):
                        raise RuntimeError("A temporary workspace name conflicts with an existing workspace")
                    # Pin the (possibly now empty) origin so Niri does not delete it.
                    self.niri.action("SetWorkspaceName", name=pin, workspace={"Id": origin_id})
                self.niri.action("MoveWindowToWorkspace", window_id=identity, reference={"Id": target}, focus=False)
                count += 1
            except Exception as exc:
                failures.append(str(exc))
        result = self.snapshot()
        result["result"] = f"Minimized {count} window(s)"
        if failures:
            result["warning"] = "; ".join(failures)
        return result

    def restore(self, ids, focus=True):
        snapshot = self.snapshot()
        minimized = {w["id"] for w in snapshot["minimized"]}
        if not ids:
            return dict(snapshot, result="There are no minimized windows")
        if any(i not in minimized for i in ids):
            raise RuntimeError("A selected window is no longer minimized; refresh the list")
        last = None
        for identity in ids:
            spaces = self.niri.workspaces()
            origin_id = self.state["windows"].get(str(identity), {}).get("origin_id")
            origin = next((w for w in spaces if w["id"] == origin_id), None)
            if origin is None:
                origin = next((w for w in spaces if w.get("is_focused") and w["id"] != self.state.get("parking_id")), None)
            if origin is None:
                origin = next((w for w in spaces if w["id"] != self.state.get("parking_id")), None)
            if origin is None:
                raise RuntimeError("No destination workspace is available; the window is still parked safely")
            self.niri.action("MoveWindowToWorkspace", window_id=identity, reference={"Id": origin["id"]}, focus=False)
            self.state["windows"].pop(str(identity), None)
            self.save()
            last = identity
        result = self.snapshot()
        if focus and last is not None:
            self.niri.action("FocusWindow", id=last)
        return dict(result, result=f"Restored {len(ids)} window(s)")

    def restore_last(self, focus=True):
        minimized = self.snapshot()["minimized"]
        if not minimized:
            raise RuntimeError("There are no minimized windows to restore")
        return self.restore([minimized[0]["id"]], focus=focus)
