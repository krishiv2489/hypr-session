"""
models.py — Core data structures for hypr-session.

Everything saved to disk and loaded from disk passes through these classes.
No external dependencies. No imports from the rest of this package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FullscreenState(IntEnum):
    """
    Maps Hyprland's fullscreen integer field to a readable name.

    From hyprctl -j clients:
      "fullscreen": 0  → normal window
      "fullscreen": 1  → compositor-managed maximize (fills workspace, keeps borders)
      "fullscreen": 2  → true fullscreen (covers everything, no borders)

    mpv in your real session had fullscreen: 2.
    """

    NONE = 0
    MAXIMIZED = 1
    FULLSCREEN = 2


# ---------------------------------------------------------------------------
# WindowEntry
# ---------------------------------------------------------------------------


@dataclass
class WindowEntry:
    """
    One saved window. Built from hyprctl -j clients output + /proc data.

    Fields that ARE saved (and why):
      address         — unique Hyprland window ID; used for before/after diffing
      initial_class   — XDG app-id at window creation; stable across title changes
      cmd             — resolved launch command (from /proc/<pid>/exe or mapping engine)
      workspace_id    — which workspace to restore to
      monitor         — which physical display (critical for multi-monitor)
      floating        — whether to restore as floating with exact position/size
      at              — (x, y) pixel position; only meaningful if floating
      size            — (width, height) in pixels; only meaningful if floating
      fullscreen      — 0/1/2 state to re-apply after launch
      pinned          — whether the window was visible on all workspaces
      focus_history_id — Hyprland's focus order; determines tiling restore order
      cwd             — working directory of foreground shell (terminal emulators only)

    Fields that are NOT saved (and why):
      pid             — ephemeral; invalid after shutdown, PID recycling makes it meaningless
      title           — changes dynamically; privacy-sensitive (contains URLs, filenames)
      visible         — derived from layout state, not a property to restore
      xwayland        — runtime protocol detail, not needed for restoration
      swallowing      — transient terminal state
      stableId        — session-scoped only, meaningless across boots
    """

    # Identity
    address: str             # e.g. "0x55737f169ea0"
    initial_class: str       # e.g. "org.kde.dolphin"
    cmd: str                 # e.g. "dolphin"

    # Placement
    workspace_id: int        # e.g. 1
    monitor: int             # e.g. 0

    # Layout geometry
    floating: bool
    at: tuple[int, int]      # (x, y) — only use if floating
    size: tuple[int, int]    # (w, h) — only use if floating

    # Extra states
    fullscreen: int          # FullscreenState value (0, 1, 2)
    pinned: bool

    # Tiling restore order — sort descending by this before restoring
    focus_history_id: int

    # Terminal context — populated only for terminal emulator classes
    cwd: str | None = None

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to a JSON-serializable dict.

        We write at and size as lists because JSON has no tuple type.
        from_dict converts them back to tuples on load.
        """
        return {
            "address": self.address,
            "initial_class": self.initial_class,
            "cmd": self.cmd,
            "workspace_id": self.workspace_id,
            "monitor": self.monitor,
            "floating": self.floating,
            "at": list(self.at),
            "size": list(self.size),
            "fullscreen": self.fullscreen,
            "pinned": self.pinned,
            "focus_history_id": self.focus_history_id,
            "cwd": self.cwd,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WindowEntry:
        """Reconstruct a WindowEntry from a JSON-loaded dict."""
        return cls(
            address=d["address"],
            initial_class=d["initial_class"],
            cmd=d["cmd"],
            workspace_id=d["workspace_id"],
            monitor=d["monitor"],
            floating=d["floating"],
            at=tuple(d["at"]),      # type: ignore[arg-type]
            size=tuple(d["size"]),  # type: ignore[arg-type]
            fullscreen=d["fullscreen"],
            pinned=d["pinned"],
            focus_history_id=d["focus_history_id"],
            cwd=d.get("cwd"),
        )

    def __repr__(self) -> str:
        fs = FullscreenState(self.fullscreen).name
        return (
            f"WindowEntry({self.initial_class!r} ws={self.workspace_id} "
            f"float={self.floating} fs={fs} cmd={self.cmd!r})"
        )


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


@dataclass
class Session:
    """
    A complete saved session — a list of WindowEntry objects plus metadata.

    version: bumped when the on-disk format changes in a breaking way.
    timestamp: ISO-8601 string of when the session was saved.
    windows: ordered list of WindowEntry; restored in this order.
    """

    version: int = 2
    timestamp: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    windows: list[WindowEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "timestamp": self.timestamp,
            "windows": [w.to_dict() for w in self.windows],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Session:
        """
        Load a Session from a JSON dict.

        Raises ValueError if the version field is missing or incompatible.
        We check version so that future breaking changes in the format can
        be detected and the user given a clear error instead of a crash.
        """
        version = d.get("version", 1)
        if version > 2:
            raise ValueError(
                f"Session file version {version} is newer than this tool supports (2). "
                "Please upgrade hypr-session."
            )
        return cls(
            version=version,
            timestamp=d.get("timestamp", "unknown"),
            windows=[WindowEntry.from_dict(w) for w in d.get("windows", [])],
        )

    def __repr__(self) -> str:
        return f"Session(v{self.version}, {len(self.windows)} windows, saved={self.timestamp})"
