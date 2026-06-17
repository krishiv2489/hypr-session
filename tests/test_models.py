"""
test_models.py — Unit tests for models.py.

Tests: serialization round-trips, from_dict edge cases, __repr__ output.
No external dependencies, no mocking needed — models are pure Python.
"""

import pytest

from hypr_session.models import FullscreenState, Session, WindowEntry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_window(**overrides) -> WindowEntry:
    """Return a WindowEntry with sane defaults, overriding any given fields."""
    defaults = {
        "address": "0x55737f169ea0",
        "initial_class": "firefox",
        "cmd": "firefox",
        "workspace_id": 1,
        "monitor": 0,
        "floating": False,
        "at": (6, 62),
        "size": (1908, 1132),
        "fullscreen": FullscreenState.NONE,
        "pinned": False,
        "focus_history_id": 1,
        "cwd": None,
    }
    defaults.update(overrides)
    return WindowEntry(**defaults)


def make_session(*windows: WindowEntry) -> Session:
    return Session(
        version=2,
        timestamp="2026-01-01T12:00:00",
        windows=list(windows),
    )


# ---------------------------------------------------------------------------
# WindowEntry serialization
# ---------------------------------------------------------------------------


class TestWindowEntrySerialization:
    def test_to_dict_returns_dict(self):
        w = make_window()
        d = w.to_dict()
        assert isinstance(d, dict)

    def test_at_and_size_serialized_as_list(self):
        # JSON has no tuple type — we write as list and convert back on load.
        w = make_window(at=(10, 20), size=(800, 600))
        d = w.to_dict()
        assert d["at"] == [10, 20]
        assert d["size"] == [800, 600]
        assert isinstance(d["at"], list)
        assert isinstance(d["size"], list)

    def test_round_trip_tiling_window(self):
        w = make_window(
            initial_class="firefox",
            cmd="firefox",
            workspace_id=1,
            floating=False,
            fullscreen=FullscreenState.NONE,
        )
        restored = WindowEntry.from_dict(w.to_dict())
        assert restored.initial_class == w.initial_class
        assert restored.cmd == w.cmd
        assert restored.workspace_id == w.workspace_id
        assert restored.floating == w.floating
        assert restored.at == w.at     # must be tuple after from_dict
        assert restored.size == w.size  # must be tuple after from_dict
        assert isinstance(restored.at, tuple)
        assert isinstance(restored.size, tuple)

    def test_round_trip_floating_window(self):
        w = make_window(
            floating=True,
            at=(560, 200),
            size=(900, 600),
            fullscreen=FullscreenState.NONE,
        )
        restored = WindowEntry.from_dict(w.to_dict())
        assert restored.floating is True
        assert restored.at == (560, 200)
        assert restored.size == (900, 600)

    def test_round_trip_fullscreen_window(self):
        w = make_window(fullscreen=FullscreenState.FULLSCREEN)
        restored = WindowEntry.from_dict(w.to_dict())
        assert restored.fullscreen == FullscreenState.FULLSCREEN

    def test_round_trip_with_cwd(self):
        w = make_window(
            initial_class="kitty",
            cmd="kitty",
            cwd="/home/krishiv/projects/hypr-session",
        )
        restored = WindowEntry.from_dict(w.to_dict())
        assert restored.cwd == "/home/krishiv/projects/hypr-session"

    def test_cwd_none_preserved(self):
        w = make_window(cwd=None)
        restored = WindowEntry.from_dict(w.to_dict())
        assert restored.cwd is None

    def test_pinned_window(self):
        w = make_window(pinned=True)
        restored = WindowEntry.from_dict(w.to_dict())
        assert restored.pinned is True

    def test_all_fields_present_in_dict(self):
        w = make_window()
        d = w.to_dict()
        expected_keys = {
            "address", "initial_class", "cmd", "workspace_id", "monitor",
            "floating", "at", "size", "fullscreen", "pinned",
            "focus_history_id", "cwd",
        }
        assert set(d.keys()) == expected_keys


class TestWindowEntryRepr:
    def test_repr_contains_class(self):
        w = make_window(initial_class="dolphin")
        assert "dolphin" in repr(w)

    def test_repr_contains_workspace(self):
        w = make_window(workspace_id=3)
        assert "ws=3" in repr(w)


# ---------------------------------------------------------------------------
# Session serialization
# ---------------------------------------------------------------------------


class TestSessionSerialization:
    def test_empty_session_round_trip(self):
        s = make_session()
        restored = Session.from_dict(s.to_dict())
        assert restored.version == s.version
        assert restored.timestamp == s.timestamp
        assert restored.windows == []

    def test_session_with_windows_round_trip(self):
        w1 = make_window(initial_class="firefox", workspace_id=1)
        w2 = make_window(initial_class="kitty", workspace_id=3, cmd="kitty")
        s = make_session(w1, w2)
        restored = Session.from_dict(s.to_dict())
        assert len(restored.windows) == 2
        assert restored.windows[0].initial_class == "firefox"
        assert restored.windows[1].initial_class == "kitty"

    def test_version_field_preserved(self):
        s = make_session()
        assert s.to_dict()["version"] == 2

    def test_future_version_raises(self):
        d = make_session().to_dict()
        d["version"] = 99
        with pytest.raises(ValueError, match="newer than this tool supports"):
            Session.from_dict(d)

    def test_missing_windows_defaults_to_empty(self):
        d = {"version": 2, "timestamp": "2026-01-01T00:00:00"}
        s = Session.from_dict(d)
        assert s.windows == []


# ---------------------------------------------------------------------------
# FullscreenState
# ---------------------------------------------------------------------------


class TestFullscreenState:
    def test_values(self):
        assert FullscreenState.NONE == 0
        assert FullscreenState.MAXIMIZED == 1
        assert FullscreenState.FULLSCREEN == 2

    def test_from_int(self):
        assert FullscreenState(0) == FullscreenState.NONE
        assert FullscreenState(2) == FullscreenState.FULLSCREEN

    def test_name(self):
        assert FullscreenState(2).name == "FULLSCREEN"
