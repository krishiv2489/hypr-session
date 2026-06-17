# Codebase Audit Report: hypr-session

This report presents a comprehensive audit of the `hypr-session` codebase, focusing on cross-distribution robustness, UI/UX ideation, and test suite status/gaps.

---

## 1. Cross-Distribution Robustness (R1)

The audit of `install.sh`, system command assumptions, dependencies, config parsing, and runtime behavior revealed several critical bottlenecks that limit the reliability and cross-distro compatibility of `hypr-session`.

### 1.1 Flatpak & Snap Command Resolution Deficiencies (Critical)
*   **The Flatpak Bug (`mapping.py`)**: 
    *   In `build_desktop_map()`, desktop entries are skipped if their binary is in `_IGNORE_EXE_FRAGMENTS` (which includes `"flatpak"`, `"bwrap"`, `"electron"`, etc.).
    *   Flatpak applications (e.g., Spotify, Discord) have desktop entries with `Exec` lines pointing to `/usr/bin/flatpak` or `/usr/bin/bwrap`. As a result, `_parse_exec_command` extracts `"flatpak"` as the binary, and the entire desktop entry is skipped.
    *   Furthermore, `_parse_exec_command` splits the command on spaces and only takes the first word, which strips out the application ID (e.g., `com.spotify.Client`). Thus, even if they weren't skipped, the command resolved would just be `flatpak` with no arguments, failing to launch the actual application.
*   **Missing Search Paths**:
    *   **Snaps**: The directory `/var/lib/snapd/desktop/applications/` is completely omitted from `_DESKTOP_SEARCH_DIRS`. Users on Ubuntu or other Snap-heavy distributions will experience broken mappings.
    *   **NixOS**: NixOS stores desktop entries in `/run/current-system/sw/share/applications/` and `~/.nix-profile/share/applications/`. These paths are not checked, preventing NixOS users from resolving commands.

### 1.2 Path Resolution Issues for Startup Hooks (High)
*   The `install-hooks` command injects `exec-once = hypr-session restore --wait` and `hypr-session save ; hyprctl dispatch exit` into `hyprland.conf`.
*   This assumes `hypr-session` is globally available in the PATH. Since `pipx` installs the package to `~/.local/bin`, this directory is frequently missing from the display manager's non-interactive/non-login shell environment. This leads to silent hook execution failures during startup and exit.
*   *Solution*: The installer should write the absolute path to the `hypr-session` executable (e.g., resolved using `sys.executable` or `shutil.which`) directly into the configuration hooks.

### 1.3 Fragile `hyprland.conf` Parsing (Medium)
*   **Modular Configs Ignored**: Modern Hyprland configurations commonly split settings across multiple files using `source = <path>`. The current `install_hooks` logic only scans `~/.config/hypr/hyprland.conf` and ignores `source` statements.
*   **Regex Fragility**: The regular expression `r',\s*(dispatch\s+)?exit\s*$'` matches the exit bind, but it fails if there are trailing comments (e.g. `bind = $mainMod, M, exit # exit config`) or alternative ways of exiting Hyprland (e.g., `exec, killall Hyprland` or `exec, hyprctl dispatch exit`).
*   **Backup Overwrite Risk**: Running `install-hooks` multiple times repeatedly copies `hyprland.conf` to `hyprland.conf.bak`, overwriting the original backup with the modified configuration.

### 1.4 System Command & `/proc` Assumptions (Medium)
*   **Blocking Restore Loop**: Restoration is completely synchronous and sequential. It loops through windows, runs `hyprctl dispatch exec`, polls `_wait_for_new_address` (with up to a 10s timeout), and sleeps for `0.4` seconds (plus an inter-launch delay of `0.3` seconds). A single slow-launching app can block the entire session restore process.
*   **Terminal CWD Resolution Collisions**: For multi-window or daemonized terminal emulators (e.g., Kitty, Wezterm), all windows share the same master PID. `get_terminal_cwd` fetches children of this master PID and takes `children[-1]` as the active shell. In a multi-window terminal setup, this heuristic frequently grabs the CWD of a completely different terminal window.
*   **Linux-Strict `/proc` Access**: Reading `/proc` directly restricts this tool to Linux. Although FreeBSD and other BSDs run Hyprland, they lack `/proc` by default or format it differently, causing runtime failures.

### 1.5 Configuration Parsing & Dependency Robustness (Low)
*   **Silent Failures**: `load_config` in `config.py` catches all exceptions during `tomllib.loads` and silently returns the default configuration. A user with a syntax error in their config is never warned.
*   **No tomllib Fallback**: `config.py` has a try-except block for `tomllib` but defines no fallback (e.g. `tomli`). Running the tool on python < 3.11 results in a `NameError` on `tomllib.loads` rather than a clean exit message.

---

## 2. Feature & UX/UI Ideation (R2)

To deliver a premium, modern terminal experience, the following CLI features and UX improvements are proposed:

### 2.1 Side-by-Side Visual Session Diff
Enhance `hypr-session diff` to show a side-by-side comparison of the saved state vs. the active state using Rich columns, highlighting mismatches with intuitive color codes:
*   **Green**: Active window matches saved state.
*   **Red**: Window is missing in the active state (present in saved).
*   **Yellow**: Window class matches, but geometry (position, size) or properties (floating, fullscreen) differ.
*   **Cyan**: New window present in active state (not present in saved).

### 2.2 Dashboard-style Concurrent Restore
Replace the slow, sequential restoration loop with an asynchronous/concurrent launch engine and display a live Dashboard:
*   Use `rich.live` to show a progress table of all windows being restored concurrently.
*   Display status states for each window: `[Pending ⏳] -> [Launching 🚀] -> [Mapping 🔍] -> [Restored ✅]`.
*   This would eliminate redundant sleep timers and cut the restoration time for a 10-window session from ~8 seconds to less than 2 seconds.

### 2.3 Selective Save/Restore
Introduce targeted command flags to give users finer control:
*   `hypr-session restore --workspace 1,2` (only restore windows on workspaces 1 and 2).
*   `hypr-session restore --exclude firefox` (skip restoring specific window classes).
*   `hypr-session save --only-current` (only save windows on the currently active workspace).
*   `hypr-session save --interactive` (prompt the user to toggle which open windows they want to include).

### 2.4 Auto-Save Daemon Mode
Introduce `hypr-session daemon` to run in the background:
*   Listens to Hyprland socket events (`openwindow`, `closewindow`, `movewindow`).
*   Periodically autosaves state to a special `.autosave` profile.
*   If the system crashes or experiences sudden power loss, the user can recover their exact workspace layouts on boot using `hypr-session restore --profile .autosave`.

### 2.5 Profile Management Commands
*   `hypr-session rename <old> <new>`: Rename an existing session profile.
*   `hypr-session duplicate <profile> <new>`: Clone a profile.
*   `hypr-session export <profile> <file.json>` / `hypr-session import <file.json> <profile>`: Easily share configurations and layouts across machines.

---

## 3. Test Suite Status and Gaps (R3)

The existing test suite contains **49 passing tests** that execute in under 0.03 seconds. While they cover core serialization and basic command resolution, there are major coverage gaps regarding real-world behavior and system level interactions.

### 3.1 Current Test Coverage
*   `test_mapping.py`: Tests basic desktop entry field parsing, placeholder stripping, and resolution priority stages (1 to 4).
*   `test_models.py`: Tests JSON serialization/deserialization for `WindowEntry`, `Session`, and `FullscreenState` enums.
*   `test_restore.py`: Tests window rule building for tiling, floating, and basic directory arguments (`--directory`) for terminal emulators.

### 3.2 Key Gaps Identified
1.  **No System / `/proc` Mocking**:
    *   Crucial, OS-level utility functions in `utils.py`—such as `get_terminal_cwd()`, `get_ancestor_pids()`, and `get_exe_path()`—are completely untested.
    *   *Recommendation*: Implement tests using mocked `/proc` directory structures (e.g., using `pytest`'s `tmp_path` to simulate `/proc/<pid>/status`, `/proc/<pid>/exe`, and `/proc/<pid>/cwd` symlinks).
2.  **No Integration or CLI Runner Tests**:
    *   There are no tests for the `cli.py` entrypoint. The commands (`save`, `restore`, `list`, `status`, `diff`, `doctor`, `install-hooks`) are never executed during tests.
    *   *Recommendation*: Add CLI integration tests using Typer's `CliRunner` to check exit codes, correct option handling, and stdout/stderr outputs.
3.  **No Mocking of the Restore Generator**:
    *   The `restore_session` generator in `restore.py` is the core execution pipeline. It remains completely untested.
    *   *Recommendation*: Mock `subprocess.run` and `run_hyprctl` to verify that `restore_session` fires the exact sequence of `hyprctl dispatch` commands for complex window layouts.
4.  **No Config Error / Type Handling Tests**:
    *   `config.py` parsing logic (`load_config`) is untested. There are no tests to verify how the application responds to malformed/invalid config files.
5.  **No Backup Rotation Tests**:
    *   The backup rotation scheme (which keeps the last 10 session backups) in `save_session` has no test coverage.
