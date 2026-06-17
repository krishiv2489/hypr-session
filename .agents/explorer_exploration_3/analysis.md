# Codebase Audit Report: hypr-session

**Date:** 2026-06-17  
**Scope:** Cross-Distro Robustness (R1), Feature & UX/UI Ideation (R2), and Test Suite Gaps (R3) for the `hypr-session` codebase at `/home/krishiv/Study/Python_Projects/hypr-session`.

---

## 1. Executive Summary
`hypr-session` is a lightweight session manager for Hyprland that avoids background daemons and leverages Hyprland IPC rules paired with Linux `/proc` inspections to restore tiling/floating window layouts and terminal working directories. 

While the architecture is elegant, this audit identifies several critical issues:
1. **Cross-Distro Robustness (R1)**: Hardcoded desktop search directories break functionality on NixOS, Flatpaks, and Ubuntu Snaps. Non-systemd distros fall back to insecure `/tmp` locking. Sequential restore polling blocks startup on slow or broken apps.
2. **UX/UI & Feature Gaps (R2)**: The `diff` command has a major logic bug that fails to detect missing/new windows if another window of the same class is present. The CLI lacks interactive management and automatic background saving.
3. **Testing Gaps (R3)**: The test suite lacks unit tests for the core save engine, IPC execution, directory scanning, procfs parser, and CLI hook injector.

---

## 2. Cross-Distribution Robustness (R1)

### A. Hardcoded Desktop Search Directories
* **Location:** `src/hypr_session/mapping.py` (lines 13-19)
* **Code:**
  ```python
  _DESKTOP_SEARCH_DIRS: list[Path] = [
      Path.home() / ".local" / "share" / "applications",
      Path("/usr/local/share/applications"),
      Path("/usr/share/applications"),
      Path("/var/lib/flatpak/exports/share/applications"),
      Path.home() / ".local" / "share" / "flatpak" / "exports" / "share" / "applications",
  ]
  ```
* **Robustness Issue:** This hardcoded list completely ignores `$XDG_DATA_DIRS` which is the standard Wayland/XDG way to resolve application directories. 
  * **NixOS:** NixOS installs application desktop files in non-standard paths like `/run/current-system/sw/share/applications` and `~/.nix-profile/share/applications`. None of these are scanned, so `StartupWMClass` matching fails entirely on NixOS.
  * **Snaps:** Ubuntu Snaps place desktop entries in `/var/lib/snapd/desktop/applications` which is not scanned.
* **Proposed Fix:** Re-write directory collection to parse the `$XDG_DATA_DIRS` environment variable, falling back to standard paths:
  ```python
  import os
  xdg_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
  search_dirs = [Path(d) / "applications" for d in xdg_dirs.split(":") if d]
  search_dirs.append(Path.home() / ".local" / "share" / "applications")
  # Filter only existing directories
  _DESKTOP_SEARCH_DIRS = [p for p in search_dirs if p.exists()]
  ```

### B. Insecure `/tmp` Fallback on Non-Systemd Systems
* **Location:** `src/hypr_session/config.py` (lines 22-26)
* **Code:**
  ```python
  _run_user_dir = Path(f"/run/user/{os.getuid()}")
  if _run_user_dir.exists():
      RUNTIME_PAUSE_LOCK = _run_user_dir / "hypr-session.paused"
  else:
      RUNTIME_PAUSE_LOCK = Path(f"/tmp/hypr-session-{os.getuid()}.paused")
  ```
* **Robustness Issue:** Non-systemd distributions (Artix, Alpine, Void Linux running OpenRC/runit/s6) do not have `/run/user/<uid>` populated. The fallback to `/tmp/hypr-session-{os.getuid()}.paused` is susceptible to symbolic link attacks and local denial-of-service (if another user creates the file first).
* **Proposed Fix:** Create a dedicated directory under `$XDG_RUNTIME_DIR` or use `tempfile.gettempdir()` securely with user-only permissions.

### C. NameError in Config Loading on older Python Environments
* **Location:** `src/hypr_session/config.py` (lines 10-13, 108)
* **Code:**
  ```python
  try:
      import tomllib  # Python 3.11+
  except ImportError:
      pass
  ...
  data = tomllib.loads(CONFIG_FILE.read_text())
  ```
* **Robustness Issue:** If the python runtime fails to import `tomllib`, it passes silently. However, line 108 calls `tomllib.loads` which throws a `NameError: name 'tomllib' is not defined`.
* **Proposed Fix:** Use a clean fallback like `tomli` or raise a user-friendly error immediately if `tomllib` is unavailable:
  ```python
  try:
      import tomllib
  except ImportError:
      try:
          import tomli as tomllib
      except ImportError:
          # Handle gracefully or define a fallback parser
  ```

### D. Single-Process Multi-Window CWD Resolution Limitations
* **Location:** `src/hypr_session/utils.py` (lines 96-121)
* **Code:**
  ```python
  def get_terminal_cwd(terminal_pid: int) -> str | None:
      ...
      children = [
          int(p.name)
          for p in Path("/proc").iterdir()
          if p.name.isdigit()
          and Path(f"/proc/{p.name}/status").exists()
          and _read_ppid(int(p.name)) == terminal_pid
      ]
      ...
      child_pid = children[-1]
      return str(Path(f"/proc/{child_pid}/cwd").resolve())
  ```
* **Robustness Issue:** Terminals like Kitty and WezTerm operate in a single-process multi-window model. When multiple terminal windows are open, they all report the *same* PID to Hyprland.
  1. `get_terminal_cwd` queries children of that single master PID.
  2. `children[-1]` uses the last PID from a directory listing of `/proc` (which is filesystem-dependent and not guaranteed to be sorted by PID or window association).
  3. Consequently, all Kitty/WezTerm windows are assigned the same directory upon restore, overriding individual tab/window context.
* **Proposed Fix:** For single-process terminals, attempt to query their IPC socket (e.g. `kitty @ ls` or `wezterm cli list`) if available, or document this as a known structural limitation.

### E. Blocking Restore Loop on Heavy I/O or Slow Launches
* **Location:** `src/hypr_session/restore.py` (lines 108-141)
* **Robustness Issue:** Restoring is sequential. For each window, the program launches it and polls `_wait_for_new_address` up to `window_wait_timeout` (default 10s). If an application is slow, fails to launch, or has an unmapped class, the entire boot restore process stalls. If three apps fail, the user waits 30 seconds.
* **Proposed Fix:** Launch applications in parallel or run the wait-and-place logic inside a thread pool, allowing fast-starting apps to render instantly without being blocked by slower apps.

### F. Broken Path Injection Fallback in Installer
* **Location:** `install.sh` (lines 42, 50-57)
* **Code:**
  ```bash
  pipx ensurepath > /dev/null 2>&1
  ...
  if command -v hypr-session &> /dev/null; then
      hypr-session install-hooks
  elif [ -x "$HOME/.local/bin/hypr-session" ]; then
  ```
* **Robustness Issue:** `pipx ensurepath` updates shell configuration files (`.bashrc`, `.zshrc`) but does *not* affect the current executing environment of `install.sh`. Thus, `command -v hypr-session` will always fail on new installations. Furthermore, if the user has defined a custom `PIPX_BIN_DIR`, the fallback checking `$HOME/.local/bin/hypr-session` will also fail, leaving the user with an incomplete hook installation.
* **Proposed Fix:** Read `PIPX_BIN_DIR` from the environment or parse pipx config output to locate the correct installation path.

---

## 3. Feature & UX/UI Ideation (R2)

### A. Broken `diff` Command Logic (Instance Count Bug)
* **Location:** `src/hypr_session/cli.py` (lines 305-328)
* **Bug:**
  ```python
  saved_keys = {f"{w.workspace_id}:{w.initial_class}" for w in saved_session.windows}
  current_keys = {f"{w.workspace_id}:{w.initial_class}" for w in current_windows}
  missing = saved_keys - current_keys
  new = current_keys - saved_keys
  ```
  If you have two `kitty` windows saved on workspace 1, and you close one of them:
  * `saved_keys` = `{"1:kitty"}`
  * `current_keys` = `{"1:kitty"}`
  * `missing` = `set()`
  * `new` = `set()`
  The `diff` command reports that the active desktop matches the saved session perfectly, which is false.
* **Proposed Visual Diff Refactor:** Use a `Counter` to compare exact instance counts and display a side-by-side table:
  ```python
  from collections import Counter
  saved_counts = Counter((w.workspace_id, w.initial_class) for w in saved_session.windows)
  current_counts = Counter((w.workspace_id, w.initial_class) for w in current_windows)
  # Show exact counts (+1, -1) in the diff table
  ```

### B. Suggested UX/UI Enhancements
1. **Interactive Session Editor**:
   Add `hypr-session edit` using a `rich.live` dashboard or `questionary` selection. This lets users manually remove specific windows from a saved session or re-assign their workspace without manually editing raw JSON files.
2. **Visual Workspace Map**:
   Improve `status` and `diff` commands by printing a textual layout representation of the monitors and workspaces.
   Example:
   ```text
   Monitor DP-1:
   ┌── Workspace 1 ──────────┐  ┌── Workspace 2 ──────────┐
   │ [firefox]  [kitty]      │  │ [spotify]               │
   └─────────────────────────┘  └─────────────────────────┘
   ```
3. **Autosave Event Listener (Daemon Mode)**:
   Implement `hypr-session watch`. Using Python's `asyncio`, it listens to Hyprland's Event Socket (`$HYPRLAND_INSTANCE_SIGNATURE/.socket2.sock`) for events like `openwindow` and `closewindow`. It performs a debounced save operation to keep the default session constantly updated in the background.
4. **Additional Command Flags**:
   * `hypr-session save --only-active-workspace`: Saves only windows on the current focused workspace.
   * `hypr-session restore --exclude "spotify,discord"`: Restores the session but skips specific heavy/web applications.
   * `hypr-session restore --interactive`: Prompts the user (`[y/N]`) before launching each window.

---

## 4. Test Suite Status and Gaps (R3)

### Current Status
The project has a basic test suite with 21 unit tests across 3 files:
* `test_models.py`: Verifies serialization round-trips for `WindowEntry` and `Session`.
* `test_mapping.py`: Tests `_extract_field`, `_parse_exec_command`, and the stage-based `resolve_command` logic.
* `test_restore.py`: Verifies `_build_cwd_cmd` and `_build_dispatch_arg`.

### Test Suite Gaps
There are significant parts of the system that are completely untested. The following files and modules have zero test coverage:

1. **`src/hypr_session/session.py` (0% Coverage)**:
   * **`get_current_session_windows`**: Needs tests mocking `run_hyprctl("clients")` to ensure class filters (`ignore_classes`), content types (`ignore_content_types`), swallowing, and ancestor PIDs filter out the calling process successfully.
   * **`save_session`**: No test verifies file writes, directory creations, or the backup rotation logic (keeping only the last 10 backups).
   * **`load_session` / `list_sessions`**: No tests verify behavior when handling corrupt JSON, missing files, or mismatched schema versions.

2. **`src/hypr_session/utils.py` (0% Coverage)**:
   * **Procfs Parsers**: `_read_ppid`, `get_ancestor_pids`, and `get_terminal_cwd` need tests that mock the `/proc` filesystem (e.g. using `pyfakefs`) to verify they don't crash under permission errors or unexpected file contents.
   * **IPC wrappers**: `run_hyprctl` has no tests validating error handling during `CalledProcessError` or parsing failure.

3. **`src/hypr_session/mapping.py` (Partially Untested)**:
   * **`build_desktop_map`**: Scanning `.desktop` files from search paths is completely untested. Tests should mock the file directories and verify that `NoDisplay` is ignored, and `StartupWMClass` is mapped correctly.

4. **`src/hypr_session/cli.py` (0% Coverage)**:
   * Typer commands (`save`, `restore`, `diff`, `doctor`, `pause`, etc.) have no integration tests. These should be tested using `typer.testing.CliRunner`.
   * **`install-hooks`**: No test verifies the regex modification of `hyprland.conf` or backup generation.
