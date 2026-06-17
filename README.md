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

> Add demo GIF here

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

## Arch Linux / EndeavourOS / Manjaro

```bash
sudo pacman -S python-pipx

pipx install git+https://github.com/krishiv2489/hypr-session.git

hypr-session install-hooks
```

## Fedora

```bash
sudo dnf install pipx

pipx install git+https://github.com/krishiv2489/hypr-session.git

hypr-session install-hooks
```

## Ubuntu / Debian

```bash
sudo apt install pipx

pipx install git+https://github.com/krishiv2489/hypr-session.git

hypr-session install-hooks
```

---

# Quick Install

```bash
curl -sSL https://raw.githubusercontent.com/krishiv2489/hypr-session/main/install.sh | bash
```

---

# Usage

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

Pause automatic saving:

```bash
hypr-session pause
```

---

# Commands

| Command             | Description                      |
| ------------------- | -------------------------------- |
| `save`              | Snapshot current desktop         |
| `restore`           | Restore saved session            |
| `restore --dry-run` | Simulate restoration             |
| `status`            | View saved windows               |
| `list`              | Show saved sessions              |
| `pause`             | Disable temporary saving         |
| `install-hooks`     | Configure Hyprland automatically |

---

# Hyprland Integration

Auto restore:

```conf
exec-once = hypr-session restore
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

## v1.x

- [ ] Named profiles

```bash
hypr-session save gaming
hypr-session restore coding
```

- [ ] Hyprland groups support

- [ ] Special workspace restoration

- [ ] Socket event listener

- [ ] AUR package

- [ ] PyPI release

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
