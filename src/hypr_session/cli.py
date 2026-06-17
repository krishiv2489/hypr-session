"""
cli.py — Command-line interface for hypr-session with Rich integration.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

from .config import (
    CONFIG_FILE,
    DATA_DIR,
    PERMANENT_PAUSE_LOCK,
    RUNTIME_PAUSE_LOCK,
    ensure_config_dir,
    load_config,
)
from .restore import restore_session as _restore
from .session import (
    clear_all_sessions,
    clear_session,
    get_current_session_windows,
    list_sessions,
    load_session,
    save_session,
)
from .utils import is_hyprland_running, notify_user, run_hyprctl, wait_for_hyprland

app = typer.Typer(
    name="hypr-session",
    help="Premium session save and restore for the Hyprland compositor.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    rich_markup_mode="rich",
)
console = Console()

def _require_hyprland() -> None:
    if not is_hyprland_running():
        console.print("[bold red]Error:[/bold red] HYPRLAND_INSTANCE_SIGNATURE is not set.")
        raise typer.Exit(1)

def _check_paused() -> bool:
    if PERMANENT_PAUSE_LOCK.exists():
        console.print("[bold yellow]Note:[/bold yellow] Auto-save is disabled permanently. Run 'hypr-session resume' to enable.")
        return True
    if RUNTIME_PAUSE_LOCK.exists():
        console.print("[bold yellow]Note:[/bold yellow] Auto-save is paused for this session.")
        return True
    return False

@app.command()
def save(
    profile: str | None = typer.Option(None, "--profile", "-p", help="Save under a named profile."),
    force: bool = typer.Option(False, "--force", "-f", help="Save even if paused."),
    force_empty: bool = typer.Option(False, "--force-empty", help="Allow saving a session with 0 windows."),
    only_active: bool = typer.Option(False, "--only-active", help="Only save windows on the currently active workspace."),
) -> None:
    """Snapshot the current Hyprland session to disk."""
    _require_hyprland()
    if not force and _check_paused():
        raise typer.Exit(0)

    try:
        path, session = save_session(profile, force_empty=force_empty, only_active=only_active)
    except RuntimeError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(1) from None

    label = profile or "default"
    console.print(f"[bold green]✅ Saved '{label}':[/bold green] {len(session.windows)} window(s) → {path}")

@app.command()
def restore(
    profile: str | None = typer.Option(None, "--profile", "-p", help="Restore a specific profile."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be restored without launching apps."),
    wait: bool = typer.Option(False, "--wait", help="Wait for Hyprland to become ready before restoring."),
    workspace: str | None = typer.Option(None, "--workspace", help="Comma-separated list of workspace IDs to restore (e.g. 1,2)."),
    exclude: str | None = typer.Option(None, "--exclude", help="Comma-separated list of window classes to skip."),
) -> None:
    """Restore the saved Hyprland session."""
    if wait:
        console.print("[dim]Waiting for Hyprland to be ready...[/dim]")
        if not wait_for_hyprland():
            console.print("[bold red]Error:[/bold red] Timed out waiting for Hyprland to start.")
            raise typer.Exit(1)

    _require_hyprland()
    try:
        session = load_session(profile)
        label = profile or "default"

        if session is None or not session.windows:
            msg = f"Session '{label}' is empty or missing."
            console.print(f"[bold yellow]⚠️ {msg}[/bold yellow]")
            if wait:
                notify_user("hypr-session Warning", msg)
            raise typer.Exit(1)

    except Exception as e:
        console.print(f"[bold red]Error loading session:[/bold red] {e}")
        if wait:
            notify_user("hypr-session Error", str(e), "critical")
        raise typer.Exit(1) from None

    workspaces_list = None
    if workspace:
        try:
            workspaces_list = [int(x.strip()) for x in workspace.split(",") if x.strip()]
        except ValueError:
            console.print("[bold red]Error:[/bold red] --workspace must be a comma-separated list of integers.")
            raise typer.Exit(1) from None

    exclude_list = None
    if exclude:
        exclude_list = [x.strip() for x in exclude.split(",") if x.strip()]

    # Filter for count
    filtered_windows = []
    for w in session.windows:
        if workspaces_list is not None and w.workspace_id not in workspaces_list:
            continue
        if exclude_list is not None and any(w.initial_class.lower() == ec.lower() for ec in exclude_list):
            continue
        filtered_windows.append(w)

    if not filtered_windows:
        console.print("[bold yellow]⚠️ No windows to restore after applying filters.[/bold yellow]")
        raise typer.Exit(0)

    console.print(f"\n[bold blue]🚀 Restoring '{label}' {'(DRY RUN)' if dry_run else ''}[/bold blue]")

    restored, failed, missing = 0, 0, 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Restoring windows...", total=len(filtered_windows))

        for window, status in _restore(
            profile,
            dry_run=dry_run,
            workspaces=workspaces_list,
            exclude_classes=exclude_list,
        ):
            if status == "OK":
                progress.console.print(f"[green]✔[/green] {window.initial_class} → ws:{window.workspace_id}")
                restored += 1
            elif status == "DRY_RUN":
                progress.console.print(f"[cyan]~[/cyan] {window.initial_class} → ws:{window.workspace_id} (Skipped)")
                restored += 1
            elif status == "MISSING":
                progress.console.print(f"[yellow]⚠[/yellow] {window.initial_class} → '{window.cmd.split()[0]}' not found in PATH")
                missing += 1
            elif status == "TIMEOUT":
                progress.console.print(f"[red]✖[/red] {window.initial_class} → Timed out waiting for window.")
                failed += 1

            progress.advance(task)

    console.print(f"\n[bold]Summary:[/bold] {restored} Restored, {missing} Missing, {failed} Failed.\n")

@app.command(name="list")
def list_cmd() -> None:
    """List all saved sessions with window counts and timestamps."""
    sessions = list_sessions()
    if not sessions:
        console.print("[bold yellow]No saved sessions found.[/bold yellow]")
        return

    table = Table(title="Saved Hyprland Sessions", title_style="bold blue")
    table.add_column("Profile", style="cyan", no_wrap=True)
    table.add_column("Windows", justify="right", style="magenta")
    table.add_column("Saved At", style="green")

    for label, _path, session in sessions:
        if session:
            table.add_row(label, str(len(session.windows)), session.timestamp[:19])
        else:
            table.add_row(label, "[red]?[/red]", "[red]corrupted[/red]")

    console.print(table)

@app.command()
def status() -> None:
    """Show the current status, configuration, and saved sessions."""
    paused = PERMANENT_PAUSE_LOCK.exists() or RUNTIME_PAUSE_LOCK.exists()
    load_config()
    sessions = list_sessions()

    status_text = (
        f"[bold]Auto-save:[/bold] {'[bold red]PAUSED ⚠[/bold red]' if paused else '[bold green]ACTIVE ✅[/bold green]'}\n"
        f"[bold]Config:[/bold]    {CONFIG_FILE}\n"
        f"[bold]Data dir:[/bold]  {DATA_DIR}"
    )
    console.print(Panel(status_text, title="System Status", border_style="blue", expand=False))

    if sessions:
        from rich.tree import Tree
        for label, _path, session in sessions:
            if not session:
                console.print(f"\n[bold blue]Profile:[/bold blue] {label} [red](corrupted)[/red]")
                continue

            root_label = f"[bold blue]Profile:[/bold blue] {label} [dim](Saved: {session.timestamp[:19]})[/dim]"
            tree = Tree(root_label)

            # Group windows by monitor, then by workspace
            windows_by_monitor = {}
            for w in session.windows:
                windows_by_monitor.setdefault(w.monitor, {}).setdefault(w.workspace_id, []).append(w)

            for monitor_id in sorted(windows_by_monitor.keys()):
                monitor_branch = tree.add(f"[bold cyan]Monitor {monitor_id}[/bold cyan]")
                workspaces_dict = windows_by_monitor[monitor_id]
                for workspace_id in sorted(workspaces_dict.keys()):
                    workspace_branch = monitor_branch.add(f"[bold green]Workspace {workspace_id}[/bold green]")
                    for w in workspaces_dict[workspace_id]:
                        layout_type = "floating" if w.floating else "tiling"
                        win_desc = f"[magenta]{w.initial_class}[/magenta] [dim]({layout_type})[/dim]"
                        if w.cwd:
                            win_desc += f" [yellow]cwd: {w.cwd}[/yellow]"
                        workspace_branch.add(win_desc)
            console.print(tree)
    else:
        console.print("[dim]No sessions saved yet.[/dim]")

@app.command()
def clear(profile: str | None = typer.Option(None, "--profile", "-p"), all_profiles: bool = typer.Option(False, "--all", "-a")) -> None:
    """Delete one or all saved sessions."""
    if all_profiles:
        console.print(f"[bold green]Cleared {clear_all_sessions()} session(s).[/bold green]")
    else:
        console.print(f"[bold green]Session '{profile or 'default'}' cleared.[/bold green]" if clear_session(profile) else "[bold yellow]No session found.[/bold yellow]")

@app.command()
def pause(permanent: bool = typer.Option(False, "--permanent", help="Disable auto-save permanently across reboots.")) -> None:
    """Disable automatic session saving."""
    if permanent:
        PERMANENT_PAUSE_LOCK.parent.mkdir(parents=True, exist_ok=True)
        PERMANENT_PAUSE_LOCK.touch()
        console.print("[bold yellow]⏸️ Auto-save permanently disabled.[/bold yellow] Run 'hypr-session resume' to re-enable.")
    else:
        RUNTIME_PAUSE_LOCK.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_PAUSE_LOCK.touch()
        console.print("[bold yellow]⏸️ Auto-save paused for this boot.[/bold yellow] Run 'hypr-session resume' to re-enable.")

@app.command()
def resume() -> None:
    """Re-enable session saving after a pause."""
    resumed = False
    if PERMANENT_PAUSE_LOCK.exists():
        PERMANENT_PAUSE_LOCK.unlink()
        resumed = True
    if RUNTIME_PAUSE_LOCK.exists():
        RUNTIME_PAUSE_LOCK.unlink()
        resumed = True

    if resumed:
        console.print("[bold green]▶️ Auto-save resumed.[/bold green]")
    else:
        console.print("Auto-save was not paused.")

@app.command(name="config")
def config_cmd() -> None:
    """Create the config directory and write a default config.toml."""
    ensure_config_dir()
    console.print(f"[{'yellow' if CONFIG_FILE.exists() else 'green'}]{'Config already exists at:' if CONFIG_FILE.exists() else 'Created config at:'}[/] {CONFIG_FILE}")

@app.command(name="install-hooks")
def install_hooks() -> None:
    """Automatically inject startup and shutdown hooks into hyprland.conf."""
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        hypr_conf = Path(xdg_config_home) / "hypr/hyprland.conf"
    else:
        hypr_conf = Path.home() / ".config/hypr/hyprland.conf"

    if not hypr_conf.exists():
        console.print(f"[bold red]❌ Could not find {hypr_conf}. Please ensure Hyprland is configured.[/bold red]")
        raise typer.Exit(1)

    # Detect the absolute path of the executing hypr-session binary
    binary_path_str = shutil.which("hypr-session")
    if binary_path_str:
        binary_path = str(Path(binary_path_str).resolve())
    else:
        if sys.argv and sys.argv[0]:
            binary_path = str(Path(sys.argv[0]).resolve())
        else:
            binary_path = "hypr-session"

    backup_path = hypr_conf.with_suffix(".conf.bak")
    if not backup_path.exists():
        shutil.copy(hypr_conf, backup_path)
        console.print(f"[dim]Created backup of hyprland.conf at {backup_path}[/dim]")
    else:
        console.print(f"[dim]Backup of hyprland.conf already exists at {backup_path}[/dim]")

    lines = hypr_conf.read_text(encoding="utf-8").splitlines()
    new_lines = []
    has_restore = False
    exit_modified = False

    for line in lines:
        if "hypr-session restore" in line:
            has_restore = True

        is_bind = line.strip().startswith("bind")
        # Ignore trailing comments and whitespace in exit bind
        is_exit = re.search(r',\s*(dispatch\s+)?exit\s*(?:#.*)?$', line.strip())

        if is_bind and is_exit and "hypr-session" not in line:
            prefix = line.rsplit(',', 1)[0]
            new_lines.append("# [Auto-commented by hypr-session]")
            new_lines.append(f"# {line}")
            new_lines.append(f"{prefix}, exec, {binary_path} save ; hyprctl dispatch exit")
            exit_modified = True
            console.print(f"[bold green]✔ Injected save hook into exit bind:[/bold green] {prefix.strip()}")
            continue

        new_lines.append(line)

    if not has_restore:
        new_lines.append("\n# --- Auto-generated by hypr-session ---")
        new_lines.append(f"exec-once = {binary_path} restore --wait")
        console.print("[bold green]✔ Injected startup hook (exec-once).[/bold green]")

    if not has_restore or exit_modified:
        hypr_conf.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        console.print("[bold blue]🎉 hyprland.conf successfully updated! Hooks are active.[/bold blue]")
    else:
        console.print("[bold yellow]⚠ Hooks were already present. No changes made.[/bold yellow]")

@app.command()
def diff(profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to diff against.")) -> None:
    """Compare currently saved session against active desktop."""
    from collections import Counter
    _require_hyprland()
    saved_session = load_session(profile)
    if not saved_session or not saved_session.windows:
        console.print("[bold yellow]No saved session to compare against.[/bold yellow]")
        return

    current_windows = get_current_session_windows()

    saved_counter = Counter((w.workspace_id, w.initial_class) for w in saved_session.windows)
    current_counter = Counter((w.workspace_id, w.initial_class) for w in current_windows)

    all_keys = sorted(
        saved_counter.keys() | current_counter.keys(),
        key=lambda x: (x[0], x[1])
    )

    table = Table(title="Session Comparison: Saved vs Active", title_style="bold blue")
    table.add_column("Saved WS", justify="right")
    table.add_column("Saved App Class")
    table.add_column("Match Status", justify="center")
    table.add_column("Active WS", justify="right")
    table.add_column("Active App Class")

    geom_warning = False
    has_diff = False

    for key in all_keys:
        ws_id, cls = key
        saved_wins = [w for w in saved_session.windows if w.workspace_id == ws_id and w.initial_class == cls]
        current_wins = [w for w in current_windows if w.workspace_id == ws_id and w.initial_class == cls]

        max_len = max(len(saved_wins), len(current_wins))
        for i in range(max_len):
            s_win = saved_wins[i] if i < len(saved_wins) else None
            c_win = current_wins[i] if i < len(current_wins) else None

            if s_win and c_win:
                geom_diff = False
                if s_win.floating and c_win.floating:
                    if s_win.at != c_win.at or s_win.size != c_win.size:
                        geom_diff = True
                        geom_warning = True
                elif s_win.floating != c_win.floating:
                    geom_diff = True
                    geom_warning = True

                if geom_diff:
                    status_str = "[bold yellow]Δ geom[/bold yellow]"
                    has_diff = True
                else:
                    status_str = "[dim]matched[/dim]"

                table.add_row(
                    f"[dim]{s_win.workspace_id}[/dim]",
                    f"[dim]{s_win.initial_class}[/dim]",
                    status_str,
                    f"[dim]{c_win.workspace_id}[/dim]",
                    f"[dim]{c_win.initial_class}[/dim]",
                )
            elif s_win:
                has_diff = True
                table.add_row(
                    f"[bold red]{s_win.workspace_id}[/bold red]",
                    f"[bold red]{s_win.initial_class}[/bold red]",
                    "[bold red]<- missing[/bold red]",
                    "[dim]-[/dim]",
                    "[dim]-[/dim]",
                )
            elif c_win:
                has_diff = True
                table.add_row(
                    "[dim]-[/dim]",
                    "[dim]-[/dim]",
                    "[bold green]new ->[/bold green]",
                    f"[bold green]{c_win.workspace_id}[/bold green]",
                    f"[bold green]{c_win.initial_class}[/bold green]",
                )

    if not has_diff:
        console.print("[bold green]✔ Active desktop matches saved session perfectly.[/bold green]")
        if geom_warning:
            console.print("[bold yellow]⚠️ Warning: Some floating window geometries differ from the saved profile.[/bold yellow]")
        return

    console.print(table)

    if geom_warning:
        console.print("[bold yellow]⚠️ Warning: Some floating window geometries differ from the saved profile.[/bold yellow]")


@app.command()
def doctor() -> None:
    """Diagnose system state and verify hypr-session requirements."""
    table = Table(title="System Diagnostics", title_style="bold blue", show_header=False)
    table.add_column("Component", style="cyan")
    table.add_column("Status")

    # Check Hyprland
    hypr_running = is_hyprland_running()
    table.add_row("Hyprland Environment", "[green]✔ Running[/green]" if hypr_running else "[red]✖ Not Running[/red]")

    # Check hyprctl
    hyprctl_path = shutil.which("hyprctl")
    table.add_row("hyprctl Binary", f"[green]✔ Found ({hyprctl_path})[/green]" if hyprctl_path else "[red]✖ Missing[/red]")

    # Check IPC
    ipc_ok = False
    if hypr_running and hyprctl_path:
        try:
            run_hyprctl("monitors")
            ipc_ok = True
        except Exception:
            pass
    table.add_row("Hyprland IPC", "[green]✔ Responsive[/green]" if ipc_ok else "[red]✖ Unresponsive[/red]")

    # Check Data Dir
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        test_file = DATA_DIR / ".test"
        test_file.touch()
        test_file.unlink()
        data_ok = True
    except Exception:
        data_ok = False
    table.add_row("Data Directory", f"[green]✔ Writable ({DATA_DIR})[/green]" if data_ok else "[red]✖ Permission Denied[/red]")

    console.print(table)

    if all([hypr_running, hyprctl_path, ipc_ok, data_ok]):
        console.print("\n[bold green]Everything looks good! System is ready.[/bold green]")
    else:
        console.print("\n[bold red]Some checks failed. hypr-session may not work correctly.[/bold red]")


def _version_callback(value: bool) -> None:
    if value:
        from hypr_session import __version__
        console.print(f"hypr-session v{__version__}")
        raise typer.Exit()


def _resolve_profile_name(name: str) -> str | None:
    if name == "default":
        return None
    return name


@app.command(name="rename")
def rename(
    old: str = typer.Argument(..., help="Current name of the profile."),
    new: str = typer.Argument(..., help="New name for the profile."),
) -> None:
    """Rename an existing session profile."""
    from .session import get_session_path

    src_path = get_session_path(_resolve_profile_name(old))
    if not src_path.exists():
        console.print(f"[bold red]Error:[/bold red] Profile '{old}' does not exist.")
        raise typer.Exit(1)

    dest_path = get_session_path(_resolve_profile_name(new))
    if dest_path.exists():
        console.print(f"[bold red]Error:[/bold red] Profile '{new}' already exists.")
        raise typer.Exit(1)

    try:
        shutil.move(src_path, dest_path)
        console.print(f"[bold green]Profile '{old}' successfully renamed to '{new}'.[/bold green]")
    except Exception as exc:
        console.print(f"[bold red]Error renaming profile:[/bold red] {exc}")
        raise typer.Exit(1) from exc


@app.command(name="copy")
def copy(
    src: str = typer.Argument(..., help="Source profile name."),
    dest: str = typer.Argument(..., help="Destination profile name."),
) -> None:
    """Duplicate an existing session profile."""
    from .session import get_session_path

    src_path = get_session_path(_resolve_profile_name(src))
    if not src_path.exists():
        console.print(f"[bold red]Error:[/bold red] Profile '{src}' does not exist.")
        raise typer.Exit(1)

    dest_path = get_session_path(_resolve_profile_name(dest))
    if dest_path.exists():
        console.print(f"[bold red]Error:[/bold red] Profile '{dest}' already exists.")
        raise typer.Exit(1)

    try:
        shutil.copy2(src_path, dest_path)
        console.print(f"[bold green]Profile '{src}' successfully copied to '{dest}'.[/bold green]")
    except Exception as exc:
        console.print(f"[bold red]Error copying profile:[/bold red] {exc}")
        raise typer.Exit(1) from exc


@app.command(name="export")
def export(
    profile: str = typer.Argument(..., help="Name of the profile to export."),
    file_path: Path = typer.Argument(..., help="Path to the destination JSON file."),
) -> None:
    """Export a session profile to a JSON file."""
    from .session import get_session_path

    src_path = get_session_path(_resolve_profile_name(profile))
    if not src_path.exists():
        console.print(f"[bold red]Error:[/bold red] Profile '{profile}' does not exist.")
        raise typer.Exit(1)

    if file_path.exists():
        console.print(f"[bold red]Error:[/bold red] File '{file_path}' already exists.")
        raise typer.Exit(1)

    try:
        if not file_path.parent.exists():
            file_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, file_path)
        console.print(f"[bold green]Profile '{profile}' successfully exported to '{file_path}'.[/bold green]")
    except Exception as exc:
        console.print(f"[bold red]Error exporting profile:[/bold red] {exc}")
        raise typer.Exit(1) from exc


@app.command(name="import")
def import_cmd(
    file_path: Path = typer.Argument(..., help="Path to the JSON file to import."),
    profile: str = typer.Option(..., "--profile", "-p", help="Name of the target profile."),
) -> None:
    """Import a JSON file as a session profile."""
    import json

    from .models import Session
    from .session import get_session_path

    if not file_path.exists() or not file_path.is_file():
        console.print(f"[bold red]Error:[/bold red] File '{file_path}' does not exist or is not a file.")
        raise typer.Exit(1)

    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
        Session.from_dict(data)
    except Exception as exc:
        console.print(f"[bold red]Error:[/bold red] '{file_path}' is not a valid session file: {exc}")
        raise typer.Exit(1) from exc

    dest_path = get_session_path(_resolve_profile_name(profile))
    if dest_path.exists():
        console.print(f"[bold red]Error:[/bold red] Profile '{profile}' already exists.")
        raise typer.Exit(1)

    try:
        shutil.copy2(file_path, dest_path)
        console.print(f"[bold green]Successfully imported '{file_path}' as profile '{profile}'.[/bold green]")
    except Exception as exc:
        console.print(f"[bold red]Error importing profile:[/bold red] {exc}")
        raise typer.Exit(1) from exc


@app.callback()
def _app_callback(
    version: bool = typer.Option(
        False, "--version", "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Premium session save and restore for the Hyprland compositor."""


def main() -> None:
    app()
