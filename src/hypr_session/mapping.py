"""
mapping.py — The class-to-command resolution engine.

Problem: Hyprland reports a window's "class" (the Wayland app-id),
but this often doesn't match what you type to launch the app.

Examples from real systems:
  class "org.kde.dolphin"  → binary "dolphin"
  class "code-url-handler" → binary "code"
  class "obsidian"         → binary from /usr/lib/electron32/electron  ← useless

Solution: Three-stage fallback chain:
  Stage 1: /proc/<pid>/exe basename      — works for most standard apps
  Stage 2: XDG .desktop file parsing    — solves KDE/GNOME app-id mismatches
  Stage 3: Bundled class_map.json       — covers Electron apps and edge cases

The mapping is built once per save invocation and cached in memory.
Disk access (scanning /usr/share/applications) is done once, not per window.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

#: Bundled fallback map shipped with the package as package data.
BUNDLED_MAP_PATH = Path(__file__).parent / "data" / "class_map.json"

#: Standard XDG locations for .desktop files. Checked in order.
_DESKTOP_SEARCH_DIRS: list[Path] = [
    Path.home() / ".local" / "share" / "applications",  # user-installed apps first
    Path("/usr/local/share/applications"),               # locally built apps
    Path("/usr/share/applications"),                     # package manager apps
    Path("/var/lib/flatpak/exports/share/applications"), # Flatpak system
    Path.home() / ".local" / "share" / "flatpak" / "exports" / "share" / "applications",
]

#: Regex to strip XDG desktop entry field code placeholders (%U, %f, etc.)
_PLACEHOLDER_RE = re.compile(r"\s+%[a-zA-Z]")

#: Electron binary name fragments — if the exe path contains any of these,
#: we know the exe path is the electron launcher, not the app itself.
_ELECTRON_FRAGMENTS = ("electron", "node", "chromium")


# ---------------------------------------------------------------------------
# Bundled map loader
# ---------------------------------------------------------------------------


def load_bundled_map() -> dict[str, str]:
    """
    Load the bundled class_map.json shipped with the package.

    This covers known problematic apps that either:
    - Are Electron apps (exe is the electron binary, not the app)
    - Have a class name that doesn't match any .desktop StartupWMClass
    - Have unusual launch mechanics

    Returns an empty dict if the file is missing or unparseable.
    All keys are lowercased for case-insensitive lookup.
    """
    if not BUNDLED_MAP_PATH.exists():
        return {}
    try:
        raw = json.loads(BUNDLED_MAP_PATH.read_text())
        return {k.lower(): v for k, v in raw.items()}
    except (json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------------------
# XDG .desktop file parser
# ---------------------------------------------------------------------------


def _extract_field(content: str, field_name: str) -> str | None:
    """
    Extract a field value from a .desktop file's [Desktop Entry] section.

    Only reads from the [Desktop Entry] section — avoids picking up
    field values from [Desktop Action ...] sub-sections.

    Returns the raw value string, or None if the field is absent.
    """
    in_desktop_entry = False
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("["):
            in_desktop_entry = (line == "[Desktop Entry]")
            continue
        if not in_desktop_entry:
            continue
        if line.startswith(f"{field_name}="):
            return line.split("=", 1)[1].strip()
    return None


def _parse_exec_command(exec_value: str) -> str:
    """
    Clean up the Exec= value from a .desktop file.

    Desktop files use field codes like %U (URL), %f (file), %F (files).
    We strip these because we're restoring the bare app, not opening a file.
    We also take only the binary (argv[0]), not the full argument list,
    because we want the app to start in its default state.
    """
    # Strip field codes
    cleaned = _PLACEHOLDER_RE.sub("", exec_value).strip()
    # Take only the binary path, not flags/args
    binary = cleaned.split()[0] if cleaned else ""
    # Return just the basename if it's an absolute path that exists
    p = Path(binary)
    if p.is_absolute() and p.exists():
        return p.name
    return binary


def build_desktop_map() -> dict[str, str]:
    """
    Scan XDG .desktop files and build a StartupWMClass → Exec mapping.

    This is the definitive way to resolve app-ids to launch commands on Linux.
    Every properly packaged app ships a .desktop file that explicitly declares
    its StartupWMClass (= Hyprland's "class" field) and Exec command.

    Returns a dict with lowercase keys for case-insensitive lookup.
    Skips .desktop files that:
    - Have NoDisplay=true (invisible launcher, not a real app)
    - Are missing StartupWMClass (can't map without it)
    - Have an Exec value that contains an electron binary (handled by bundled map)

    O(n) in the number of installed .desktop files. Typically 200-500 files
    on a desktop system. Fast enough to run once per save invocation.
    """
    mapping: dict[str, str] = {}

    for search_dir in _DESKTOP_SEARCH_DIRS:
        if not search_dir.exists():
            continue

        for desktop_file in search_dir.glob("*.desktop"):
            try:
                content = desktop_file.read_text(errors="replace")
            except OSError:
                continue

            # Skip hidden/invisible launchers
            no_display = _extract_field(content, "NoDisplay")
            if no_display and no_display.lower() == "true":
                continue

            wm_class = _extract_field(content, "StartupWMClass")
            exec_value = _extract_field(content, "Exec")

            if not wm_class or not exec_value:
                continue

            binary = _parse_exec_command(exec_value)
            if not binary:
                continue

            # Don't use this mapping if the binary is electron —
            # the bundled map has the correct override for Electron apps.
            if any(frag in binary.lower() for frag in _ELECTRON_FRAGMENTS):
                continue

            # First writer wins — user apps (~/.local/share) take precedence
            # over system apps (/usr/share) because we search user dirs first.
            key = wm_class.lower()
            if key not in mapping:
                mapping[key] = binary

    return mapping


# ---------------------------------------------------------------------------
# Main resolution function
# ---------------------------------------------------------------------------


def resolve_command(
    initial_class: str,
    exe_path: str | None,
    bundled_map: dict[str, str],
    desktop_map: dict[str, str],
) -> str:
    """
    Resolve the launch command for a window using a three-stage fallback chain.

    Stage 1: /proc/<pid>/exe basename
      Most reliable for standard apps. If dolphin's exe is /usr/bin/dolphin,
      the basename is "dolphin" and we're done.
      SKIP if the exe basename is an electron/node binary — it's a launcher,
      not the app. Fall through to Stage 2/3 for Electron apps.

    Stage 2: XDG .desktop file map
      Resolves class names like "org.kde.dolphin" to "dolphin" by reading
      the StartupWMClass field from /usr/share/applications/*.desktop.
      This is the standard Linux approach.

    Stage 3: Bundled class_map.json
      Handles known edge cases: Electron apps (VSCode, Obsidian, Discord),
      apps with unusual class names, etc.

    Stage 4: Use initial_class as-is
      Last resort. Works for many apps where class == binary name
      (firefox, kitty, steam, etc.).

    Returns the command string to pass to subprocess.Popen.
    """
    class_lower = initial_class.lower()

    # --- Stage 1: /proc/<pid>/exe basename ---
    if exe_path:
        exe_name = Path(exe_path).name
        is_electron = any(frag in exe_name.lower() for frag in _ELECTRON_FRAGMENTS)
        if exe_name and not is_electron:
            return exe_name

    # --- Stage 2: XDG .desktop map ---
    if class_lower in desktop_map:
        return desktop_map[class_lower]

    # --- Stage 3: Bundled class map ---
    if class_lower in bundled_map:
        return bundled_map[class_lower]

    # --- Stage 4: Use class name as-is ---
    # This works for apps like "firefox", "kitty", "steam" where
    # class == binary name. For unknown apps, this is the best we can do.
    return initial_class
