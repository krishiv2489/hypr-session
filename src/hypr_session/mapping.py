"""
mapping.py — The class-to-command resolution engine.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

BUNDLED_MAP_PATH = Path(__file__).parent / "data" / "class_map.json"

_DESKTOP_SEARCH_DIRS: list[Path] = [
    Path.home() / ".local" / "share" / "applications",
    Path("/usr/local/share/applications"),
    Path("/usr/share/applications"),
    Path("/var/lib/flatpak/exports/share/applications"),
    Path.home() / ".local" / "share" / "flatpak" / "exports" / "share" / "applications",
]

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
    binary = cleaned.split()[0] if cleaned else ""
    p = Path(binary)
    if p.is_absolute() and p.exists():
        return p.name
    return binary

def build_desktop_map() -> dict[str, str]:
    mapping: dict[str, str] = {}

    for search_dir in _DESKTOP_SEARCH_DIRS:
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

            if any(frag in binary.lower() for frag in _IGNORE_EXE_FRAGMENTS):
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
