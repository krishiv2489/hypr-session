import pytest
from unittest.mock import patch, MagicMock

from hypr_session.models import WindowEntry, Session
from hypr_session.session import get_current_session_windows
from hypr_session.restore import _build_dispatch_arg
from hypr_session.config import HyprSessionConfig

def test_special_workspace_save():
    clients = [
        {
            "address": "0x123",
            "class": "Kitty",
            "initialClass": "Kitty",
            "workspace": {"id": -99, "name": "special:magic"},
            "grouped": [],
            "floating": False,
        }
    ]
    with patch("hypr_session.session.run_hyprctl", return_value=clients):
        with patch("hypr_session.session.get_ancestor_pids", return_value=[]), \
             patch("hypr_session.session.build_desktop_map", return_value={}), \
             patch("hypr_session.session.load_bundled_map", return_value={}):
            windows = get_current_session_windows()
            assert len(windows) == 1
            assert windows[0].special_workspace_name == "special:magic"
            assert windows[0].group_id is None

def test_build_dispatch_arg_special_workspace():
    window = WindowEntry(
        address="0x123", initial_class="kitty", cmd="kitty",
        workspace_id=-99, monitor=0, floating=False, at=(0,0), size=(0,0),
        fullscreen=0, pinned=False, focus_history_id=0,
        special_workspace_name="special:magic"
    )
    cfg = HyprSessionConfig()
    arg = _build_dispatch_arg(window, cfg)
    assert "workspace special:magic silent" in arg

def test_grouped_windows():
    clients = [
        {
            "address": "0x111",
            "class": "Kitty",
            "initialClass": "Kitty",
            "workspace": {"id": 1, "name": "1"},
            "grouped": ["0x111", "0x222"],
        },
        {
            "address": "0x222",
            "class": "Firefox",
            "initialClass": "Firefox",
            "workspace": {"id": 1, "name": "1"},
            "grouped": ["0x111", "0x222"],
        }
    ]
    with patch("hypr_session.session.run_hyprctl", return_value=clients):
        with patch("hypr_session.session.get_ancestor_pids", return_value=[]), \
             patch("hypr_session.session.build_desktop_map", return_value={}), \
             patch("hypr_session.session.load_bundled_map", return_value={}):
            windows = get_current_session_windows()
            assert len(windows) == 2
            assert windows[0].group_id == "0x111"
            assert windows[1].group_id == "0x111"

def test_from_dict_v2_graceful():
    v2_session_dict = {
        "version": 2,
        "timestamp": "2024-01-01T00:00:00",
        "windows": [
            {
                "address": "0x123",
                "initial_class": "kitty",
                "cmd": "kitty",
                "workspace_id": 1,
                "monitor": 0,
                "floating": False,
                "at": [0, 0],
                "size": [800, 600],
                "fullscreen": 0,
                "pinned": False,
                "focus_history_id": 0
            }
        ]
    }
    session = Session.from_dict(v2_session_dict)
    assert session.version == 2
    assert len(session.windows) == 1
    assert session.windows[0].special_workspace_name is None
    assert session.windows[0].group_id is None
