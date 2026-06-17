# hypr-session

> Session save and restore for the [Hyprland](https://hyprland.org) Wayland compositor.

Close your laptop. Open it again. Everything is back where you left it.

---

## What it does

Hyprland does not have built-in session restoration. `hypr-session` fills that gap.

Before you shut down, it captures:

- Which applications are open
- Which workspace each window is on
- Whether each window is floating (and its exact position and size)
- Whether each window is fullscreen or maximized
- The working directory of any open terminal windows

On next boot, it relaunches every app and places each window back on its workspace — automatically.

---

## Demo

```
$ hypr-session status

─── hypr-session status ─────────────────────────────
  Auto-save:    active
  Config file:  /home/user/.config/hypr-session/config.toml
  Data dir:     /home/user/.local/share/hypr-session/

─── Saved Sessions ──────────────────────────────────
  [default]  3 window(s)  saved: 2026-06-15T23:41:02
       ws1  firefox                        cmd=firefox
       ws2  org.kde.dolphin               cmd=dolphin
       ws3  kitty                          cmd=kitty --directory '/home/user/projects'
```

---

## 📦 Installation

We provide an automated installation script that securely installs the package and automatically configures your `hyprland.conf` to restore on boot and save on exit.

Run the following command in your terminal:

```bash
curl -sSL https://raw.githubusercontent.com/krishiv2489/hypr-session/main/install.sh | bash
```

**Verify the install:**

```
hypr-session --help
```

---

## Setup (2 lines in hyprland.conf)

Open `~/.config/hypr/hyprland.conf` and add:

```
# 1. Restore your last session automatically on every login
exec-once = hypr-session restore

# 2. Override your exit keybind to save BEFORE Hyprland closes
#    Change SUPER SHIFT Q to whatever your exit bind is
bind = SUPER SHIFT, Q, exec, hypr-session save && hyprctl dispatch exit
```

That is it. Next time you log out and back in, your windows will be back.

---

## Usage

```bash
hypr-session save                  # save the current session (default profile)
hypr-session save --profile work   # save a named session profile
hypr-session restore               # restore the default session
hypr-session restore --profile work
hypr-session list                  # show all saved sessions
hypr-session clear                 # delete the default saved session
hypr-session clear --all           # delete all saved sessions
hypr-session pause                 # disable auto-save for this logout only
hypr-session resume                # re-enable auto-save
hypr-session status                # show full status and config
hypr-session config                # create a default config file
```

---

## Configuration

Run `hypr-session config` to create the config file, then edit it:

```
~/.config/hypr-session/config.toml
```

```toml
[general]
# Seconds to wait after Hyprland starts before restoring.
# Increase this if windows land on the wrong workspace.
restore_delay_seconds = 2.0

# Seconds to wait for each window to appear.
# Firefox can take 8-10 seconds on a cold start.
window_wait_timeout = 12.0

# Restore floating windows with their exact position and size.
restore_floating = true

# Reapply fullscreen/maximize state after launch.
restore_fullscreen = true

# Restore the working directory of terminal windows.
restore_cwd = true

[ignore]
# Additional window classes to never save.
# Built-in ignores: mpv, vlc, waybar, dunst, hyprpaper, and others.
# classes = ["obsidian", "steam"]
```

---

## Known limitations

**These are by design, not bugs:**

- **Terminal history is not restored.** The command history inside a terminal session exists only in that shell's memory. `hypr-session` restores the working directory (e.g. you'll be back in `/home/user/projects/`), but not the commands you ran.

- **Browser tabs are not managed.** Firefox and Chrome have their own session restore. They reopen their tabs automatically. `hypr-session` opening Firefox is enough — the browser handles the rest.

- **Media players are intentionally excluded.** mpv and VLC embed the file path in their launch arguments. Restoring them would restart the video from 0:00. They are in the default ignore list.

- **Tiling layout is approximate, not pixel-perfect.** Hyprland's tiling algorithm places windows based on insertion order. `hypr-session` preserves the order, so the general layout (which window is left/right/top/bottom) is correct. The exact split ratios may differ slightly.

- **Flatpak apps may not resolve correctly.** Flatpak sandboxes the binary path, making `/proc/<pid>/exe` resolve to a Flatpak runner rather than the app. Add Flatpak apps to your `[ignore]` list or manually specify the command using a named profile.

---

## How it works

1. **Save**: Queries `hyprctl -j clients` to get all windows with their workspace, position, size, and fullscreen state. For each window, reads `/proc/<pid>/exe` to get the real binary name. For terminal windows, reads `/proc/<childpid>/cwd` to get the shell's working directory. Serializes everything to JSON.

2. **Restore**: Reads the JSON, builds a Hyprland dispatch exec rule per window (e.g. `[workspace 2 silent; float; move 560 200; size 900 600] pavucontrol`), and fires each rule via `hyprctl dispatch exec`. Polls for each window to appear using a before/after address diff on `hyprctl -j clients`. Windows with identical class names (e.g. two Kitty terminals) are restored sequentially so they can be tracked individually by address.

3. **Command resolution**: Uses a three-stage fallback — (1) `/proc/<pid>/exe` basename, (2) XDG `.desktop` file `StartupWMClass` field, (3) bundled `class_map.json` for known Electron apps and KDE/GNOME apps.

---

## Requirements

- Python 3.11+
- Hyprland (any recent version)
- `hyprctl` in PATH (installed with Hyprland)
- `typer` Python package (auto-installed as dependency)

---

## Contributing

Issues and PRs are welcome. If your app doesn't restore correctly, the most useful thing you can provide is the output of:

```bash
hypr-session status
cat /proc/$(pidof yourapp | awk '{print $1}')/cmdline | tr '\0' '\n'
ls -la /proc/$(pidof yourapp | awk '{print $1}')/exe
```

This tells us exactly what the tool sees and helps fix the mapping.

---

## License

MIT — see [LICENSE](LICENSE).
