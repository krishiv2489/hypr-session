"""
restore.py — Session restore logic.

The restore pipeline for each window:
  1. Build the hyprctl dispatch exec rule
  2. Snapshot which window addresses currently exist for this class
  3. Fire the dispatch exec rule via hyprctl
  4. Poll until a new address appears for this class
  5. THE FIX: Forcefully move the discovered address to the correct workspace
     to counter DBus-activated apps ignoring the initial exec rule.
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
# Address tracking
# ---------------------------------------------------------------------------

def _addresses_for_class(wm_class: str) -> set[str]:
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
    wm_class: str, before: set[str], timeout: float, poll_interval: float = 0.3
) -> str | None:
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
    cmd = window.cmd
    if not window.cwd or not Path(window.cwd).is_dir():
        return cmd

    class_lower = window.initial_class.lower()
    flag_info = TERMINAL_CWD_FLAGS.get(class_lower)

    if flag_info is None:
        return f"{cmd} --working-directory {shlex.quote(window.cwd)}"

    style, flag = flag_info
    quoted_cwd = shlex.quote(window.cwd)

    if style == "separate":
        return f"{cmd} {flag} {quoted_cwd}"
    elif style == "equals":
        return f"{cmd} {flag}={quoted_cwd}"
    elif style == "subcommand":
        return f"{cmd} {flag} {quoted_cwd}"
    return cmd

def _build_dispatch_arg(window: WindowEntry, cfg) -> str:
    """
    Builds the argument string directly. 
    Returns: "[workspace 1 silent] firefox --dir '/home/user'"
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

    # THE FIX: Do not wrap the entire thing in 'exec'. Just return the exact
    # string Hyprland expects to receive as an argument.
    return f"[{rule_string}] {cmd}"

# ---------------------------------------------------------------------------
# Per-window restore
# ---------------------------------------------------------------------------

def _restore_window(window: WindowEntry, cfg) -> bool:
    dispatch_arg = _build_dispatch_arg(window, cfg)
    before = _addresses_for_class(window.initial_class)

    # 1. Fire the atomic rule (bypassing shlex entirely to preserve inner quotes)
    subprocess.run(
        ["hyprctl", "dispatch", "exec", dispatch_arg],
        capture_output=True,
        check=False,
    )

    # 2. Wait for the window to actually render
    new_address = _wait_for_new_address(
        window.initial_class, before, cfg.window_wait_timeout
    )

    if not new_address:
        return False

    # 3. THE FIX: Force Placement 
    # Even if DBus stole the process and ignored the [workspace X] exec rule,
    # we now have the window's Hex Address. We can FORCE it to obey.
    subprocess.run([
        "hyprctl", "dispatch", "movetoworkspacesilent", 
        f"{window.workspace_id},address:{new_address}"
    ], check=False)

    if window.floating and cfg.restore_floating:
        subprocess.run(["hyprctl", "dispatch", "movewindowpixel", f"exact {window.at[0]} {window.at[1]},address:{new_address}"], check=False)
        subprocess.run(["hyprctl", "dispatch", "resizewindowpixel", f"exact {window.size[0]} {window.size[1]},address:{new_address}"], check=False)

    return True

# ---------------------------------------------------------------------------
# Main restore entry point
# ---------------------------------------------------------------------------

def restore_session(profile: str | None = None) -> tuple[int, int]:
    cfg = load_config()
    session = load_session(profile)
    label = profile or "default"

    if session is None:
        print(f"[hypr-session] No saved session for profile '{label}'.")
        return 0, 0

    if not session.windows:
        print(f"[hypr-session] Session '{label}' is empty — nothing to restore.")
        return 0, 0

    print(f"[hypr-session] Restoring {len(session.windows)} window(s) from '{label}'")

    if cfg.restore_delay_seconds > 0:
        print(f"[hypr-session] Waiting {cfg.restore_delay_seconds}s for compositor...")
        time.sleep(cfg.restore_delay_seconds)

    restored = 0
    failed = 0

    for i, window in enumerate(session.windows, 1):
        prefix = f"  [{i}/{len(session.windows)}]"
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
            print(f"{prefix} TIMEOUT — {window.initial_class} did not appear.")
            failed += 1

    print(f"\n[hypr-session] Done: {restored} restored, {failed} failed.")
    return restored, failed