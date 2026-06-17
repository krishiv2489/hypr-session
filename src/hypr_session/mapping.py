"""
mapping.py — The class-to-command resolution engine.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

BUNDLED_MAP_PATH = Path(__file__).parent / "data" / "class_map.json"

def _get_desktop_search_dirs() -> list[Path]:
    import os
    dirs: list[Path] = []

    # 1. XDG_DATA_HOME (respect environment, default to ~/.local/share)
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        data_home = Path(xdg_data_home).expanduser()
    else:
        data_home = Path.home() / ".local" / "share"
    dirs.append(data_home / "applications")

    # 2. XDG_DATA_DIRS (default to /usr/local/share:/usr/share)
    xdg_data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    for d in xdg_data_dirs.split(":"):
        if d.strip():
            dirs.append(Path(d.strip()).expanduser() / "applications")

    # 3. NixOS search paths
    dirs.append(Path("/run/current-system/sw/share/applications"))
    dirs.append(Path("~/.nix-profile/share/applications").expanduser())

    # 4. Snap search paths
    dirs.append(Path("/var/lib/snapd/desktop/applications"))

    # 5. Flatpak paths (system and user) if they exist
    flatpak_system = Path("/var/lib/flatpak/exports/share/applications")
    flatpak_user = (Path.home() / ".local" / "share" / "flatpak" / "exports" / "share" / "applications")
    if flatpak_system.exists():
        dirs.append(flatpak_system)
    if flatpak_user.exists():
        dirs.append(flatpak_user)

    # De-duplicate to preserve order and keep only unique Path objects
    seen = set()
    unique_dirs = []
    for d in dirs:
        try:
            resolved = d.resolve()
        except Exception:
            resolved = d
        if resolved not in seen:
            seen.add(resolved)
            unique_dirs.append(d)

    return unique_dirs

_PLACEHOLDER_RE = re.compile(r"\s+%[a-zA-Z]")

# Added sandbox and interpreter binaries to force fallback
_IGNORE_EXE_FRAGMENTS = ("electron", "node", "chromium", "bwrap", "flatpak", "python")

def load_bundled_map() -> dict[str, str]:
    if not BUNDLED_MAP_PATH.exists():
        return {}
    try:
        raw = json.loads(BUNDLED_MAP_PATH.read_text())
        return {k.lower(): v for k, v in raw.items()}
    except (json.JSONDecodeError, OSError):
        return {}

def _extract_field(content: str, field_name: str) -> str | None:
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
    cleaned = _PLACEHOLDER_RE.sub("", exec_value).strip()
    if not cleaned:
        return ""

    parts = cleaned.split()
    first_part = parts[0]
    is_flatpak = False
    if first_part == "flatpak":
        is_flatpak = True
    else:
        try:
            if Path(first_part).name == "flatpak":
                is_flatpak = True
        except Exception:
            pass

    if is_flatpak and len(parts) > 1 and parts[1] == "run":
        return cleaned

    binary = parts[0]
    p = Path(binary)
    if p.is_absolute() and p.exists():
        return p.name
    return binary

def build_desktop_map() -> dict[str, str]:
    mapping: dict[str, str] = {}

    for search_dir in _get_desktop_search_dirs():
        if not search_dir.exists():
            continue

        for desktop_file in search_dir.glob("*.desktop"):
            try:
                content = desktop_file.read_text(errors="replace")
            except OSError:
                continue

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

            # Check if this is a flatpak command, so we do not skip it
            is_flatpak = False
            parts = binary.split()
            if parts:
                first_part = parts[0]
                if first_part == "flatpak" or (first_part.startswith("/") and Path(first_part).name == "flatpak"):
                    if len(parts) > 1 and parts[1] == "run":
                        is_flatpak = True

            if not is_flatpak and any(frag in binary.lower() for frag in _IGNORE_EXE_FRAGMENTS):
                continue

            key = wm_class.lower()
            if key not in mapping:
                mapping[key] = binary

    return mapping

def resolve_command(
    initial_class: str,
    exe_path: str | None,
    bundled_map: dict[str, str],
    desktop_map: dict[str, str],
) -> str:
    class_lower = initial_class.lower()

    if exe_path:
        exe_name = Path(exe_path).name
        is_ignored = any(frag in exe_name.lower() for frag in _IGNORE_EXE_FRAGMENTS)
        if exe_name and not is_ignored:
            return exe_name

    if class_lower in desktop_map:
        return desktop_map[class_lower]

    if class_lower in bundled_map:
        return bundled_map[class_lower]

    return initial_class
