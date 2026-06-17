"""
utils.py — Low-level system utilities (hyprctl wrappers, /proc reading).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path


def notify_user(title: str, message: str, urgency: str = "normal") -> None:
    """Send a desktop notification using notify-send if available."""
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-u", urgency, title, message], check=False)


def run_hyprctl(command: str) -> dict | list:
    """Run a hyprctl command and parse the JSON output safely."""
    try:
        result = subprocess.run(
            ["hyprctl", "-j", command],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)
    except FileNotFoundError as e:
        raise RuntimeError("hyprctl not found. Are you running Hyprland?") from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Hyprland IPC failed: {e.stderr}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError("Invalid JSON received from hyprctl") from e


def wait_for_hyprland(timeout: float = 10.0) -> bool:
    """Wait for Hyprland to become ready by polling the IPC socket."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            run_hyprctl("monitors")
            return True
        except RuntimeError:
            time.sleep(0.2)
    return False


def is_hyprland_running() -> bool:
    """Check if we are currently inside a Hyprland session."""
    return "HYPRLAND_INSTANCE_SIGNATURE" in os.environ


def _read_ppid(pid: int) -> int | None:
    """Read the parent PID from /proc/<pid>/status."""
    try:
        status_text = Path(f"/proc/{pid}/status").read_text()
        for line in status_text.splitlines():
            if line.startswith("PPid:"):
                return int(line.split()[1])
    except (FileNotFoundError, PermissionError):
        pass
    return None


def get_ancestor_pids(pid: int) -> set[int]:
    """Walk up the process tree to find all ancestors of a PID."""
    ancestors = set()
    current_pid: int | None = pid

    while current_pid is not None and current_pid > 1:
        ppid = _read_ppid(current_pid)
        if ppid is not None and ppid > 0:
            ancestors.add(ppid)
        current_pid = ppid

    return ancestors


def get_current_process_ancestors() -> set[int]:
    """Return all PIDs in the chain that launched this script (e.g., zsh -> kitty)."""
    my_pid = os.getpid()
    return get_ancestor_pids(my_pid)


def get_exe_path(pid: int) -> str | None:
    """Resolve the actual binary path from /proc/<pid>/exe."""
    try:
        return str(Path(f"/proc/{pid}/exe").resolve())
    except (FileNotFoundError, PermissionError):
        return None


def get_terminal_cwd(terminal_pid: int) -> str | None:
    """
    Find the foreground shell child of a terminal emulator
    and return its current working directory.
    """
    try:
        # Find child processes of the terminal
        children = [
            int(p.name)
            for p in Path("/proc").iterdir()
            if p.name.isdigit()
            and Path(f"/proc/{p.name}/status").exists()
            and _read_ppid(int(p.name)) == terminal_pid
        ]

        if not children:
            return None

        # Take the last child (most recently spawned shell/process)
        child_pid = children[-1]

        # /proc/<pid>/cwd is a symlink to the actual directory
        return str(Path(f"/proc/{child_pid}/cwd").resolve())
    except (PermissionError, FileNotFoundError):
        return None
