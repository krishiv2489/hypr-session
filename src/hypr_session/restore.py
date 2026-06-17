"""
restore.py — Session restore logic.

The restore pipeline for each window:
  1. Build the hyprctl dispatch exec rule (encodes workspace, float, size, fullscreen)
  2. Snapshot which window addresses currently exist for this class (before set)
  3. Fire the dispatch exec rule via hyprctl
  4. Poll until a new address appears for this class (after - before = new window)
  5. Log success or timeout

Windows are restored sequentially in the order they appear in the session
(which was sorted by focusHistoryID descending in session.py).
Sequential launch is required for the before/after address diffing to work —
if two Kitty windows launched simultaneously, we couldn't tell them apart.

The dispatch exec rule syntax is:
  hyprctl dispatch exec '[rule1; rule2; ...] command'

Hyprland parses the bracketed rules and applies them as the window is created,
before it's ever drawn. This is atomic — no flicker, no wrong-position-then-jump.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path

from .config import TERMINAL_CWD_FLAGS, load_config
from .models import FullscreenState, WindowEntry
from .session import load_session
from .utils import run_hyprctl


# ---------------------------------------------------------------------------
# Address tracking (before/after diffing)
# ---------------------------------------------------------------------------


def _addresses_for_class(wm_class: str) -> set[str]:
    """
    Return the set of window addresses currently open for a given class.

    Uses both 'class' and 'initialClass' fields because some apps report
    differently in these two fields (notably Electron apps in some setups).
    Case-insensitive match.
    """
    try:
        clients: list[dict] = run_hyprctl("clients")  # type: ignore[assignment]
        class_lower = wm_class.lower()
        return {
            c["address"]
            for c in clients
            if (c.get("class", "").lower() == class_lower)
            or (c.get("initialClass", "").lower() == class_lower)
        }
    except RuntimeError:
        return set()


def _wait_for_new_address(
    wm_class: str,
    before: set[str],
    timeout: float,
    poll_interval: float = 0.3,
) -> str | None:
    """
    Poll until a new window address appears for wm_class.

    The "new" address is computed as: current_addresses - before_addresses.
    Returns the new address string, or None on timeout.

    poll_interval: seconds between each /proc + hyprctl poll.
    0.3s means we check ~3x per second — fast enough to catch even quick apps
    without hammering the IPC socket.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = _addresses_for_class(wm_class)
        new = current - before
        if new:
            return new.pop()
        time.sleep(poll_interval)
    return None


# ---------------------------------------------------------------------------
# Dispatch rule builder
# ---------------------------------------------------------------------------


def _build_cwd_cmd(window: WindowEntry) -> str:
    """
    Build the launch command with CWD flag appended for terminal emulators.

    Different terminals use different flags to set the starting directory:
      kitty:        kitty --directory /path
      alacritty:    alacritty --working-directory /path
      foot:         foot --working-directory /path
      wezterm:      wezterm start --cwd /path
      gnome-terminal: gnome-terminal --working-directory=/path

    Returns the command unchanged if:
      - No CWD is saved
      - The terminal class is not in our flag map
      - The saved CWD path no longer exists on disk
    """
    cmd = window.cmd

    if not window.cwd:
        return cmd

    # Don't try to restore a CWD that no longer exists
    if not Path(window.cwd).is_dir():
        return cmd

    class_lower = window.initial_class.lower()
    flag_info = TERMINAL_CWD_FLAGS.get(class_lower)

    if flag_info is None:
        # Unknown terminal — try the most common flag style as a best guess
        return f"{cmd} --working-directory {shlex.quote(window.cwd)}"

    style, flag = flag_info
    quoted_cwd = shlex.quote(window.cwd)

    if style == "separate":
        # kitty --directory /path
        return f"{cmd} {flag} {quoted_cwd}"
    elif style == "equals":
        # gnome-terminal --working-directory=/path
        return f"{cmd} {flag}={quoted_cwd}"
    elif style == "subcommand":
        # wezterm start --cwd /path
        return f"{cmd} {flag} {quoted_cwd}"

    return cmd


def _build_exec_rule(window: WindowEntry, cfg) -> str:
    """
    Build the full Hyprland dispatch exec rule for a WindowEntry.

    The rule format is:
      exec '[workspace N silent; rule2; rule3] command --args'

    The full hyprctl call will be:
      hyprctl dispatch exec '[workspace N silent; ...] command'

    Rules applied (in order, per Hyprland's parser expectations):
      workspace N silent — always; places window on workspace N without
                           switching to it. "silent" is critical — without it
                           every restored window would steal focus and switch
                           your view to its workspace.

      pin               — if the window was pinned (visible on all workspaces)

      float             — if the window was floating
      move X Y          — floating only; sets pixel position
      size W H          — floating only; sets pixel size

      fullscreen        — if fullscreen state was FULLSCREEN (2) = true fullscreen
      maximize          — if fullscreen state was MAXIMIZED (1)

    For tiling windows, we ONLY set the workspace. The tiling layout is
    determined by insertion order, not by coordinates. Trying to set
    position for a tiling window fights the compositor and causes visual glitches.

    The command has the CWD flag appended for terminal emulators.
    """
    rules: list[str] = [f"workspace {window.workspace_id} silent"]

    if window.pinned:
        rules.append("pin")

    if window.floating and cfg.restore_floating:
        x, y = window.at
        w, h = window.size
        rules.append("float")
        rules.append(f"move {x} {y}")
        rules.append(f"size {w} {h}")

    if cfg.restore_fullscreen:
        fs = FullscreenState(window.fullscreen)
        if fs == FullscreenState.FULLSCREEN:
            rules.append("fullscreen")
        elif fs == FullscreenState.MAXIMIZED:
            rules.append("maximize")

    rule_string = "; ".join(rules)
    cmd = _build_cwd_cmd(window)

    # The final dispatch argument.
    # Note: we do NOT use shell=True in subprocess, so the brackets and
    # semicolons are not interpreted by sh — they go straight to hyprctl,
    # which passes them to Hyprland's own parser. This is correct behavior.
    return f"exec '[{rule_string}] {cmd}'"


# ---------------------------------------------------------------------------
# Per-window restore
# ---------------------------------------------------------------------------


def _restore_window(window: WindowEntry, cfg) -> bool:
    """
    Launch one window and wait for it to appear.

    Returns True if the window appeared within the timeout, False otherwise.
    A False return means the app either failed to launch or took too long.
    The restore loop continues regardless — one failed window doesn't abort the rest.
    """
    rule = _build_exec_rule(window, cfg)

    # Snapshot BEFORE launch so we can detect the new window
    before = _addresses_for_class(window.initial_class)

    # Fire the dispatch exec rule
    # hyprctl dispatch exec '[workspace 1 silent] firefox'
    result = subprocess.run(
        ["hyprctl", "dispatch"] + shlex.split(rule),
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return False

    # Wait for the new address to appear
    new_address = _wait_for_new_address(
        window.initial_class,
        before,
        cfg.window_wait_timeout,
    )

    return new_address is not None


# ---------------------------------------------------------------------------
# Main restore entry point
# ---------------------------------------------------------------------------


def restore_session(profile: str | None = None) -> tuple[int, int]:
    """
    Restore a saved Hyprland session.

    Loads the session JSON, applies a startup delay, then restores each
    window sequentially. Sequential (not parallel) launch is required
    for the before/after address diffing to correctly identify each window.

    Returns (restored_count, failed_count).

    Progress is printed to stdout so the user can see what's happening
    when restore is triggered from exec-once in hyprland.conf.
    """
    cfg = load_config()
    session = load_session(profile)

    label = profile or "default"

    if session is None:
        print(f"[hypr-session] No saved session for profile '{label}'.")
        return 0, 0

    if not session.windows:
        print(f"[hypr-session] Session '{label}' is empty — nothing to restore.")
        return 0, 0

    print(
        f"[hypr-session] Restoring {len(session.windows)} window(s) "
        f"from '{label}' (saved {session.timestamp})"
    )

    # Wait for the compositor to fully initialize.
    # Without this delay, the first dispatch exec may fire before Hyprland
    # has finished setting up workspace state, causing windows to land on
    # the wrong workspace.
    if cfg.restore_delay_seconds > 0:
        print(
            f"[hypr-session] Waiting {cfg.restore_delay_seconds}s for compositor..."
        )
        time.sleep(cfg.restore_delay_seconds)

    restored = 0
    failed = 0

    for i, window in enumerate(session.windows, 1):
        prefix = f"  [{i}/{len(session.windows)}]"

        # Build the rule string for display before attempting launch
        rule = _build_exec_rule(window, cfg)

        print(
            f"{prefix} {window.initial_class} "
            f"→ ws:{window.workspace_id} "
            f"{'[float]' if window.floating else '[tile]'} "
            f"{'[fs]' if window.fullscreen else ''}"
        )

        success = _restore_window(window, cfg)

        if success:
            print(f"{prefix} OK")
            restored += 1
        else:
            print(
                f"{prefix} TIMEOUT — {window.initial_class} did not appear "
                f"within {cfg.window_wait_timeout}s (app may have crashed or "
                f"the class name changed)"
            )
            failed += 1

    print(
        f"\n[hypr-session] Done: {restored} restored, {failed} failed."
    )
    return restored, failed
