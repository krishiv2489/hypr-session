## 2026-06-17T13:52:00Z

Implement the Feature & UX/UI improvements (R2) and corresponding tests (R3) for hypr-session:
1. Broken `diff` Command:
   - In `src/hypr_session/cli.py` (under the `diff` command), refactor the comparison logic to use `collections.Counter` on `(workspace_id, initial_class)` pairs. This ensures duplicate instances of the same application class on the same workspace are tracked correctly.
2. Side-by-Side Visual Diff Table:
   - Use the `rich` library (e.g. `rich.table.Table`, `rich.console.Console`) to output a beautiful, side-by-side or split layout comparison of the Saved Profile vs the Active Desktop.
   - Color code matched windows (dimmed), missing windows (bold red), and new windows (bold green).
   - Display a warning if floating window geometries differ.
3. Dashboard Status:
   - In `src/hypr_session/cli.py` (under the `status` command), refactor the output using a Rich `Tree` displaying:
     - Profile Name and Save Timestamp.
     - Monitors as top-level branches.
     - Workspaces as sub-branches.
     - Windows under each workspace, showing their class, floating status, and current working directory if available.
4. Targeted Save/Restore Flags:
   - Under the `restore` command in `src/hypr_session/cli.py` (and in `src/hypr_session/restore.py`), support:
     - `--workspace` (comma-separated list of workspace IDs, e.g. `1,2`). Only windows belonging to those workspaces are restored.
     - `--exclude` (comma-separated list of window classes). Windows of those classes are skipped.
   - Under the `save` command in `src/hypr_session/cli.py` (and in `src/hypr_session/session.py`), support:
     - `--only-active`: Only windows belonging to the currently active/focused workspace (obtained from hyprland state) are saved.
5. Profile Management Commands:
   - Add these commands to `src/hypr_session/cli.py`:
     - `rename <old> <new>`: Rename an existing session profile JSON file.
     - `copy <src> <dest>`: Duplicate a session profile JSON file.
     - `export <profile> <file.json>`: Export a session profile file to a path.
     - `import <file.json> --profile <name>` (or `-p <name>`): Import a session JSON file to profile storage.
   - Validate inputs (e.g., check if files/profiles exist/already exist).
6. Testing (R3):
   - Add unit and integration tests covering the Counter-based diff, the new commands, and the filter flags.
   - Use `typer.testing.CliRunner` to test the command executions.

Verify your changes by running the test suite via `.venv/bin/pytest`.
Run ruff check via `.venv/bin/ruff check src/ tests/` to ensure zero lint errors.
