"""
cli.py — Command-line interface for hypr-session with Rich integration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

import re
import shutil

from .config import (
    CONFIG_FILE, DATA_DIR, PAUSE_LOCK,
    ensure_config_dir, load_config,
)
from .restore import restore_session as _restore
from .session import (
    clear_all_sessions, clear_session, list_sessions,
    load_session, save_session,
)
from .utils import is_hyprland_running

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
    if PAUSE_LOCK.exists():
        console.print("[bold yellow]Note:[/bold yellow] Auto-save is paused.")
        return True
    return False

@app.command()
def save(
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="Save under a named profile."),
    force: bool = typer.Option(False, "--force", "-f", help="Save even if paused."),
) -> None:
    """Snapshot the current Hyprland session to disk."""
    _require_hyprland()
    if not force and _check_paused():
        raise typer.Exit(0)

    try:
        path, session = save_session(profile)
    except RuntimeError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(1)

    label = profile or "default"
    console.print(f"[bold green]✅ Saved '{label}':[/bold green] {len(session.windows)} window(s) → {path}")

@app.command()
def restore(
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="Restore a specific profile."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be restored without launching apps.")
) -> None:
    """Restore the saved Hyprland session."""
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

    for label, path, session in sessions:
        if session:
            table.add_row(label, str(len(session.windows)), session.timestamp[:19])
        else:
            table.add_row(label, "[red]?[/red]", "[red]corrupted[/red]")

    console.print(table)

@app.command()
def status() -> None:
    """Show the current status, configuration, and saved sessions."""
    paused = PAUSE_LOCK.exists()
    cfg = load_config()
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

        for label, path, session in sessions:
            console.print(f"\n[bold blue]Profile:[/bold blue] {label} [dim](Saved: {session.timestamp[:19] if session else 'Unknown'})[/dim]")
            if session:
                for w in session.windows:
                    state = []
                    if w.floating: state.append("float")
                    if w.fullscreen == 2: state.append("full")
                    elif w.fullscreen == 1: state.append("max")
                    if w.cwd: state.append("cwd")
                    table.add_row(str(w.workspace_id), w.initial_class, w.cmd, ",".join(state) if state else "-")
        console.print(table)
    else:
        console.print("[dim]No sessions saved yet.[/dim]")

@app.command()
def clear(profile: Optional[str] = typer.Option(None, "--profile", "-p"), all_profiles: bool = typer.Option(False, "--all", "-a")) -> None:
    """Delete one or all saved sessions."""
    if all_profiles:
        console.print(f"[bold green]Cleared {clear_all_sessions()} session(s).[/bold green]")
    else:
        console.print(f"[bold green]Session '{profile or 'default'}' cleared.[/bold green]" if clear_session(profile) else "[bold yellow]No session found.[/bold yellow]")

@app.command()
def pause() -> None:
    """Disable automatic session saving for this boot."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PAUSE_LOCK.touch()
    console.print("[bold yellow]⏸️ Auto-save paused.[/bold yellow] Run 'hypr-session resume' to re-enable.")

@app.command()
def resume() -> None:
    """Re-enable session saving after a pause."""
    if PAUSE_LOCK.exists():
        PAUSE_LOCK.unlink()
        console.print("[bold green]▶️ Auto-save resumed.[/bold green]")
    else:
        console.print("Auto-save was not paused.")

@app.command(name="config")
def config_cmd() -> None:
    """Create the config directory and write a default config.toml."""
    ensure_config_dir()
    console.print(f"[{'yellow' if CONFIG_FILE.exists() else 'green'}]{'Config already exists at:' if CONFIG_FILE.exists() else 'Created config at:'}[/] {CONFIG_FILE}")

@app.command()
def install_hooks() -> None:
    """Automatically inject startup and shutdown hooks into hyprland.conf."""
    hypr_conf = Path.home() / ".config/hypr/hyprland.conf"
    
    if not hypr_conf.exists():
        console.print(f"[bold red]❌ Could not find {hypr_conf}. Please ensure Hyprland is installed.[/bold red]")
        raise typer.Exit(1)

    # 1. Create a safe backup
    backup_path = hypr_conf.with_suffix(".conf.bak")
    shutil.copy(hypr_conf, backup_path)
    console.print(f"[dim]Created backup of hyprland.conf at {backup_path}[/dim]")

    lines = hypr_conf.read_text().splitlines()
    new_lines = []
    has_restore = False
    exit_modified = False

    for line in lines:
        if "hypr-session restore" in line:
            has_restore = True

        # 2. Intelligently hunt for the user's exit bind
        # We look for a line starting with "bind", ending with "exit" or "dispatch exit"
        # and ensure it hasn't already been modified by hypr-session.
        is_bind = line.strip().startswith("bind")
        is_exit = re.search(r',\s*(dispatch\s+)?exit\s*$', line)
        
        if is_bind and is_exit and "hypr-session" not in line:
            # Split the line at the last comma to keep the user's custom key combination
            # e.g., "bind = SUPER, M, exit" becomes prefix -> "bind = SUPER, M"
            prefix = line.rsplit(',', 1)[0]
            
            new_lines.append("# [Auto-commented by hypr-session]")
            new_lines.append(f"# {line}")
            new_lines.append(f"{prefix}, exec, hypr-session save ; hyprctl dispatch exit")
            
            exit_modified = True
            console.print(f"[bold green]✔ Injected save hook into exit bind:[/bold green] {prefix.strip()}")
            continue

        new_lines.append(line)

    # 3. Append the auto-start routine if it's missing
    if not has_restore:
        new_lines.append("\n# --- Auto-generated by hypr-session ---")
        new_lines.append("exec-once = sleep 2 && hypr-session restore")
        console.print("[bold green]✔ Injected startup hook (exec-once).[/bold green]")

    if not has_restore or exit_modified:
        hypr_conf.write_text("\n".join(new_lines) + "\n")
        console.print("[bold blue]🎉 hyprland.conf successfully updated! Hooks are active.[/bold blue]")
    else:
        console.print("[bold yellow]⚠ Hooks were already present. No changes made.[/bold yellow]")

def main() -> None:
    app()