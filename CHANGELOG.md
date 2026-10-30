# Changelog

## 1.0.1

- Match README, plugin and interface branding to Noctalia Minimize.
- Update repository URLs while preserving existing commands, IDs and settings.

## 1.0.0 — 2026-10-29

First standalone release, extracted from the local "Desk Tools" plugin
(`local/desk-tools` 0.1.0), whose window-management half it replaces.

### Kept from Desk Tools
- Niri workspace parking: windows move without focus to a reserved
  `Noctalia Minimized` workspace and return to their original workspace.
- Temporary `Restore N` names keep emptied origin workspaces alive; user names are never overwritten.
- Event-driven automatic restore when a parked window is selected in the taskbar.
- Bar button (left click minimize, right click panel), control-center tile, restore panel.
- Private 0600 atomic state; recovery after Noctalia restarts.

### New
- Standalone plugin `local/minimizer` and CLI `noctalia-minimizer`.
- Nix flake: package, overlay, NixOS module with configurable Niri key bindings, checks and a VM test.
- `noctalia-minimizer-setup`: conflict-checked Niri include, Noctalia source registration, backup and `undo`.
- `restore-last` action; minimized list ordered most recent first.
- Restore all no longer moves keyboard focus (single restore still focuses the window).
- `Ctrl+A` restores all from the panel; optional confirmation for Minimize all.
- One-time adoption of windows parked by Desk Tools in the same Niri session.
- Backend path is baked into the plugin at build time (no `PATH` dependency).
