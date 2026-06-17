## 2026-06-17T19:19:32+05:30

Implement the robustness improvements (R1) for hypr-session:
1. Hardcoded Desktop Search Paths:
   In `src/hypr_session/mapping.py`, dynamically collect search paths using `os.environ.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share')` and respect `os.environ.get('XDG_DATA_HOME', '~/.local/share')`.
   Also append NixOS search paths (`/run/current-system/sw/share/applications`, `~/.nix-profile/share/applications`) and Snap search paths (`/var/lib/snapd/desktop/applications`).
   Append Flatpak paths (system and user) if they exist.
2. Flatpak Executable Mapping Bug:
   In `src/hypr_session/mapping.py`, make sure Flatpak applications are not skipped during desktop map generation. In `_parse_exec_command`, do not strip the application ID or arguments needed to execute a Flatpak application correctly (e.g. preserve `flatpak run com.spotify.Client`).
3. Insecure `/tmp` Fallback:
   In `src/hypr_session/config.py`, check `os.environ.get('XDG_RUNTIME_DIR')` first before fallback directories. If writing to `/tmp`, create a secure user-only directory (e.g. `mode=0o700`) to place the lock/paused files safely.
4. Hook Installer Robustness:
   In `src/hypr_session/cli.py` (under `install-hooks` command), detect the absolute path of the executing `hypr-session` binary (using `sys.argv[0]` or `shutil.which` or similar) and write the absolute path to the injected hooks in `hyprland.conf`.
   Also respect `$XDG_CONFIG_HOME` when resolving `hyprland.conf` path.
   Make exit bind regex search ignore trailing comments and whitespace, e.g. `r',\s*(dispatch\s+)?exit\s*(?:#.*)?$'`.
   Ensure multiple runs of `install-hooks` do not overwrite the original backup with a modified config (check if a backup already exists and do not copy over it).
5. Config Loading & toml fallback:
   In `src/hypr_session/config.py`, print a warning to stderr when config loading fails. Add import fallback to `tomli` if `tomllib` is unavailable.

Verify your changes by running the test suite via `.venv/bin/pytest`.
Run ruff check via `.venv/bin/ruff check src/ tests/` to ensure zero lint errors.
