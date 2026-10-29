"""Unprivileged, finite window operations for the Noctalia UI and shortcuts.

Every invocation prints exactly one JSON object and exits non-zero on failure.
"""
import argparse
import json
import os
import sys

from common import lock
from windows import Parking

ACTIONS = ["status", "minimize", "minimize-all", "restore", "restore-all", "restore-last", "restore-focused"]


def run(args, parking_factory=Parking):
    with lock("windows.lock"):
        parking = parking_factory()
        if args.action == "status":
            return parking.snapshot()
        if args.action == "minimize":
            return parking.minimize([args.id] if args.id is not None else None)
        if args.action == "minimize-all":
            return parking.minimize([w["id"] for w in parking.snapshot()["windows"]])
        if args.action == "restore":
            if args.id is None:
                raise ValueError("restore needs --id; use restore-last or restore-all otherwise")
            return parking.restore([args.id], focus=not args.no_focus)
        if args.action == "restore-all":
            # Bulk restore keeps the current focus; nothing jumps under the pointer.
            return parking.restore([w["id"] for w in parking.snapshot()["minimized"]], focus=args.focus)
        if args.action == "restore-last":
            return parking.restore_last(focus=not args.no_focus)
        if args.action == "restore-focused":
            if args.id is None:
                raise ValueError("restore-focused needs --id")
            parking.snapshot()
            focused = next((w for w in parking.niri.windows() if w.get("is_focused") and w["id"] == args.id), None)
            if focused and str(args.id) in parking.state["windows"]:
                return parking.restore([args.id])
            return {"skipped": True}
    raise ValueError("Unsupported window operation")


def parser():
    result = argparse.ArgumentParser(prog="noctalia-minimizer",
                                     description="Reversible window minimization for Niri (workspace parking).")
    result.add_argument("action", choices=ACTIONS)
    result.add_argument("--id", type=int, help="Niri window id")
    result.add_argument("--no-focus", action="store_true", help="restore without focusing the window")
    result.add_argument("--focus", action="store_true", help="restore-all: focus the last restored window")
    return result


def main(argv=None):
    os.umask(0o077)
    try:
        args = parser().parse_args(argv)
        print(json.dumps(run(args)))
        return 0
    except SystemExit:
        raise
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
