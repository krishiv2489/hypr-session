"""
cli.py — Command-line interface for hypr-session.
"""

from __future__ import annotations
import sys
import typer
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .config import (
    CONFIG_DIR, CONFIG_FILE, DATA_DIR, PAUSE_LOCK,
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
    help="Session save and restore for the Hyprland Wayland compositor.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
console = Console()

def _require_hyprland() -> None:
    if not is_hyprland_running():
        console.print("[bold red]Error:[/bold red] HYPRLAND_INSTANCE_SIGNATURE is not set.\nThis must be run inside a Hyprland session.")
        raise typer.Exit(1)

def _check_paused() -> bool:
    if PAUSE_LOCK.exists():
        console.print("[bold yellow]Note:[/bold yellow] Session auto-save is paused. Run 'hypr-session resume' to re-enable.")
        return True
    return False

@app.command()
def save(
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="Save under a named profile."),
    force: bool = typer.Option(False, "--force", "-f", help="Save even if paused."),
) -> None:
    """Save the current Hyprland session to disk."""
    _require_hyprland()
    if not force and _check_paused():
        raise typer.Exit(0)

    try:
        path, session = save_session(profile)
    except RuntimeError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(1)

    label = profile or "default"
    console.print(f"[bold green]✅ Saved session '{label}':[/bold green] {len(session.windows)} window(s) → {path}")

@app.command()
def restore(profile: Optional[str] = typer.Option(None, "--profile", "-p", help="Restore a specific profile.")) -> None:
    """Restore the saved Hyprland session."""
    _require_hyprland()
    try:
        restored, failed = _restore(profile)
    except RuntimeError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(1)

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
def clear(
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="Clear a specific profile."),
    all_profiles: bool = typer.Option(False, "--all", "-a", help="Clear ALL saved sessions."),
) -> None:
    """Delete one or all saved sessions."""
    if all_profiles:
        count = clear_all_sessions()
        console.print(f"[bold green]Cleared {count} session(s).[/bold green]")
        return
    label = profile or "default"
    if clear_session(profile):
        console.print(f"[bold green]Session '{label}' cleared.[/bold green]")
    else:
        console.print(f"[bold yellow]No session found for profile '{label}'.[/bold yellow]")

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

@app.command()
def status() -> None:
    """Show the current status, configuration, and saved sessions."""
    paused = PAUSE_LOCK.exists()
    cfg = load_config()
    sessions = list_sessions()

    # System Status Panel
    status_text = (
        f"[bold]Auto-save:[/bold] {'[bold red]PAUSED ⚠[/bold red]' if paused else '[bold green]ACTIVE ✅[/bold green]'}\n"
        f"[bold]Config:[/bold]    {CONFIG_FILE}\n"
        f"[bold]Data dir:[/bold]  {DATA_DIR}"
    )
    console.print(Panel(status_text, title="System Status", border_style="blue", expand=False))

    # Configuration Panel
    cfg_text = (
        f"[cyan]restore_delay_seconds[/cyan] : {cfg.restore_delay_seconds}s\n"
        f"[cyan]window_wait_timeout[/cyan]   : {cfg.window_wait_timeout}s\n"
        f"[cyan]restore_floating[/cyan]      : {cfg.restore_floating}\n"
        f"[cyan]restore_fullscreen[/cyan]    : {cfg.restore_fullscreen}\n"
        f"[cyan]restore_cwd[/cyan]           : {cfg.restore_cwd}"
    )
    console.print(Panel(cfg_text, title="Active Configuration", border_style="magenta", expand=False))

    # Sessions Table
    if sessions:
        table = Table(title="Window Layouts", show_header=True, header_style="bold cyan")
        table.add_column("Workspace", style="dim", width=4)
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

@app.command(name="config")
def config_cmd() -> None:
    """Create the config directory and write a default config.toml."""
    ensure_config_dir()
    if CONFIG_FILE.exists():
        console.print(f"[bold yellow]Config already exists at:[/bold yellow] {CONFIG_FILE}")
    else:
        console.print(f"[bold green]Created default config at:[/bold green] {CONFIG_FILE}")

def main() -> None:
    app()