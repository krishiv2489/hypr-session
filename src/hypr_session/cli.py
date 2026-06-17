"""
cli.py — Command-line interface for hypr-session with Rich integration.
"""

from __future__ import annotations

import re
import shutil
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
from .utils import is_hyprland_running, run_hyprctl, wait_for_hyprland

app = typer.Typer(
    name="hypr-session",
    help="Premium session save and restore for the Hyprland compositor.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
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
) -> None:
    """Snapshot the current Hyprland session to disk."""
    _require_hyprland()
    if not force and _check_paused():
        raise typer.Exit(0)

    try:
        path, session = save_session(profile, force_empty=force_empty)
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
) -> None:
    """Restore the saved Hyprland session."""
    if wait:
        console.print("[dim]Waiting for Hyprland to be ready...[/dim]")
        if not wait_for_hyprland():
            console.print("[bold red]Error:[/bold red] Timed out waiting for Hyprland to start.")
            raise typer.Exit(1)

    _require_hyprland()
    session = load_session(profile)
    label = profile or "default"

    if session is None or not session.windows:
        console.print(f"[bold yellow]⚠️ Session '{label}' is empty or missing.[/bold yellow]")
        raise typer.Exit(1)

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
        task = progress.add_task("Restoring windows...", total=len(session.windows))

        for window, status in _restore(profile, dry_run=dry_run):
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
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("WS", style="dim", width=3)
        table.add_column("App Class", style="bold green")
        table.add_column("Command", style="yellow")
        table.add_column("State", style="magenta")

        for label, _path, session in sessions:
            console.print(f"\n[bold blue]Profile:[/bold blue] {label} [dim](Saved: {session.timestamp[:19] if session else 'Unknown'})[/dim]")
            if session:
                for w in session.windows:
                    state = []
                    if w.floating:
                        state.append("float")
                    if w.fullscreen == 2:
                        state.append("full")
                    elif w.fullscreen == 1:
                        state.append("max")
                    if w.cwd:
                        state.append("cwd")
                    table.add_row(
                        str(w.workspace_id), w.initial_class, w.cmd,
                        ",".join(state) if state else "-",
                    )
        console.print(table)
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
    hypr_conf = Path.home() / ".config/hypr/hyprland.conf"

    if not hypr_conf.exists():
        console.print(f"[bold red]❌ Could not find {hypr_conf}. Please ensure Hyprland is configured.[/bold red]")
        raise typer.Exit(1)

    backup_path = hypr_conf.with_suffix(".conf.bak")
    shutil.copy(hypr_conf, backup_path)
    console.print(f"[dim]Created backup of hyprland.conf at {backup_path}[/dim]")

    lines = hypr_conf.read_text(encoding="utf-8").splitlines()
    new_lines = []
    has_restore = False
    exit_modified = False

    for line in lines:
        if "hypr-session restore" in line:
            has_restore = True

        is_bind = line.strip().startswith("bind")
        is_exit = re.search(r',\s*(dispatch\s+)?exit\s*$', line)

        if is_bind and is_exit and "hypr-session" not in line:
            prefix = line.rsplit(',', 1)[0]
            new_lines.append("# [Auto-commented by hypr-session]")
            new_lines.append(f"# {line}")
            new_lines.append(f"{prefix}, exec, hypr-session save ; hyprctl dispatch exit")
            exit_modified = True
            console.print(f"[bold green]✔ Injected save hook into exit bind:[/bold green] {prefix.strip()}")
            continue

        new_lines.append(line)

    if not has_restore:
        new_lines.append("\n# --- Auto-generated by hypr-session ---")
        new_lines.append("exec-once = hypr-session restore --wait")
        console.print("[bold green]✔ Injected startup hook (exec-once).[/bold green]")

    if not has_restore or exit_modified:
        hypr_conf.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        console.print("[bold blue]🎉 hyprland.conf successfully updated! Hooks are active.[/bold blue]")
    else:
        console.print("[bold yellow]⚠ Hooks were already present. No changes made.[/bold yellow]")

@app.command()
def diff(profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to diff against.")) -> None:
    """Compare currently saved session against active desktop."""
    _require_hyprland()
    saved_session = load_session(profile)
    if not saved_session or not saved_session.windows:
        console.print("[bold yellow]No saved session to compare against.[/bold yellow]")
        return

    current_windows = get_current_session_windows()

    saved_keys = {f"{w.workspace_id}:{w.initial_class}" for w in saved_session.windows}
    current_keys = {f"{w.workspace_id}:{w.initial_class}" for w in current_windows}

    missing = saved_keys - current_keys
    new = current_keys - saved_keys

    if not missing and not new:
        console.print("[bold green]✔ Active desktop matches saved session perfectly.[/bold green]")
        return

    table = Table(title="Session Diff", title_style="bold blue")
    table.add_column("Status", style="bold")
    table.add_column("Workspace", style="dim")
    table.add_column("App Class", style="cyan")

    for key in missing:
        ws, cls = key.split(":", 1)
        table.add_row("[red]- Missing[/red]", ws, cls)

    for key in new:
        ws, cls = key.split(":", 1)
        table.add_row("[green]+ New[/green]", ws, cls)

    console.print(table)


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
