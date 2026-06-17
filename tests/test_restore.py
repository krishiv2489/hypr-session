"""
test_restore.py — Unit tests for restore.py dispatch rule building.
"""

from typing import Any

from hypr_session.config import HyprSessionConfig
from hypr_session.models import FullscreenState, WindowEntry
from hypr_session.restore import _build_cwd_cmd, _build_dispatch_arg


def make_cfg(**overrides: Any) -> HyprSessionConfig:
    cfg = HyprSessionConfig()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg

def make_window(**overrides: Any) -> WindowEntry:
    """Explicitly cast types to satisfy strict IDE type checkers like Pylance."""
    at_val = overrides.get("at", (0, 0))
    size_val = overrides.get("size", (1920, 1200))
    cwd_val = overrides.get("cwd")

    return WindowEntry(
        address=str(overrides.get("address", "0x55737f169ea0")),
        initial_class=str(overrides.get("initial_class", "firefox")),
        cmd=str(overrides.get("cmd", "firefox")),
        workspace_id=int(overrides.get("workspace_id", 1)),
        monitor=int(overrides.get("monitor", 0)),
        floating=bool(overrides.get("floating", False)),
        at=(int(at_val[0]), int(at_val[1])) if isinstance(at_val, tuple) else (0, 0),
        size=(int(size_val[0]), int(size_val[1])) if isinstance(size_val, tuple) else (1920, 1200),
        fullscreen=int(overrides.get("fullscreen", FullscreenState.NONE)),
        pinned=bool(overrides.get("pinned", False)),
        focus_history_id=int(overrides.get("focus_history_id", 0)),
        cwd=str(cwd_val) if cwd_val is not None else None,
    )

class TestBuildDispatchArgTiling:
    def test_basic_tiling_window(self):
        w = make_window(workspace_id=1, floating=False)
        cfg = make_cfg()
        arg = _build_dispatch_arg(w, cfg)
        assert arg.startswith("[")
        assert "workspace 1 silent" in arg
        assert "float" not in arg
        assert "firefox" in arg

    def test_workspace_number_in_arg(self):
        w = make_window(workspace_id=5)
        arg = _build_dispatch_arg(w, make_cfg())
        assert "workspace 5 silent" in arg

    def test_silent_keyword_always_present(self):
        w = make_window(workspace_id=2)
        arg = _build_dispatch_arg(w, make_cfg())
        assert "silent" in arg

    def test_no_float_rules_for_tiling(self):
        w = make_window(floating=False)
        arg = _build_dispatch_arg(w, make_cfg())
        assert "float" not in arg
        assert "move" not in arg
        assert "size" not in arg

class TestBuildDispatchArgFloating:
    def test_float_rule_present(self):
        w = make_window(floating=True, at=(100, 200), size=(800, 600))
        arg = _build_dispatch_arg(w, make_cfg(restore_floating=True))
        assert "float" in arg

    def test_move_rule_with_correct_coords(self):
        w = make_window(floating=True, at=(560, 200), size=(900, 600))
        arg = _build_dispatch_arg(w, make_cfg(restore_floating=True))
        assert "move 560 200" in arg

    def test_size_rule_with_correct_dimensions(self):
        w = make_window(floating=True, at=(0, 0), size=(1200, 800))
        arg = _build_dispatch_arg(w, make_cfg(restore_floating=True))
        assert "size 1200 800" in arg

    def test_float_skipped_when_restore_floating_false(self):
        w = make_window(floating=True, at=(100, 200), size=(800, 600))
        arg = _build_dispatch_arg(w, make_cfg(restore_floating=False))
        assert "float" not in arg
        assert "move" not in arg

class TestBuildCwdCmd:
    def test_kitty_uses_directory_flag(self, tmp_path):
        w = make_window(initial_class="kitty", cmd="kitty", cwd=str(tmp_path))
        cfg = make_cfg(restore_cwd=True)
        cmd = _build_cwd_cmd(w, cfg)
        assert "--directory" in cmd
        assert str(tmp_path) in cmd

    def test_path_with_spaces_is_quoted(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="my dir ") as tmpdir:
            w = make_window(initial_class="kitty", cmd="kitty", cwd=tmpdir)
            cfg = make_cfg(restore_cwd=True)
            cmd = _build_cwd_cmd(w, cfg)
            assert "'" in cmd or '"' in cmd

    def test_cwd_skipped_when_restore_cwd_false(self, tmp_path):
        w = make_window(initial_class="kitty", cmd="kitty", cwd=str(tmp_path))
        cfg = make_cfg(restore_cwd=False)
        cmd = _build_cwd_cmd(w, cfg)
        assert "--directory" not in cmd
        assert cmd == "kitty"
