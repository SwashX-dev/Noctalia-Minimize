"""Live integration test against a real, disposable Niri session.

Not part of `nix flake check` (needs a compositor). Run it inside a nested
Niri whose only windows are disposable test windows, for example:

    niri -c test-config.kdl &              # nested session (window on your desktop)
    export NIRI_SOCKET=/run/user/$UID/niri.wayland-2.<pid>.sock
    for t in A B C; do niri msg action spawn -- ghostty --gtk-single-instance=false --title="Test window $t" -e sleep 3600; done
    MINIMIZER=./result/bin/noctalia-minimizer python3 tests/live/niri_live_test.py

It refuses to run if any window title does not start with "Test window".
"""
import json
import os
import subprocess
import sys
import time

CLI = os.environ.get("MINIMIZER", "noctalia-minimizer")
SOCKET = os.environ["NIRI_SOCKET"]


def niri(*args):
    out = subprocess.run(["niri", "msg", "--json", *args], check=True, capture_output=True, text=True).stdout
    return json.loads(out) if out.strip() else None


def cli(*args, expect_ok=True):
    result = subprocess.run([CLI, *args], capture_output=True, text=True)
    data = json.loads(result.stdout)
    assert (result.returncode == 0) == expect_ok, (args, result.returncode, data)
    return data


def windows():
    return {w["title"]: w for w in niri("windows")}


def spaces():
    return {s["id"]: s for s in niri("workspaces")}


def parking_id():
    return next((s["id"] for s in spaces().values() if s["name"] == "Noctalia Minimized"), None)


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        sys.exit(1)


def main():
    titles = list(windows())
    if not titles or any(not t.startswith("Test window") for t in titles):
        sys.exit("Refusing: this Niri session has windows that are not disposable test windows: %r" % titles)
    names = sorted(titles)[:3]
    a, b, c = names
    origin = {t: w["workspace_id"] for t, w in windows().items()}

    niri("action", "focus-window", "--id", str(windows()[c]["id"]))
    state = cli("minimize")
    check("minimize active window", windows()[c]["workspace_id"] == parking_id())
    check("minimized window is listed", [w["title"] for w in state["minimized"]] == [c])
    check("focus did not follow the parked window", not windows()[c]["is_focused"])

    cli("minimize", "--id", str(windows()[b]["id"]))
    check("multiple windows parked", {windows()[b]["workspace_id"], windows()[c]["workspace_id"]} == {parking_id()})

    state = cli("restore-last")
    check("restore-last returns most recent (B)", windows()[b]["workspace_id"] == origin[b])
    check("restore focuses restored window", windows()[b]["is_focused"])

    cli("restore", "--id", str(windows()[c]["id"]))
    check("restore individual window", windows()[c]["workspace_id"] == origin[c])
    time.sleep(0.3)
    check("parking workspace name released", parking_id() is None)

    # Close a window while it is minimized.
    cli("minimize", "--id", str(windows()[c]["id"]))
    closed_id = windows()[c]["id"]
    pid = windows()[c].get("pid")
    niri("action", "close-window", "--id", str(closed_id))
    time.sleep(1.0)
    if any(w["id"] == closed_id for w in windows().values()) and pid:
        os.kill(pid, 15)  # the app ignored the polite close (e.g. a confirm dialog): it exits instead
        time.sleep(1.5)
    state = cli("status")
    check("closed minimized window is pruned", all(w["id"] != closed_id for w in state["minimized"]))
    check("names released after close", parking_id() is None and not any(
        (s["name"] or "").startswith("Restore ") for s in spaces().values()))

    # Move A to another workspace, then minimize everything and restore all.
    other = next(s["id"] for s in spaces().values() if s["id"] != windows()[a]["workspace_id"])
    niri("action", "move-window-to-workspace", "--window-id", str(windows()[a]["id"]), "--focus", "false",
         str(spaces()[other]["idx"]))
    origin = {t: w["workspace_id"] for t, w in windows().items()}
    check("windows on two workspaces", len(set(origin.values())) == 2, origin)
    focused_before = next((t for t, w in windows().items() if w["is_focused"]), None)
    cli("minimize-all")
    check("minimize all parks every window", all(w["workspace_id"] == parking_id() for w in windows().values()))
    cli("restore-all")
    check("restore all returns each window to its own workspace",
          all(windows()[t]["workspace_id"] == origin[t] for t in origin), {t: windows()[t]["workspace_id"] for t in origin})
    check("no windows were closed by parking", sorted(windows()) == sorted(origin))
    focused_after = next((t for t, w in windows().items() if w["is_focused"]), None)
    check("restore all did not move focus to a restored window", focused_after in (None, focused_before),
          (focused_before, focused_after))

    # IPC failure handling.
    env = dict(os.environ, NIRI_SOCKET="/nonexistent/niri.sock")
    result = subprocess.run([CLI, "status"], capture_output=True, text=True, env=env)
    check("unreachable Niri reports JSON error", result.returncode == 1 and "error" in json.loads(result.stdout))
    print("ALL LIVE CHECKS PASSED")


if __name__ == "__main__":
    main()
