"""
restore.py — Session restore logic.
"""

from __future__ import annotations

import logging
import shlex
import shutil
import subprocess
import time
from collections.abc import Generator
from pathlib import Path

from .config import TERMINAL_CWD_FLAGS, HyprSessionConfig, load_config
from .models import FullscreenState, WindowEntry
from .session import load_session
from .utils import run_hyprctl

log = logging.getLogger(__name__)
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

def _get_client_info(address: str) -> dict | None:
    try:
        clients: list[dict] = run_hyprctl("clients")  # type: ignore[assignment]
        for c in clients:
            if c.get("address") == address:
                return c
    except RuntimeError:
        pass
    return None

def _wait_for_new_address(
    wm_class: str, before: set[str], timeout: float, poll_interval: float = 0.3
) -> str | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = _addresses_for_class(wm_class)
        new = current - before
        if new:
            return list(new)[0]
        time.sleep(poll_interval)
    return None

def _build_cwd_cmd(window: WindowEntry, cfg: HyprSessionConfig) -> str:
    """Append the CWD flag to the launch command for terminal emulators."""
    cmd = window.cmd
    if not cfg.restore_cwd or not window.cwd or not Path(window.cwd).is_dir():
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

def _build_dispatch_arg(window: WindowEntry, cfg: HyprSessionConfig) -> str:
    """Build the Hyprland dispatch exec argument with window rules."""
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
    cmd = _build_cwd_cmd(window, cfg)

    return f"[{rule_string}] {cmd}"

def restore_session(
    profile: str | None = None,
    dry_run: bool = False,
    workspaces: list[int] | None = None,
    exclude_classes: list[str] | None = None,
) -> Generator[tuple[WindowEntry, str], None, None]:
    """
    Generator that yields (WindowEntry, StatusString) to decouple logic from the UI.
    """
    cfg = load_config()
    session = load_session(profile)

    if session is None or not session.windows:
        return

    # Filter windows based on workspaces and exclude list
    filtered_windows = []
    for w in session.windows:
        if workspaces is not None and w.workspace_id not in workspaces:
            continue
        if exclude_classes is not None and any(w.initial_class.lower() == ec.lower() for ec in exclude_classes):
            continue
        filtered_windows.append(w)

    if not filtered_windows:
        return

    if cfg.restore_delay_seconds > 0 and not dry_run:
        time.sleep(cfg.restore_delay_seconds)

    for i, window in enumerate(filtered_windows):
        executable = window.cmd.split()[0]
        if not shutil.which(executable):
            log.warning("Skipping %s: '%s' not found in PATH", window.initial_class, executable)
            yield window, "MISSING"
            continue

        if dry_run:
            yield window, "DRY_RUN"
            continue

        dispatch_arg = _build_dispatch_arg(window, cfg)
        before = _addresses_for_class(window.initial_class)

        log.info("Launching %s on workspace %d", window.initial_class, window.workspace_id)
        log.debug("Dispatch arg: %s", dispatch_arg)

        # 1. Fire Atomic Rule
        subprocess.run(
            ["hyprctl", "dispatch", "exec", dispatch_arg],
            capture_output=True,
            check=False,
        )

        # 2. Wait for rendering
        new_address = _wait_for_new_address(
            window.initial_class, before, cfg.window_wait_timeout
        )

        if not new_address:
            log.warning("Timed out waiting for %s window", window.initial_class)
            yield window, "TIMEOUT"
            continue

        # 3. FORCE PLACEMENT (DBus Countermeasure)
        # Wait briefly for the window to be fully mapped before moving it
        time.sleep(0.4)

        client_info = _get_client_info(new_address)
        if not client_info:
            continue

        if client_info.get("workspace", {}).get("id") != window.workspace_id:
            subprocess.run([
                "hyprctl", "dispatch", "movetoworkspacesilent",
                f"{window.workspace_id},address:{new_address}"
            ], check=False)

        if window.floating and cfg.restore_floating:
            if not client_info.get("floating", False):
                subprocess.run(["hyprctl", "dispatch", "setfloating", f"address:{new_address}"], check=False)
            
            curr_x, curr_y = client_info.get("at", [0, 0])
            curr_w, curr_h = client_info.get("size", [0, 0])
            target_x, target_y = window.at
            target_w, target_h = window.size
            
            if abs(curr_x - target_x) > 5 or abs(curr_y - target_y) > 5:
                subprocess.run(["hyprctl", "dispatch", "movewindowpixel", f"exact {target_x} {target_y},address:{new_address}"], check=False)
            
            if abs(curr_w - target_w) > 5 or abs(curr_h - target_h) > 5:
                subprocess.run(["hyprctl", "dispatch", "resizewindowpixel", f"exact {target_w} {target_h},address:{new_address}"], check=False)

        log.info("Placed %s at %s on workspace %d", window.initial_class, new_address, window.workspace_id)
        yield window, "OK"

        # Inter-launch delay to avoid IPC flooding
        if i < len(session.windows) - 1:
            time.sleep(0.3)
