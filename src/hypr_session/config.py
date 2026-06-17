"""
config.py — All configuration constants and the config file loader.

Config file location: ~/.config/hypr-session/config.toml
Data directory:       ~/.local/share/hypr-session/
Pause lock file:      ~/.local/share/hypr-session/.paused

The config file is OPTIONAL. If it doesn't exist, all defaults apply.
This is intentional: the tool should work out of the box with zero config.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

# tomllib is stdlib in Python 3.11+. For 3.10 and below you'd need tomli.
# We require 3.11 in pyproject.toml so this is always available.
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[no-redef]
    except ImportError:
        raise RuntimeError("Python 3.11+ is required for hypr-session.")


# ---------------------------------------------------------------------------
# Directory and file paths
# ---------------------------------------------------------------------------

CONFIG_DIR: Path = Path.home() / ".config" / "hypr-session"
DATA_DIR: Path = Path.home() / ".local" / "share" / "hypr-session"
CONFIG_FILE: Path = CONFIG_DIR / "config.toml"

# A zero-byte file whose EXISTENCE means "auto-save is paused".
# Created by `hypr-session pause`, deleted by `hypr-session resume`.
PAUSE_LOCK: Path = DATA_DIR / ".paused"


# ---------------------------------------------------------------------------
# Default ignore sets — classes and content types we never save
# ---------------------------------------------------------------------------

#: Window classes that are never included in a saved session.
#: These are either system UI components (managed by autostart),
#: media players (file-path args make blind restore wrong),
#: or auth agents (launched automatically by PAM/systemd).
DEFAULT_IGNORE_CLASSES: frozenset[str] = frozenset(
    {
        # Media players — they embed the file path in argv; restoring
        # would restart media from 0:00, not from where it was paused.
        "mpv",
        "vlc",
        "celluloid",
        "totem",
        "rhythmbox",
        # System UI — these are managed by hyprland.conf exec-once, not sessions.
        "waybar",
        "dunst",
        "hyprpaper",
        "swaybg",
        "swww",
        "eww",
        "ags",
        "rofi",
        "wofi",
        "fuzzel",
        # Auth agents — launched automatically at session start by systemd/PAM.
        "polkit-gnome-authentication-agent-1",
        "lxqt-policykit-agent",
        "org.gnome.polkit-gnome-authentication-agent",
        # XDG portals — compositor infrastructure, not user apps.
        "xdg-desktop-portal",
        "xdg-desktop-portal-hyprland",
        "xdg-desktop-portal-gtk",
        "xdg-desktop-portal-kde",
        # The session tool itself — avoids self-referential save.
        "hypr-session",
    }
)

#: Hyprland's contentType field values that trigger auto-ignore.
#: "video" covers mpv, VLC, etc. "game" covers full-screen game launchers.
DEFAULT_IGNORE_CONTENT_TYPES: frozenset[str] = frozenset({"video", "game"})

#: Window classes that are known terminal emulators.
#: Used to decide whether to capture and restore the CWD of the child shell.
TERMINAL_CLASSES: frozenset[str] = frozenset(
    {
        "kitty",
        "alacritty",
        "foot",
        "wezterm",
        "gnome-terminal",
        "org.gnome.terminal",
        "konsole",
        "org.kde.konsole",
        "xterm",
        "urxvt",
        "st",
        "rio",
    }
)

#: Maps terminal class → the flag it uses to set the working directory.
#: Format: (flag_style, flag_string)
#:   "equals"    → --flag=<path>   (gnome-terminal style)
#:   "separate"  → --flag <path>   (kitty, alacritty, foot style)
#:   "subcommand"→ subcommand --flag <path>  (wezterm style)
TERMINAL_CWD_FLAGS: dict[str, tuple[str, str]] = {
    "kitty":            ("separate",   "--directory"),
    "alacritty":        ("separate",   "--working-directory"),
    "foot":             ("separate",   "--working-directory"),
    "wezterm":          ("subcommand", "start --cwd"),
    "gnome-terminal":   ("equals",     "--working-directory"),
    "org.gnome.terminal": ("equals",   "--working-directory"),
    "konsole":          ("separate",   "--workdir"),
    "org.kde.konsole":  ("separate",   "--workdir"),
}


# ---------------------------------------------------------------------------
# The config dataclass
# ---------------------------------------------------------------------------


@dataclass
class HyprSessionConfig:
    """
    Runtime configuration. Built from config.toml if it exists,
    otherwise all fields use their defaults.

    Users only need to set what they want to change.
    """

    # How long to sleep after Hyprland starts before beginning restoration.
    # Hyprland needs a moment to finish initializing its compositor state.
    restore_delay_seconds: float = 2.0

    # How long to wait for a single window to appear before giving up.
    # Firefox cold-start can take 8-10 seconds; 12 is a safe default.
    window_wait_timeout: float = 12.0

    # Whether to restore floating windows with their saved position and size.
    restore_floating: bool = True

    # Whether to reapply fullscreen/maximize state after launch.
    restore_fullscreen: bool = True

    # Whether to capture and restore terminal working directories.
    restore_cwd: bool = True

    # Classes to ignore ON TOP OF the defaults.
    # Users add their own; the default set is always included.
    extra_ignore_classes: set[str] = field(default_factory=set)

    @property
    def ignore_classes(self) -> frozenset[str]:
        """Combined set: defaults + user additions. Always lowercase."""
        return frozenset(
            c.lower() for c in (DEFAULT_IGNORE_CLASSES | self.extra_ignore_classes)
        )

    @property
    def ignore_content_types(self) -> frozenset[str]:
        return DEFAULT_IGNORE_CONTENT_TYPES


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


def load_config() -> HyprSessionConfig:
    """
    Load config from ~/.config/hypr-session/config.toml.

    If the file doesn't exist or is unparseable, returns a config with all
    defaults. We never crash on a missing or malformed config file —
    the tool must always be able to run.
    """
    if not CONFIG_FILE.exists():
        return HyprSessionConfig()

    try:
        with CONFIG_FILE.open("rb") as f:
            raw = tomllib.load(f)
    except Exception as exc:
        # Bad TOML syntax — warn but don't crash.
        import sys
        print(
            f"Warning: could not parse {CONFIG_FILE}: {exc}. Using defaults.",
            file=sys.stderr,
        )
        return HyprSessionConfig()

    cfg = HyprSessionConfig()
    general = raw.get("general", {})

    cfg.restore_delay_seconds = float(
        general.get("restore_delay_seconds", cfg.restore_delay_seconds)
    )
    cfg.window_wait_timeout = float(
        general.get("window_wait_timeout", cfg.window_wait_timeout)
    )
    cfg.restore_floating = bool(
        general.get("restore_floating", cfg.restore_floating)
    )
    cfg.restore_fullscreen = bool(
        general.get("restore_fullscreen", cfg.restore_fullscreen)
    )
    cfg.restore_cwd = bool(
        general.get("restore_cwd", cfg.restore_cwd)
    )

    ignore_section = raw.get("ignore", {})
    extra = ignore_section.get("classes", [])
    cfg.extra_ignore_classes = set(extra)

    return cfg


# ---------------------------------------------------------------------------
# Default config file template (written on first run if missing)
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_TEMPLATE = """\
# hypr-session configuration
# All values shown are the defaults. Uncomment and change what you need.

[general]
# Seconds to wait after Hyprland starts before restoring windows.
# restore_delay_seconds = 2.0

# Seconds to wait for each window to appear before giving up on it.
# window_wait_timeout = 12.0

# Restore floating windows with their exact position and size.
# restore_floating = true

# Re-apply fullscreen/maximize state after window appears.
# restore_fullscreen = true

# Capture and restore the working directory of terminal emulators.
# restore_cwd = true

[ignore]
# Additional window classes to never save (on top of the built-in ignore list).
# classes = ["obsidian", "steam"]
"""


def ensure_config_dir() -> None:
    """
    Create config and data directories if they don't exist.
    Write a default config.toml template if no config exists yet.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(DEFAULT_CONFIG_TEMPLATE)
