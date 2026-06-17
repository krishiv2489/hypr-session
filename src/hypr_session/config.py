"""
config.py — Configuration loading and defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:
    pass

import os

CONFIG_DIR = Path.home() / ".config/hypr-session"
CONFIG_FILE = CONFIG_DIR / "config.toml"
DATA_DIR = Path.home() / ".local/share/hypr-session"
BACKUPS_DIR = DATA_DIR / "backups"

_run_user_dir = Path(f"/run/user/{os.getuid()}")
if _run_user_dir.exists():
    RUNTIME_PAUSE_LOCK = _run_user_dir / "hypr-session.paused"
else:
    RUNTIME_PAUSE_LOCK = Path(f"/tmp/hypr-session-{os.getuid()}.paused")

PERMANENT_PAUSE_LOCK = CONFIG_DIR / "disabled"

DEFAULT_IGNORE_CLASSES = {
    "mpv",
    "vlc",
    "celluloid",
    "waybar",
    "dunst",
    "hyprpaper",
    "swaybg",
    "swayosd",
    "polkit-gnome-authentication-agent-1",
    "lxqt-policykit-agent",
    "hypr-session",
    "rofi",
    "wofi",
}

DEFAULT_CONTENT_TYPE_IGNORE = {
    "video",
    "game",
}

TERMINAL_CWD_FLAGS: dict[str, tuple[str, str]] = {
    "kitty": ("separate", "--directory"),
    "alacritty": ("separate", "--working-directory"),
    "foot": ("separate", "--working-directory"),
    "wezterm": ("subcommand", "start --cwd"),
    "gnome-terminal": ("separate", "--working-directory"),
    "konsole": ("separate", "--working-directory"),
    "ghostty": ("separate", "--working-directory"),
}

TERMINAL_CLASSES = set(TERMINAL_CWD_FLAGS.keys())

@dataclass
class HyprSessionConfig:
    restore_delay_seconds: float = 0.5  # Sped up for faster perceived boot
    window_wait_timeout: float = 10.0
    restore_floating: bool = True
    restore_fullscreen: bool = True
    restore_cwd: bool = True
    ignore_classes: set[str] = field(default_factory=lambda: set(DEFAULT_IGNORE_CLASSES))
    ignore_content_types: set[str] = field(default_factory=lambda: set(DEFAULT_CONTENT_TYPE_IGNORE))

def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        default_toml = """[general]
# Delay before restoring windows on startup (gives Waybar/Wallpaper time to load)
restore_delay_seconds = 0.5

# Max time to wait for an app to spawn its window before giving up
window_wait_timeout = 10.0

restore_floating = true
restore_fullscreen = true

# Attempt to restore the current working directory of terminal emulators
restore_cwd = true

[ignore]
# Window classes to completely ignore during save
classes = [
    "mpv", "vlc", "celluloid",
    "waybar", "dunst", "hyprpaper", "swaybg", "swayosd", "rofi", "wofi",
    "polkit-gnome-authentication-agent-1", "lxqt-policykit-agent",
    "hypr-session"
]

# Wayland content types to ignore (prevents auto-restarting movies/games)
content_types = ["video", "game"]
"""
        CONFIG_FILE.write_text(default_toml)

def load_config() -> HyprSessionConfig:
    if not CONFIG_FILE.exists():
        return HyprSessionConfig()

    try:
        data = tomllib.loads(CONFIG_FILE.read_text())
    except Exception:
        return HyprSessionConfig()

    cfg = HyprSessionConfig()

    if "general" in data:
        gen = data["general"]
        cfg.restore_delay_seconds = float(gen.get("restore_delay_seconds", cfg.restore_delay_seconds))
        cfg.window_wait_timeout = float(gen.get("window_wait_timeout", cfg.window_wait_timeout))
        cfg.restore_floating = bool(gen.get("restore_floating", cfg.restore_floating))
        cfg.restore_fullscreen = bool(gen.get("restore_fullscreen", cfg.restore_fullscreen))
        cfg.restore_cwd = bool(gen.get("restore_cwd", cfg.restore_cwd))

    if "ignore" in data:
        ign = data["ignore"]
        if "classes" in ign:
            cfg.ignore_classes = {c.lower() for c in ign["classes"]}
        if "content_types" in ign:
            cfg.ignore_content_types = {c.lower() for c in ign["content_types"]}

    return cfg
