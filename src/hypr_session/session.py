"""
session.py — Session save, load, and management logic.

The save pipeline:
  1. Query `hyprctl -j clients` for all windows
  2. For each window:
     a. Skip if class is in the ignore list
     b. Skip if contentType is video/game
     c. Skip if window is swallowed (transient child of a terminal)
     d. Skip if the window belongs to an ancestor of this process
        (prevents saving the terminal that's running hypr-session save)
     e. Resolve the launch command via the mapping engine
     f. If it's a terminal emulator, capture the CWD of the child shell
     g. Build a WindowEntry
  3. Sort windows by focusHistoryID descending (tiling restore order)
  4. Write Session JSON to disk
"""

from __future__ import annotations

import json
import os
import shutil
import time
import logging
from pathlib import Path

log = logging.getLogger(__name__)

from .config import (
    BACKUPS_DIR,
    DATA_DIR,
    TERMINAL_CLASSES,
    load_config,
)
from .mapping import build_desktop_map, load_bundled_map, resolve_command
from .models import Session, WindowEntry
from .utils import (
    get_ancestor_pids,
    get_exe_path,
    get_terminal_cwd,
    run_hyprctl,
)


def _extract_fullscreen(raw: object) -> int:
    """Extract fullscreen int from Hyprland's field.

    Hyprland v0.40+ returns ``{"isFullscreen": bool, "current": int}``.
    Older versions return a plain integer.  Handle both gracefully.
    """
    if isinstance(raw, dict):
        return int(raw.get("current", raw.get("isFullscreen", 0)))
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Session file paths
# ---------------------------------------------------------------------------


def get_session_path(profile: str | None = None) -> Path:
    """
    Return the file path for a session profile.

    Default session:       ~/.local/share/hypr-session/session.json
    Named profile "work":  ~/.local/share/hypr-session/session-work.json
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if profile:
        safe_name = profile.replace("/", "_").replace(" ", "_")
        return DATA_DIR / f"session-{safe_name}.json"
    return DATA_DIR / "session.json"


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


def get_current_session_windows(only_active: bool = False) -> list[WindowEntry]:
    """
    Query Hyprland and return a list of WindowEntry objects representing the active session.
    """
    cfg = load_config()

    # Build mapping tables once — scanning .desktop files is O(n) but
    # we only do it once per save, not per window.
    bundled_map = load_bundled_map()
    desktop_map = build_desktop_map()

    # Determine our own ancestor PIDs to exclude the terminal running this save.
    # This prevents hypr-session from saving its own terminal window.
    own_ancestors = get_ancestor_pids(os.getpid())

    active_ws_id = None
    if only_active:
        try:
            active_ws = run_hyprctl("activeworkspace")
            if isinstance(active_ws, dict):
                active_ws_id = active_ws.get("id")
        except Exception:
            try:
                monitors = run_hyprctl("monitors")
                if isinstance(monitors, list):
                    for m in monitors:
                        if m.get("focused"):
                            active_ws_id = m.get("activeWorkspace", {}).get("id")
                            break
            except Exception:
                pass
        
        if active_ws_id is None:
            log.warning("only_active=True but could not determine active workspace. Saving nothing.")

    clients: list[dict] = run_hyprctl("clients")  # type: ignore[assignment]
    windows: list[WindowEntry] = []

    for client in clients:
        # ----------------------------------------------------------------
        # Step 1: Identity and basic filters
        # ----------------------------------------------------------------

        initial_class = (
            client.get("initialClass", "")
            or client.get("class", "")
            or ""
        )

        if not initial_class:
            # Empty class = compositor internal, tooltip, or transient popup.
            continue

        if initial_class.lower() in cfg.ignore_classes:
            # Explicitly ignored (system UI, media players, etc.)
            continue

        content_type = client.get("contentType", "none") or "none"
        if content_type in cfg.ignore_content_types:
            # video/game content type — restoring would be wrong.
            continue

        # ----------------------------------------------------------------
        # Step 2: Skip transient / structural windows
        # ----------------------------------------------------------------

        swallowing = client.get("swallowing", "0x0") or "0x0"
        if swallowing not in ("0x0", "", None):
            # A swallowed window is a transient child displayed inside a
            # terminal emulator. It exists only while the terminal exists.
            continue

        pid = client.get("pid", 0)

        if pid in own_ancestors:
            # This window is the terminal running the save command.
            # Including it would create an infinite loop on restore.
            continue

        # ----------------------------------------------------------------
        # Step 3: Resolve the launch command
        # ----------------------------------------------------------------

        exe_path = get_exe_path(pid) if pid else None
        cmd = resolve_command(initial_class, exe_path, bundled_map, desktop_map)

        # ----------------------------------------------------------------
        # Step 4: Capture terminal CWD
        # ----------------------------------------------------------------

        cwd: str | None = None
        if cfg.restore_cwd and initial_class.lower() in {
            c.lower() for c in TERMINAL_CLASSES
        }:
            cwd = get_terminal_cwd(pid) if pid else None

        # ----------------------------------------------------------------
        # Step 5: Build the WindowEntry
        # ----------------------------------------------------------------

        at_raw = client.get("at", [0, 0])
        size_raw = client.get("size", [800, 600])
        workspace = client.get("workspace", {})
        workspace_id = workspace.get("id", 1)
        workspace_name = workspace.get("name", "")
        
        special_workspace_name = workspace_name if workspace_name.startswith("special:") else None

        if active_ws_id is not None and workspace_id != active_ws_id:
            continue

        grouped = client.get("grouped", [])
        if grouped:
            group_id = min(grouped + [client.get("address", "0x0")])
        else:
            group_id = None

        entry = WindowEntry(
            address=client.get("address", "0x0"),
            initial_class=initial_class,
            cmd=cmd,
            workspace_id=workspace_id,
            monitor=client.get("monitor", 0),
            floating=client.get("floating", False),
            at=(int(at_raw[0]), int(at_raw[1])),
            size=(int(size_raw[0]), int(size_raw[1])),
            fullscreen=_extract_fullscreen(client.get("fullscreen", 0)),
            pinned=client.get("pinned", False),
            focus_history_id=client.get("focusHistoryID", 0),
            cwd=cwd,
            special_workspace_name=special_workspace_name,
            group_id=group_id,
        )
        windows.append(entry)

    # ----------------------------------------------------------------
    # Step 6: Sort for correct tiling restore order
    # ----------------------------------------------------------------
    #
    # focusHistoryID is Hyprland's focus recency counter.
    # 0 = most recently focused, higher = less recently focused.
    #
    # We sort DESCENDING (highest focusHistoryID first) so that when
    # we restore windows in this order:
    #   - The least-recently-used window is placed first (goes left in tiling)
    #   - The most-recently-used window is placed last (gets focus on restore)
    #
    # This mirrors the original tiling insertion order.
    windows.sort(key=lambda w: w.focus_history_id, reverse=True)
    return windows

def save_session(profile: str | None = None, force_empty: bool = False, only_active: bool = False) -> tuple[Path, Session]:
    """
    Capture the current Hyprland session and write it to disk.

    Returns (path, session) so the caller can report what was saved.

    Raises RuntimeError if hyprctl fails or if trying to save an empty session without force_empty.
    """
    windows = get_current_session_windows(only_active=only_active)

    if not windows and not force_empty:
        raise RuntimeError("No windows detected. Refusing to save an empty session.")

    session = Session(windows=windows)
    path = get_session_path(profile)

    if path.exists():
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        backup_path = BACKUPS_DIR / f"{path.name}.{int(time.time())}.bak"
        shutil.copy2(path, backup_path)

        # Rotate backups (keep last 10 per profile)
        backups = sorted(BACKUPS_DIR.glob(f"{path.name}.*.bak"), key=lambda p: p.stat().st_mtime)
        while len(backups) > 10:
            backups.pop(0).unlink(missing_ok=True)

    path.write_text(json.dumps(session.to_dict(), indent=2))

    return path, session


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


def load_session(profile: str | None = None) -> Session | None:
    """
    Load a saved session from disk.

    Returns None if no session file exists for this profile.
    Raises RuntimeError if the file exists but is corrupted.
    """
    path = get_session_path(profile)
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text())
        return Session.from_dict(data)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Session file {path} is corrupted and cannot be loaded: {exc}\n"
            "Run `hypr-session clear` to delete it and start fresh."
        ) from exc


# ---------------------------------------------------------------------------
# List all sessions
# ---------------------------------------------------------------------------


def list_sessions() -> list[tuple[str, Path, Session | None]]:
    """
    Return all saved sessions as (label, path, session_or_none) tuples.

    session_or_none is None if the file is corrupted.
    Sorted by profile name.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    for path in sorted(DATA_DIR.glob("session*.json")):
        if path.name == "session.json":
            label = "default"
        else:
            label = path.stem.removeprefix("session-")

        session: Session | None = None
        try:
            data = json.loads(path.read_text())
            session = Session.from_dict(data)
        except Exception:
            pass

        results.append((label, path, session))

    return results


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def clear_session(profile: str | None = None) -> bool:
    """
    Delete the session file for the given profile.

    Returns True if a file was deleted, False if it didn't exist.
    """
    path = get_session_path(profile)
    if path.exists():
        path.unlink()
        return True
    return False


def clear_all_sessions() -> int:
    """
    Delete all session files in the data directory.

    Returns the number of files deleted.
    """
    count = 0
    for _label, path, _ in list_sessions():
        path.unlink(missing_ok=True)
        count += 1
    return count
