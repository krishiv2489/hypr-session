# hypr-session Codebase Audit Report

## Executive Summary
This report presents an audit of the `hypr-session` codebase located at `/home/krishiv/Study/Python_Projects/hypr-session`. The audit evaluates three major areas:
1. **Cross-Distro Robustness (R1)**: Analyzing portability, dependency management, install hooks, config parsing, and runtime environments.
2. **Feature & UX/UI Ideation (R2)**: Proposing CLI improvements, status panels, diff visualizations, and new flags.
3. **Test Suite Status & Gaps (R3)**: Examining existing unit tests and outlining current gaps in test coverage.

---

## 1. Cross-Distro Robustness (R1)

The audit identified several areas where the codebase makes assumptions that could break on non-Arch distributions, alternative init systems (non-systemd), or custom desktop setups.

### 1.1 Hardcoded Application Search Paths (NixOS / Custom XDG Data Paths)
* **File & Lines**: `src/hypr_session/mapping.py` (lines 13-19)
* **Verbatim Code**:
  ```python
  _DESKTOP_SEARCH_DIRS: list[Path] = [
      Path.home() / ".local" / "share" / "applications",
      Path("/usr/local/share/applications"),
      Path("/usr/share/applications"),
      Path("/var/lib/flatpak/exports/share/applications"),
      Path.home() / ".local" / "share" / "flatpak" / "exports" / "share" / "applications",
  ]
  ```
* **Robustness Issue**: On declarative distributions like **NixOS**, packages are installed in the Nix store, and active desktop entries are exposed via `/run/current-system/sw/share/applications` or `~/.nix-profile/share/applications`. Because the search paths are hardcoded, `hypr-session` will fail to resolve class-to-command mappings on NixOS, fallback to standard binary execution, and fail if the binary name doesn't match the class name.
* **Resolution**: Construct the search list dynamically by splitting the `XDG_DATA_DIRS` environment variable (defaulting to `/usr/local/share:/usr/share`) and appending `/applications` to each segment, while also respecting `XDG_DATA_HOME` (defaulting to `~/.local/share`).

### 1.2 Systemd-Specific Runtime Directory Assumption
* **File & Lines**: `src/hypr_session/config.py` (lines 22-26)
* **Verbatim Code**:
  ```python
  _run_user_dir = Path(f"/run/user/{os.getuid()}")
  if _run_user_dir.exists():
      RUNTIME_PAUSE_LOCK = _run_user_dir / "hypr-session.paused"
  else:
      RUNTIME_PAUSE_LOCK = Path(f"/tmp/hypr-session-{os.getuid()}.paused")
  ```
* **Robustness Issue**: The path `/run/user/<uid>` is a systemd convention. On non-systemd Linux distributions (e.g., Artix, Alpine, Void, Devuan, Gentoo without systemd), runtime session folders might be managed differently (e.g., via `elogind` or `seatd`). Although a fallback to `/tmp` is present, it is standard and more robust to check `os.environ.get("XDG_RUNTIME_DIR")` first before checking `/run/user/<uid>`.
* **Resolution**: Update the check to:
  ```python
  _runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
  if _runtime_dir:
      RUNTIME_PAUSE_LOCK = Path(_runtime_dir) / "hypr-session.paused"
  else:
      _run_user_dir = Path(f"/run/user/{os.getuid()}")
      if _run_user_dir.exists():
          ...
  ```

### 1.3 Strict Installer Environment Check
* **File & Lines**: `install.sh` (lines 10-14)
* **Verbatim Code**:
  ```bash
  if ! command -v hyprctl &> /dev/null; then
      echo -e "\033[1;31m[ERROR] hyprctl is not found.\033[0m"
      echo "This tool requires Hyprland to be installed and running."
      exit 1
  fi
  ```
* **Robustness Issue**: Exiting immediately if `hyprctl` is not in `$PATH` prevents building, packaging, or installing `hypr-session` in headless environments (e.g., inside an AUR clean chroot build container or during system provisioning scripts prior to running Hyprland).
* **Resolution**: Demote this check to a warning during installation instead of a hard exit, since `hyprctl` is checked at runtime by the tool anyway.

### 1.4 Rigid Path in Hook Injection
* **File & Lines**: `src/hypr_session/cli.py` (line 250)
* **Verbatim Code**:
  ```python
  hypr_conf = Path.home() / ".config/hypr/hyprland.conf"
  ```
* **Robustness Issue**: The path to `hyprland.conf` assumes standard user layouts and ignores custom configurations specified via `Hyprland --config <path>` or setups where `XDG_CONFIG_HOME` is modified.
* **Resolution**: Use `os.environ.get("XDG_CONFIG_HOME")` (falling back to `~/.config`) to construct the config path.

### 1.5 Hook Injection Exit Bind Regex Limitations
* **File & Lines**: `src/hypr_session/cli.py` (lines 269-270)
* **Verbatim Code**:
  ```python
  is_bind = line.strip().startswith("bind")
  is_exit = re.search(r',\s*(dispatch\s+)?exit\s*$', line)
  ```
* **Robustness Issue**: The `$` anchor in the regex prevents finding exit binds that have inline trailing comments or trailing spaces (e.g., `bind = SUPER SHIFT, Q, exit # shutdown`). This prevents automated hook injection on many existing configs.
* **Resolution**: Update the regex to ignore trailing comments and whitespace, e.g., `r',\s*(dispatch\s+)?exit\s*(?:#.*)?$'`.

### 1.6 Silent Configuration Parsing Failures
* **File & Lines**: `src/hypr_session/config.py` (lines 107-110)
* **Verbatim Code**:
  ```python
  try:
      data = tomllib.loads(CONFIG_FILE.read_text())
  except Exception:
      return HyprSessionConfig()
  ```
* **Robustness Issue**: If the user makes a syntax error in their `config.toml`, it is silently discarded, falling back to the defaults. The user is never warned that their config is corrupted.
* **Resolution**: Print a stderr warning or log an error when config file loading fails so users know they have a malformed TOML file.

---

## 2. Feature & UX/UI Ideation (R2)

To elevate `hypr-session` from a standard utility to a premium desktop tool, the following features and visual enhancements are proposed:

### 2.1 Side-by-Side Visual Diff
* **Concept**: The current `hypr-session diff` prints a simple flat table of missing and new apps. We propose an interactive, color-coded side-by-side or split layout (using Rich Columns/Grid).
* **Details**:
  * Left side: **[Saved Profile]** showing window classes and workspaces.
  * Right side: **[Active Desktop]** showing what is currently open.
  * Line connections or colors matching matched windows (gray/dim), missing windows (bold red `-`), and new windows (bold green `+`).
  * Add a warning indicator for floating windows whose dimensions/coordinates have shifted.

### 2.2 Interactive Profile Selection
* **Concept**: Instead of forcing the user to type profile names or look them up, running `hypr-session restore` or `hypr-session clear` without arguments could open an interactive menu.
* **Details**:
  * List all saved profiles with their metadata (window count, timestamp, description).
  * Allow navigating via arrow keys and selecting a profile with `Enter`.

### 2.3 Command Quiet (`-q` / `--quiet`) and Verbose (`-v` / `--verbose`) Flags
* **Concept**: Refine terminal output based on usage.
  * `--quiet`: Suppress all console prints and progress spinners. Excellent for `exec-once` startup scripts to ensure faster booting without polluting systemd/journal logs.
  * `--verbose`: Print internal state changes (desktop file paths searched, IPC command payloads, process matching details, and DBus restoration timing).

### 2.4 Targeted Workspace Filters
* **Concept**: Give the user fine-grained control over which workspaces are saved or restored.
  * `hypr-session save -p coding --workspace 1,2`: Only snapshot workspaces 1 and 2.
  * `hypr-session restore -p coding --workspace 1`: Only restore windows belonging to workspace 1 from the saved profile.

### 2.5 Profile Metadata and Custom Notes
* **Concept**: Allow users to attach a description/note to a saved session.
  * `hypr-session save --description "Gaming setup - steam + discord"`
  * display this note in `hypr-session list` or `status` to make profile management intuitive.

### 2.6 Session Utilities: Rename, Copy, and Backup Import/Export
* **Concept**: Provide first-class CLI commands for managing session files:
  * `hypr-session rename <old> <new>`: Rename session JSON file.
  * `hypr-session copy <src> <dest>`: Duplicate session profile.
  * `hypr-session export <profile> <file.json>`: Export a session.
  * `hypr-session import <file.json> -p <profile>`: Import a session.

### 2.7 Beautiful Dashboard Status Panel
* **Concept**: Redesign `hypr-session status` into a cohesive dashboard dashboard using Rich layouts.
  * Display a `Tree` layout representing the session:
    ```text
    Profile: default (Saved: 2026-06-17 19:15:00)
    ├── Workspace 1
    │   ├── Kitty (cwd: ~/Projects/hypr-session)
    │   └── VSCode
    └── Workspace 2
        └── Firefox
    ```

---

## 3. Test Suite Status and Gaps (R3)

### 3.1 Current Test Suite Analysis
* **Status**: 49 tests passing successfully.
* **Coverage**: Excellent coverage for isolated logical components:
  * `test_mapping.py`: Validates field extraction (`_extract_field`), placeholder stripping (`_parse_exec_command`), and command resolution rules priority.
  * `test_models.py`: Validates serialization and round-tripping of `WindowEntry` and `Session` structures, including version constraints.
  * `test_restore.py`: Validates string argument generation (`_build_cwd_cmd`, `_build_dispatch_arg`) for tiling and floating behaviors.

### 3.2 Key Testing Gaps
The current test suite focuses entirely on unit testing internal parsing and serialization logic. Key runtime components remain untested:
1. **No CLI Tests (`src/hypr_session/cli.py`)**:
   - Typer commands (`save`, `restore`, `diff`, `list`, `doctor`) are completely untested. No verification of command-line argument parsing, exit codes, or interactive commands exists.
   - *Resolution*: Use `typer.testing.CliRunner` to write integration tests for commands.
2. **No Core Session Operations Tests (`src/hypr_session/session.py`)**:
   - The backup creation, rotation limit (keeping exactly 10 backups per profile), profile deletion, and list parsing are not tested.
   - *Resolution*: Write unit tests targeting `save_session`, `list_sessions`, and `clear_session` using python's `unittest.mock` to mock `shutil.copy2` and file system writes.
3. **No Process Tree/System Utilities Tests (`src/hypr_session/utils.py`)**:
   - The code reading `/proc/<pid>/status`, `/proc/<pid>/exe`, and `/proc/<pid>/cwd` lacks testing.
   - *Resolution*: Create mock `/proc` directory structures in temporary directories during test execution to verify process ancestor chains (`get_ancestor_pids`) and shell cwd extraction (`get_terminal_cwd`).
4. **No IPC Restorer Engine Tests (`src/hypr_session/restore.py`)**:
   - The generator `restore_session(...)` that manages execution pipelines, calls `shutil.which` on commands, polls for new window addresses (`_wait_for_new_address`), and executes secondary positioning rules is untested.
   - *Resolution*: Mock `subprocess.run` and `shutil.which` to verify that the restoration generator executes correct IPC sequences for both successful and timing out applications.
5. **No Path Fallback Tests**:
   - Missing tests for environment variable configuration fallbacks (`XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_RUNTIME_DIR`).
