# Project: hypr-session Improvement

## Architecture
- CLI session manager for Hyprland or desktop configuration.
- Written in Python, utilizes system commands, custom parsing.
- Uses `pytest` and `ruff`.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Exploration & Audit | Audit current codebase for cross-distro issues, UX/UI improvements, and missing tests. | None | DONE |
| M2 | Robustness (R1) | Implement fixes for non-Arch compatibility (XDG search paths, Flatpak exec mappings, secure /tmp fallback, absolute hook paths, toml fallback). | M1 | DONE |
| M3 | Feature & UX (R2) | Implement collections.Counter for `diff`, visual diff layout, status dashboard tree, targeted CLI flags, and session utilities (rename, copy, export, import). | M1 | DONE |
| M4 | Testing & QA (R3) | Mock /proc utilities, add CLI Integration runner tests, mock session write/rotation, and achieve 100% pytest pass rate & zero ruff issues. | M2, M3 | DONE |
| M5 | Verification & Audit | Conduct challengers and Forensic Auditor run to verify everything is CLEAN. | M4 | DONE |

## Code Layout
- `install.sh`: Session installation/setup scripts.
- `src/`: Core Python library and CLI code.
  - `cli.py`: Typer command entries.
  - `config.py`: File layout configurations and paths.
  - `mapping.py`: Mapping of window class to system executable desktop files.
  - `models.py`: JSON schemas for window and session entries.
  - `restore.py`: restoration generator and IPC.
  - `session.py`: active window listing, file save/load.
  - `utils.py`: low level procfs reader and hyprctl subprocess runner.
- `tests/`: Project tests.
- `pyproject.toml`: Dependency and tool management.

## Interface Contracts
- CLI arguments and outputs must match expected Typer schemas.
- Profile storage paths are in user's state directory.
