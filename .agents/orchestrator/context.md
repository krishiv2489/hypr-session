# Comprehensive Codebase Audit Synthesis

## 1. Cross-Distro Robustness (R1)
- **Hardcoded Desktop Search Paths**:
  - Currently in `src/hypr_session/mapping.py` (lines 13-19).
  - *Fix*: Resolve dynamically using `os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")` and `os.environ.get("XDG_DATA_HOME", "~/.local/share")`. Append NixOS (`/run/current-system/sw/share/applications`, `~/.nix-profile/share/applications`) and Snaps (`/var/lib/snapd/desktop/applications`) search paths.
- **Flatpak Executable Mapping Bug**:
  - Flatpaks use `flatpak run` commands. In `mapping.py`, their binaries are ignored because `flatpak` is in `_IGNORE_EXE_FRAGMENTS`. Additionally, `_parse_exec_command` splits on spaces and only takes the first word, which strips out the Flatpak application ID (e.g. `com.spotify.Client`).
  - *Fix*: Handle Flatpak desktop entry executables correctly: extract the application ID or executable name, and do not ignore `flatpak` if it has trailing app ID arguments.
- **Insecure `/tmp` Fallback**:
  - `config.py` uses `/tmp/hypr-session-{os.getuid()}.paused` when `/run/user/{os.getuid()}` doesn't exist. This fallback is susceptible to symlink/DoS attacks on non-systemd distros.
  - *Fix*: Use `os.environ.get("XDG_RUNTIME_DIR")` first. If resorting to `/tmp`, create a secure, user-only subdirectory (e.g., `mode=0o700`) and place lock files inside it.
- **Hook Installer Issues**:
  - Pipx installs `hypr-session` to `~/.local/bin`. The installer injects hooks using `hypr-session`, which is missing from systemd/DM non-login PATHs.
  - *Fix*: Resolve the absolute path of the executing `hypr-session` binary (e.g. using `sys.argv[0]` or `shutil.which`) and write that absolute path into `hyprland.conf` hooks.
  - Respect `$XDG_CONFIG_HOME` when resolving `hyprland.conf` path.
  - Regex for exit bind is fragile and fails with trailing comments. Update to: `r',\s*(dispatch\s+)?exit\s*(?:#.*)?$'`.
  - Fix backup rotation in hook installer to avoid overwriting original backup if run multiple times.
- **Config parsing NameError / Silence**:
  - `config.py` catches all config loading exceptions silently. It also fails to define a fallback for `tomllib` on Python < 3.11.
  - *Fix*: Print a stderr warning when config parsing fails. Try loading `tomli` as a fallback for `tomllib`.

## 2. Feature & UX/UI Ideation (R2)
- **Broken `diff` Command Logic**:
  - Currently compares sets of `f"{workspace_id}:{class}"` which misses duplicate windows of the same class on the same workspace.
  - *Fix*: Use `collections.Counter` to track instance counts and display a side-by-side comparison table of Saved vs Current status.
- **Beautiful Side-by-Side Visual Diff Table**:
  - Refactor `diff` command using Rich to show a visual comparison grid.
  - Add color coding: Green (matched), Red (missing from current), Cyan (new/extra), Yellow (position/state mismatched).
- **Dashboard-style Restoration (Verbose/Progress)**:
  - Add a `--verbose` flag to see details, and visual progress indicator when launching and waiting for windows.
- **Targeted Flags for Save & Restore**:
  - `restore --workspace 1,2`: Only restore windows on workspaces 1 and 2.
  - `restore --exclude "firefox,chrome"`: Exclude specific window classes.
  - `save --only-active`: Save only windows on the active workspace.
- **Session Utilities**:
  - `rename <old> <new>`: Rename session JSON file.
  - `copy <src> <dest>`: Duplicate session profile.
  - `export <profile> <file.json>` / `import <file.json> -p <profile>`: Import/Export.
- **Dashboard Status Layout**:
  - Refactor `hypr-session status` to display a clean Rich `Tree` of monitors, workspaces, and windows.

## 3. Test Suite Status & Gaps (R3)
- **High-priority gaps**:
  - No tests for `/proc` parsing (`utils.py`). Need to mock `/proc` filesystem or its functions.
  - No tests for CLI commands (`cli.py`). Need to test with `typer.testing.CliRunner`.
  - No tests for save/load/rotate session files (`session.py`).
  - No tests for restoration execution engine (`restore.py`).
