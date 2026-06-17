"""
utils.py — Low-level system utilities.

All direct interaction with:
  - The kernel's /proc virtual filesystem
  - The hyprctl binary (Hyprland IPC)
  - The OS environment

Nothing here knows about sessions or windows at a high level.
Everything here is mockable for testing.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


# ---------------------------------------------------------------------------
# Hyprland IPC
# ---------------------------------------------------------------------------


def run_hyprctl(subcommand: str) -> list | dict:
    """
    Run `hyprctl -j <subcommand>` and return parsed JSON.

    Uses check=False so we can give a useful error rather than a CalledProcessError
    stack trace. Raises RuntimeError on failure.

    Examples:
        run_hyprctl("clients")     → list of window dicts
        run_hyprctl("workspaces")  → list of workspace dicts
        run_hyprctl("monitors")    → list of monitor dicts
    """
    result = subprocess.run(
        ["hyprctl", "-j", subcommand],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"hyprctl -j {subcommand} failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"hyprctl -j {subcommand} returned invalid JSON: {exc}"
        ) from exc


def hyprctl_dispatch(rule: str) -> bool:
    """
    Run `hyprctl dispatch <rule>`.

    Returns True if the dispatch succeeded, False otherwise.
    Failures are non-fatal — a failed dispatch skips that window
    but does not abort the restore loop.

    The rule is passed as a single string argument, NOT through a shell.
    This means bracket syntax like `[workspace 1 silent] firefox` is
    passed directly to hyprctl, which is correct — the brackets are parsed
    by Hyprland, not by sh.
    """
    result = subprocess.run(
        ["hyprctl", "dispatch"] + rule.split(None, 1),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def is_hyprland_running() -> bool:
    """
    Check whether we are inside a live Hyprland session.

    Hyprland sets HYPRLAND_INSTANCE_SIGNATURE in the environment of every
    process it manages. If this variable is absent, we are not in Hyprland.
    """
    return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"))


# ---------------------------------------------------------------------------
# /proc — process information
# ---------------------------------------------------------------------------


def get_exe_path(pid: int) -> str | None:
    """
    Read /proc/<pid>/exe — the symlink to the actual binary on disk.

    This is more reliable than reading argv[0] from cmdline because:
      1. Some processes rewrite their argv[0] to show status info.
      2. Electron apps set argv[0] to the electron binary, not the app name.

    Returns None if the process has exited or we lack permission.

    Example:
        PID of Dolphin → "/usr/bin/dolphin"
        PID of Obsidian → "/usr/lib/electron32/electron"  (caught by mapping engine)
    """
    try:
        return str(Path(f"/proc/{pid}/exe").resolve(strict=True))
    except (FileNotFoundError, PermissionError, OSError):
        return None


def get_cmdline(pid: int) -> list[str] | None:
    """
    Read /proc/<pid>/cmdline and return the full argv as a list.

    /proc/<pid>/cmdline stores the arguments as null-byte-separated bytes.
    We split on null bytes and decode each part as UTF-8.

    Returns None if the process has exited or we lack permission.

    Example:
        PID of `kitty --directory /home/krishiv` →
        ["/usr/bin/kitty", "--directory", "/home/krishiv"]
    """
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        parts = [p.decode("utf-8", errors="replace") for p in raw.split(b"\x00") if p]
        return parts if parts else None
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None


def get_cwd(pid: int) -> str | None:
    """
    Read /proc/<pid>/cwd — symlink to the process's current working directory.

    Returns None if the process has exited, we lack permission,
    or the CWD resolves to the root directory (meaningless to restore).
    """
    try:
        cwd = str(Path(f"/proc/{pid}/cwd").resolve(strict=True))
        return cwd if cwd != "/" else None
    except (FileNotFoundError, PermissionError, OSError):
        return None


def get_ppid(pid: int) -> int | None:
    """
    Read the PPID (parent process ID) of a process from /proc/<pid>/status.

    Reads the PPid field from the status file. This is more reliable than
    reading from /proc/<pid>/stat (which uses positional fields and is
    tricky to parse when process names contain spaces).

    Returns None if the process has exited.
    """
    try:
        status_text = Path(f"/proc/{pid}/status").read_text(errors="replace")
        for line in status_text.splitlines():
            if line.startswith("PPid:"):
                return int(line.split()[1])
    except (FileNotFoundError, PermissionError, ValueError):
        pass
    return None


def get_child_pids(parent_pid: int) -> list[int]:
    """
    Find all direct child PIDs of parent_pid.

    Scans every numeric entry in /proc and checks its PPid field.
    O(n) in the number of running processes — typically 200-400 on a desktop.
    This is fast enough for our use case (runs once per terminal window).

    Returns an empty list if parent_pid has no children or has exited.
    """
    children: list[int] = []
    proc_root = Path("/proc")

    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        ppid = get_ppid(int(entry.name))
        if ppid == parent_pid:
            children.append(int(entry.name))

    return children


def get_terminal_cwd(terminal_pid: int) -> str | None:
    """
    Get the working directory of the foreground shell inside a terminal.

    When you open Kitty, it fork+execs a shell as its child (typically zsh).
    That shell's CWD is the directory the user is currently in.

    Strategy:
      1. Find child PIDs of the terminal process.
      2. Sort descending by PID (higher = spawned later = more recent shell).
      3. Return the CWD of the first child that has a non-root CWD.
      4. Fall back to the terminal's own CWD if no useful child CWD found.

    This handles the common case of one shell per terminal window.
    For Kitty with multiple tabs/splits, it returns the CWD of the most
    recently spawned shell (which is usually what you want).

    Returns None if no useful CWD can be determined.
    """
    children = get_child_pids(terminal_pid)

    if not children:
        # No child processes — terminal just opened, return terminal CWD itself.
        return get_cwd(terminal_pid)

    # Higher PID = spawned more recently = foreground/active shell
    children.sort(reverse=True)

    for child_pid in children:
        cwd = get_cwd(child_pid)
        if cwd:
            return cwd

    # All children had root CWD (unlikely) — fall back to terminal itself
    return get_cwd(terminal_pid)


def get_ancestor_pids(start_pid: int) -> set[int]:
    """
    Walk up the process tree from start_pid and collect all ancestor PIDs.

    Used to exclude the terminal window that is running the save command.

    Example: hypr-session save runs as:
        PID 12345 (python3)
          → PPID 12300 (zsh)
            → PPID 800456 (kitty)  ← this is the window we want to exclude
              → PPID 1 (systemd)   ← stop here

    Returns a set of all ancestor PIDs up to (but not including) PID 1.
    """
    ancestors: set[int] = set()
    current_pid = start_pid

    for _ in range(32):  # depth limit prevents infinite loops on bad /proc state
        ppid = get_ppid(current_pid)
        if ppid is None or ppid <= 1:
            break
        ancestors.add(ppid)
        current_pid = ppid

    return ancestors
