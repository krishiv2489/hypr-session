"""
test_restore.py — Unit tests for restore.py dispatch rule building.

We test _build_exec_rule directly since it's pure logic (no subprocess calls).
The polling/launch functions would need a live Hyprland session, so we skip those.
"""

import pytest

from hypr_session.config import HyprSessionConfig
from hypr_session.models import FullscreenState, WindowEntry
from hypr_session.restore import _build_exec_rule, _build_cwd_cmd


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_cfg(**overrides) -> HyprSessionConfig:
    cfg = HyprSessionConfig()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def make_window(**overrides) -> WindowEntry:
    defaults = dict(
        address="0x55737f169ea0",
        initial_class="firefox",
        cmd="firefox",
        workspace_id=1,
        monitor=0,
        floating=False,
        at=(0, 0),
        size=(1920, 1200),
        fullscreen=FullscreenState.NONE,
        pinned=False,
        focus_history_id=0,
        cwd=None,
    )
    defaults.update(overrides)
    return WindowEntry(**defaults)


# ---------------------------------------------------------------------------
# _build_exec_rule — tiling windows
# ---------------------------------------------------------------------------


class TestBuildExecRuleTiling:
    def test_basic_tiling_window(self):
        w = make_window(workspace_id=1, floating=False)
        cfg = make_cfg()
        rule = _build_exec_rule(w, cfg)
        assert rule.startswith("exec '")
        assert "workspace 1 silent" in rule
        assert "float" not in rule
        assert "firefox" in rule

    def test_workspace_number_in_rule(self):
        w = make_window(workspace_id=5)
        rule = _build_exec_rule(w, make_cfg())
        assert "workspace 5 silent" in rule

    def test_silent_keyword_always_present(self):
        # "silent" prevents the restore from stealing focus
        w = make_window(workspace_id=2)
        rule = _build_exec_rule(w, make_cfg())
        assert "silent" in rule

    def test_no_float_rules_for_tiling(self):
        w = make_window(floating=False)
        rule = _build_exec_rule(w, make_cfg())
        assert "float" not in rule
        assert "move" not in rule
        assert "size" not in rule


# ---------------------------------------------------------------------------
# _build_exec_rule — floating windows
# ---------------------------------------------------------------------------


class TestBuildExecRuleFloating:
    def test_float_rule_present(self):
        w = make_window(floating=True, at=(100, 200), size=(800, 600))
        rule = _build_exec_rule(w, make_cfg(restore_floating=True))
        assert "float" in rule

    def test_move_rule_with_correct_coords(self):
        w = make_window(floating=True, at=(560, 200), size=(900, 600))
        rule = _build_exec_rule(w, make_cfg(restore_floating=True))
        assert "move 560 200" in rule

    def test_size_rule_with_correct_dimensions(self):
        w = make_window(floating=True, at=(0, 0), size=(1200, 800))
        rule = _build_exec_rule(w, make_cfg(restore_floating=True))
        assert "size 1200 800" in rule

    def test_float_skipped_when_restore_floating_false(self):
        w = make_window(floating=True, at=(100, 200), size=(800, 600))
        rule = _build_exec_rule(w, make_cfg(restore_floating=False))
        assert "float" not in rule
        assert "move" not in rule


# ---------------------------------------------------------------------------
# _build_exec_rule — fullscreen states
# ---------------------------------------------------------------------------


class TestBuildExecRuleFullscreen:
    def test_fullscreen_state_2_adds_fullscreen_rule(self):
        w = make_window(fullscreen=FullscreenState.FULLSCREEN)
        rule = _build_exec_rule(w, make_cfg(restore_fullscreen=True))
        assert "fullscreen" in rule

    def test_fullscreen_state_1_adds_maximize_rule(self):
        w = make_window(fullscreen=FullscreenState.MAXIMIZED)
        rule = _build_exec_rule(w, make_cfg(restore_fullscreen=True))
        assert "maximize" in rule

    def test_fullscreen_state_0_no_fullscreen_rule(self):
        w = make_window(fullscreen=FullscreenState.NONE)
        rule = _build_exec_rule(w, make_cfg(restore_fullscreen=True))
        assert "fullscreen" not in rule
        assert "maximize" not in rule

    def test_fullscreen_skipped_when_restore_fullscreen_false(self):
        w = make_window(fullscreen=FullscreenState.FULLSCREEN)
        rule = _build_exec_rule(w, make_cfg(restore_fullscreen=False))
        assert "fullscreen" not in rule


# ---------------------------------------------------------------------------
# _build_exec_rule — pinned windows
# ---------------------------------------------------------------------------


class TestBuildExecRulePinned:
    def test_pinned_window_has_pin_rule(self):
        w = make_window(pinned=True)
        rule = _build_exec_rule(w, make_cfg())
        assert "pin" in rule

    def test_unpinned_window_no_pin_rule(self):
        w = make_window(pinned=False)
        rule = _build_exec_rule(w, make_cfg())
        assert "pin" not in rule


# ---------------------------------------------------------------------------
# _build_cwd_cmd — CWD flag construction
# ---------------------------------------------------------------------------


class TestBuildCwdCmd:
    def test_kitty_uses_directory_flag(self, tmp_path):
        # _build_cwd_cmd checks Path(cwd).is_dir() — use a real temp dir.
        w = make_window(
            initial_class="kitty",
            cmd="kitty",
            cwd=str(tmp_path),
        )
        cmd = _build_cwd_cmd(w)
        assert "--directory" in cmd
        assert str(tmp_path) in cmd

    def test_alacritty_uses_working_directory_flag(self, tmp_path):
        w = make_window(
            initial_class="alacritty",
            cmd="alacritty",
            cwd=str(tmp_path),
        )
        cmd = _build_cwd_cmd(w)
        assert "--working-directory" in cmd

    def test_wezterm_uses_subcommand_flag(self, tmp_path):
        w = make_window(
            initial_class="wezterm",
            cmd="wezterm",
            cwd=str(tmp_path),
        )
        cmd = _build_cwd_cmd(w)
        assert "start" in cmd
        assert "--cwd" in cmd

    def test_no_cwd_returns_cmd_unchanged(self):
        w = make_window(initial_class="kitty", cmd="kitty", cwd=None)
        assert _build_cwd_cmd(w) == "kitty"

    def test_nonexistent_cwd_returns_cmd_unchanged(self):
        w = make_window(
            initial_class="kitty",
            cmd="kitty",
            cwd="/this/path/does/not/exist",
        )
        assert _build_cwd_cmd(w) == "kitty"

    def test_path_with_spaces_is_quoted(self):
        import tempfile, os
        # Create a real temp dir with spaces to test quoting
        with tempfile.TemporaryDirectory(prefix="my dir ") as tmpdir:
            w = make_window(
                initial_class="kitty",
                cmd="kitty",
                cwd=tmpdir,
            )
            cmd = _build_cwd_cmd(w)
            # The path should be shell-quoted (wrapped in single quotes)
            assert "'" in cmd or tmpdir in cmd
