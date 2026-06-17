"""
cli.py — Command-line interface for hypr-session.

All user-facing commands are defined here. The business logic lives in
session.py and restore.py. This file only does argument parsing, validation,
and output formatting.

Commands:
  save     — save current session (optionally named)
  restore  — restore a saved session
  list     — show all saved sessions
  clear    — delete a saved session
  pause    — disable auto-save without changing anything
  resume   — re-enable auto-save
  status   — show current configuration and session state
  config   — write the default config file to ~/.config/hypr-session/
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer

from .config import (
    CONFIG_DIR,
    CONFIG_FILE,
    DATA_DIR,
    PAUSE_LOCK,
    ensure_config_dir,
    load_config,
)
from .restore import restore_session as _restore
from .session import (
    clear_all_sessions,
    clear_session,
    list_sessions,
    load_session,
    save_session,
)
from .utils import is_hyprland_running

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="hypr-session",
    help=(
        "Session save and restore for the Hyprland Wayland compositor.\n\n"
        "Quick start:\n"
        "  1. Add to hyprland.conf: exec-once = hypr-session restore\n"
        "  2. Override your exit bind: bind = SUPER SHIFT, Q, exec, "
        "hypr-session save && hyprctl dispatch exit\n"
        "  3. That's it."
    ),
    no_args_is_help=True,
    pretty_exceptions_enable=False,  # We handle errors ourselves
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _require_hyprland() -> None:
    """Exit with a clear error if we're not inside Hyprland."""
    if not is_hyprland_running():
        typer.echo(
            "Error: HYPRLAND_INSTANCE_SIGNATURE is not set.\n"
            "This command must be run inside a Hyprland session.",
            err=True,
        )
        raise typer.Exit(1)


def _check_paused() -> bool:
    """Print a warning and return True if auto-save is paused."""
    if PAUSE_LOCK.exists():
        typer.echo(
            "Note: Session auto-save is paused.\n"
            "Run 'hypr-session resume' to re-enable.",
            err=True,
        )
        return True
    return False


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


@app.command()
def save(
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        "-p",
        help="Save under a named profile (e.g. 'work', 'gaming').",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Save even if auto-save is currently paused.",
    ),
) -> None:
    """Save the current Hyprland session to disk."""
    _require_hyprland()

    if not force and _check_paused():
        # If paused and not forced, exit silently with 0 so the keybind
        # sequence (save && exit) still proceeds to exit Hyprland.
        raise typer.Exit(0)

    try:
        path, session = save_session(profile)
    except RuntimeError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)

    label = profile or "default"
    count = len(session.windows)
    typer.echo(f"Saved session '{label}': {count} window(s) → {path}")


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------


@app.command()
def restore(
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        "-p",
        help="Restore a specific named profile.",
    ),
) -> None:
    """Restore the saved Hyprland session."""
    _require_hyprland()

    try:
        restored, failed = _restore(profile)
    except RuntimeError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)

    if failed > 0:
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@app.command(name="list")
def list_cmd() -> None:
    """List all saved sessions with window counts and timestamps."""
    sessions = list_sessions()

    if not sessions:
        typer.echo("No saved sessions found.")
        typer.echo(f"Run 'hypr-session save' to create one.")
        return

    typer.echo(f"{'PROFILE':<20}  {'WINDOWS':>7}  SAVED")
    typer.echo("-" * 50)

    for label, path, session in sessions:
        if session:
            typer.echo(
                f"{label:<20}  {len(session.windows):>7}  {session.timestamp[:19]}"
            )
        else:
            typer.echo(f"{label:<20}  {'?':>7}  [corrupted — run clear]")


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


@app.command()
def clear(
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        "-p",
        help="Clear a specific named profile. Clears default if omitted.",
    ),
    all_profiles: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Clear ALL saved sessions.",
    ),
) -> None:
    """Delete one or all saved sessions."""
    if all_profiles:
        count = clear_all_sessions()
        typer.echo(f"Cleared {count} session(s).")
        return

    label = profile or "default"
    deleted = clear_session(profile)
    if deleted:
        typer.echo(f"Session '{label}' cleared.")
    else:
        typer.echo(f"No session found for profile '{label}'.")


# ---------------------------------------------------------------------------
# pause
# ---------------------------------------------------------------------------


@app.command()
def pause() -> None:
    """
    Disable automatic session saving.

    When paused, 'hypr-session save' exits immediately without saving.
    This is useful if you want to shut down without saving the current layout
    (e.g. you're in the middle of something you don't want to restore).
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PAUSE_LOCK.touch()
    typer.echo("Auto-save paused. Run 'hypr-session resume' to re-enable.")


# ---------------------------------------------------------------------------
# resume
# ---------------------------------------------------------------------------


@app.command()
def resume() -> None:
    """Re-enable session saving after a pause."""
    if PAUSE_LOCK.exists():
        PAUSE_LOCK.unlink()
        typer.echo("Auto-save resumed.")
    else:
        typer.echo("Auto-save was not paused.")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status() -> None:
    """Show the current status, configuration, and saved sessions."""
    paused = PAUSE_LOCK.exists()
    cfg = load_config()
    sessions = list_sessions()

    typer.echo("─── hypr-session status ─────────────────────────────")
    typer.echo(f"  Auto-save:    {'PAUSED ⚠' if paused else 'active'}")
    typer.echo(f"  Config file:  {CONFIG_FILE}")
    typer.echo(f"  Data dir:     {DATA_DIR}")
    typer.echo("")
    typer.echo("─── Configuration ───────────────────────────────────")
    typer.echo(f"  restore_delay_seconds : {cfg.restore_delay_seconds}")
    typer.echo(f"  window_wait_timeout   : {cfg.window_wait_timeout}")
    typer.echo(f"  restore_floating      : {cfg.restore_floating}")
    typer.echo(f"  restore_fullscreen    : {cfg.restore_fullscreen}")
    typer.echo(f"  restore_cwd           : {cfg.restore_cwd}")
    typer.echo(f"  ignored classes       : {len(cfg.ignore_classes)} total")
    if cfg.extra_ignore_classes:
        typer.echo(f"  user extra ignores    : {sorted(cfg.extra_ignore_classes)}")
    typer.echo("")
    typer.echo("─── Saved Sessions ──────────────────────────────────")
    if not sessions:
        typer.echo("  (none)")
    else:
        for label, path, session in sessions:
            if session:
                typer.echo(
                    f"  [{label}]  {len(session.windows)} window(s)  "
                    f"saved: {session.timestamp[:19]}"
                )
                for w in session.windows:
                    fs_label = (
                        " [fullscreen]" if w.fullscreen == 2
                        else " [maximized]" if w.fullscreen == 1
                        else ""
                    )
                    float_label = " [float]" if w.floating else ""
                    cwd_label = f" cwd={w.cwd}" if w.cwd else ""
                    typer.echo(
                        f"       ws{w.workspace_id}  {w.initial_class:<30} "
                        f"cmd={w.cmd}{float_label}{fs_label}{cwd_label}"
                    )
            else:
                typer.echo(f"  [{label}]  [corrupted]  path={path}")
    typer.echo("─────────────────────────────────────────────────────")


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


@app.command(name="config")
def config_cmd() -> None:
    """
    Create the config directory and write a default config.toml if none exists.

    Safe to run multiple times — won't overwrite an existing config.
    """
    ensure_config_dir()
    if CONFIG_FILE.exists():
        typer.echo(f"Config already exists at: {CONFIG_FILE}")
        typer.echo("Edit it with your preferred text editor.")
    else:
        typer.echo(f"Created default config at: {CONFIG_FILE}")
    typer.echo(f"Data directory: {DATA_DIR}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    app()
