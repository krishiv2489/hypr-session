<div align="center">

```text
██╗  ██╗██╗   ██╗██████╗ ██████╗       ███████╗███████╗███████╗███████╗██╗ ██████╗ ██████╗
██║  ██║╚██╗ ██╔╝██╔══██╗██╔══██╗      ██╔════╝██╔════╝██╔════╝██╔════╝██║██╔═══██╗██╔══██╗
███████║ ╚████╔╝ ██████╔╝██████╔╝█████╗███████║█████╗  ███████║███████║██║██║   ██║██║  ██║
██╔══██║  ╚██╔╝  ██╔═══╝ ██╔══██╗╚════╝╚════██║██╔══╝  ╚════██║╚════██║██║██║   ██║██║  ██║
██║  ██║   ██║   ██║     ██║  ██║      ███████║███████╗███████║███████║██║╚██████╔╝██║  ██║
╚═╝  ╚═╝   ╚═╝   ╚═╝     ╚═╝  ╚═╝      ╚══════╝╚══════╝╚══════╝╚══════╝╚═╝ ╚═════╝ ╚═╝  ╚═╝
```

### Native session restoration for Hyprland.

Bring back your workspaces.  
Bring back your windows.  
Continue exactly where you stopped.

**A KDE Plasma-like session restore experience for the Hyprland Wayland compositor.**

<br>

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![Hyprland](https://img.shields.io/badge/Hyprland-Wayland-purple)
![License](https://img.shields.io/badge/License-MIT-green)
![Status](https://img.shields.io/badge/status-active-success)

</div>

---

# Why hypr-session?

You close your laptop.

You reboot.

Everything is gone.

Your carefully arranged workspaces, terminals, editors, file managers, and apps disappear because Wayland currently has no universal session restoration protocol like the old X11 XSMP system.

KDE solved this internally.

Hyprland intentionally keeps things lightweight.

`hypr-session` fills that gap.

## The Idea

Most "session managers" try to control your desktop.

`hypr-session` does not.

It simply:

1. Takes a snapshot of your running environment.
2. Stores your window layout.
3. Restores everything during your next login.

No background daemon.

No constant polling.

No unnecessary magic.

---

# Demo



```text
$ hypr-session status

╭────────────── Saved Session ───────────────╮
│                                             │
│  Firefox        workspace 2       READY     │
│  Kitty          workspace 1       READY     │
│  VSCode         workspace 3       READY     │
│                                             │
╰─────────────────────────────────────────────╯
```

---

# Features

## Atomic Hyprland Restoration

Uses Hyprland dispatch rules:

```bash
[workspace 2 silent] firefox
```

Applications spawn directly into their saved workspace.

No window teleporting.

No flickering.

No ugly startup chaos.

---

## Smart Process Recovery

Hyprland knows windows.

Linux knows processes.

`hypr-session` connects both.

Uses:

```
hyprctl -j clients
        +
/proc/<pid>/cmdline
        +
XDG desktop mapping
```

to reconstruct how applications were launched.

---

## DBus Resistant Restore Engine

Modern applications are annoying.

Firefox, Dolphin, Electron apps, and Flatpaks often ignore simple launch rules because DBus handles the real process.

`hypr-session` tracks the created window address:

```text
0x55fa91ab3020
```

and forcefully restores the correct workspace.

---

## Terminal Directory Restore

Close your terminal inside:

```bash
~/Projects/kernel-driver/
```

Restore session.

Terminal opens again inside:

```bash
~/Projects/kernel-driver/
```

Supported:

- Kitty
- Alacritty
- Foot
- WezTerm

---

## Electron / Flatpak Friendly

Handles:

- VSCode
- Discord
- Obsidian
- Chromium apps
- sandbox wrappers
- renamed binaries

---

## Beautiful CLI

Powered by Rich.

Includes:

- colored dashboards
- progress animations
- session overview
- dry runs

---

# Installation

## Arch Linux (AUR)

If you are using Arch Linux, you can install the package directly from the AUR using your favorite helper:

```bash
yay -S hypr-session-git
```
Then, install the auto-start hooks:
```bash
hypr-session install-hooks
```

## PyPI (Universal)

For all other distributions (Ubuntu, Fedora, NixOS, etc.), we recommend using `pipx` to install `hypr-session` in an isolated environment.

**Arch Linux / EndeavourOS / Manjaro**
```bash
sudo pacman -S python-pipx
pipx install hypr-session
hypr-session install-hooks
```

**Fedora**
```bash
sudo dnf install pipx
pipx install hypr-session
hypr-session install-hooks
```

**Ubuntu / Debian**
```bash
sudo apt install pipx
pipx install hypr-session
hypr-session install-hooks
```

---

# Quick Install Script

If you want a fully automated installation that handles `pipx` configuration for you:

```bash
curl -sSL https://raw.githubusercontent.com/krishiv2489/hypr-session/main/install.sh | bash
```

---

# Usage

## Workspace Profiles

Save a named layout once:

```bash
hypr-session save --profile study
```

Restore it with a keybind. Add to `~/.config/hypr/hyprland.conf`:

```conf
# SUPER + SHIFT + S restores your Study layout instantly
bind = SUPER SHIFT, S, exec, hypr-session restore --profile study
```

Create as many profiles as you need:

```bash
hypr-session save --profile gaming
hypr-session save --profile coding
hypr-session save --profile music
```

Each profile is a separate JSON file and can be exported, shared, or version-controlled.

## Basic Commands

Save current session:

```bash
hypr-session save
```

Restore:

```bash
hypr-session restore
```

Preview without opening apps:

```bash
hypr-session restore --dry-run
```

Show dashboard:

```bash
hypr-session status
```

List profiles:

```bash
hypr-session list
```

Compare your active desktop to the saved session:

```bash
hypr-session diff
```

Diagnose system issues:

```bash
hypr-session doctor
```

Pause automatic saving:

```bash
hypr-session pause
hypr-session pause --permanent
```

---

# Commands

| Command             | Description                      |
| ------------------- | -------------------------------- |
| `save`              | Snapshot current desktop         |
| `restore`           | Restore saved session            |
| `diff`              | Compare active vs saved windows  |
| `status`            | View saved windows               |
| `list`              | Show saved sessions              |
| `rename`            | Rename a session profile         |
| `copy`              | Duplicate a session profile      |
| `export`            | Export session to JSON           |
| `import`            | Import session from JSON         |
| `doctor`            | Run system diagnostics           |
| `pause`             | Disable temporary/permanent save |
| `install-hooks`     | Configure Hyprland automatically |

---

# Hyprland Integration

Auto restore:

```conf
exec-once = hypr-session restore --wait
```

Save before exit:

```conf
bind = SUPER SHIFT, Q, exec, hypr-session save && hyprctl dispatch exit
```

---

# How It Works

## Saving

```
Hyprland IPC
      |
      v
hyprctl clients
      |
      v
Window PID
      |
      v
Linux /proc
      |
      v
Session JSON
```

Example saved entry:

```json
{
  "class": "kitty",
  "workspace": 1,
  "cmd": "kitty",
  "size": [900, 600]
}
```

---

## Restoring

```
Session JSON
      |
      v
Launch application
      |
      v
Detect new window
      |
      v
Apply Hyprland rules
```

---

# Project Structure

```text
hypr-session/

├── src/
│   └── hypr_session/
│
│       ├── models.py
│       │   Data structures
│
│       ├── session.py
│       │   Save engine
│
│       ├── restore.py
│       │   Restore engine
│
│       ├── mapping.py
│       │   Application detection
│
│       ├── config.py
│       │   User configuration
│
│       └── cli.py
│           Terminal interface
│
├── tests/
├── pyproject.toml
└── README.md
```

---

# Philosophy

A window manager cannot know what is inside an application.

Browsers restore browser tabs.

Editors restore files.

Terminals restore shell locations.

`hypr-session` restores the desktop environment around them.

Small tools.

Clear boundaries.

Unix philosophy.

---

# Roadmap

## v1.0 ✅

- [x] Named profiles

```bash
hypr-session save --profile gaming
hypr-session restore --profile coding
```

- [x] DBus-resistant restore engine

- [x] Terminal CWD restoration

- [x] Rich CLI with progress bars

- [x] Dry-run mode

- [x] Auto-hook installer (`install-hooks`)

- [x] AUR package

- [x] PyPI release

## v1.x

- [ ] Hyprland groups / tabbed layout support

- [ ] Special workspace restoration

- [ ] Socket event listener for auto-save

---

# Contributing

Contributions are welcome.

Useful contributions:

- application mappings
- bug fixes
- distro testing
- restore improvements

Development:

```bash
git clone https://github.com/krishiv2489/hypr-session

cd hypr-session

python -m venv .venv

source .venv/bin/activate

pip install -e ".[dev]"

pytest
```

---

# Author

Created by **Krishiv Patel**

GitHub: `@krishiv2489`

---

# License

MIT License.

Use it.

Modify it.

Break it.

Improve it.

```

```
