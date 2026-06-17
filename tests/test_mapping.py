"""
test_mapping.py — Unit tests for mapping.py.

Tests: the resolve_command fallback chain, desktop file parsing,
and electron detection. Uses temporary directories for .desktop files
so tests don't depend on installed apps.
"""



from hypr_session.mapping import (
    _extract_field,
    _parse_exec_command,
    resolve_command,
)

# ---------------------------------------------------------------------------
# _extract_field
# ---------------------------------------------------------------------------


class TestExtractField:
    def test_basic_field(self):
        content = "[Desktop Entry]\nName=Firefox\nExec=firefox %u\n"
        assert _extract_field(content, "Exec") == "firefox %u"

    def test_field_in_desktop_entry_section_only(self):
        content = (
            "[Desktop Entry]\n"
            "Exec=real-exec\n"
            "[Desktop Action New]\n"
            "Exec=other-exec\n"
        )
        assert _extract_field(content, "Exec") == "real-exec"

    def test_missing_field_returns_none(self):
        content = "[Desktop Entry]\nName=Firefox\n"
        assert _extract_field(content, "StartupWMClass") is None

    def test_field_outside_section_ignored(self):
        content = "Exec=orphan\n[Desktop Entry]\nName=Test\n"
        assert _extract_field(content, "Exec") is None

    def test_startup_wm_class(self):
        content = "[Desktop Entry]\nStartupWMClass=org.kde.dolphin\nExec=dolphin\n"
        assert _extract_field(content, "StartupWMClass") == "org.kde.dolphin"


# ---------------------------------------------------------------------------
# _parse_exec_command
# ---------------------------------------------------------------------------


class TestParseExecCommand:
    def test_strips_field_codes(self):
        assert _parse_exec_command("firefox %u") == "firefox"
        assert _parse_exec_command("nautilus %U") == "nautilus"

    def test_takes_only_binary(self):
        assert _parse_exec_command("code --no-sandbox --unity-launch") == "code"

    def test_handles_absolute_path(self):
        # If the binary exists as absolute path, return basename
        result = _parse_exec_command("/usr/bin/dolphin %u")
        # result is either "dolphin" (if /usr/bin/dolphin exists) or "/usr/bin/dolphin"
        assert "dolphin" in result

    def test_empty_string(self):
        assert _parse_exec_command("") == ""


# ---------------------------------------------------------------------------
# resolve_command — the full fallback chain
# ---------------------------------------------------------------------------


class TestResolveCommand:
    def _resolve(self, initial_class, exe_path=None, bundled=None, desktop=None):
        return resolve_command(
            initial_class=initial_class,
            exe_path=exe_path,
            bundled_map=bundled or {},
            desktop_map=desktop or {},
        )

    # Stage 1: exe basename
    def test_stage1_uses_exe_basename(self):
        result = self._resolve(
            "firefox",
            exe_path="/usr/lib/firefox/firefox-bin",
        )
        assert result == "firefox-bin"

    def test_stage1_skips_electron_binary(self):
        # /usr/lib/electron32/electron → should fall through to stage 2/3
        result = self._resolve(
            "obsidian",
            exe_path="/usr/lib/electron32/electron",
            bundled={"obsidian": "obsidian"},
        )
        # Should reach stage 3 and return "obsidian"
        assert result == "obsidian"

    def test_stage1_skips_node_binary(self):
        result = self._resolve(
            "some-node-app",
            exe_path="/usr/bin/node",
            bundled={"some-node-app": "some-app"},
        )
        assert result == "some-app"

    # Stage 2: desktop map
    def test_stage2_uses_desktop_map(self):
        result = self._resolve(
            "org.kde.dolphin",
            exe_path=None,
            desktop={"org.kde.dolphin": "dolphin"},
        )
        assert result == "dolphin"

    def test_stage2_case_insensitive(self):
        result = self._resolve(
            "Org.KDE.Dolphin",
            exe_path=None,
            desktop={"org.kde.dolphin": "dolphin"},
        )
        assert result == "dolphin"

    # Stage 3: bundled map
    def test_stage3_uses_bundled_map(self):
        result = self._resolve(
            "code-url-handler",
            exe_path=None,
            bundled={"code-url-handler": "code"},
        )
        assert result == "code"

    # Stage 4: class name fallback
    def test_stage4_uses_class_name(self):
        result = self._resolve("firefox")
        assert result == "firefox"

    def test_stage4_unknown_app(self):
        result = self._resolve("some-unknown-app")
        assert result == "some-unknown-app"

    # Priority: stage 1 beats stage 2 beats stage 3
    def test_stage1_beats_stage2(self):
        result = self._resolve(
            "dolphin",
            exe_path="/usr/bin/dolphin",
            desktop={"dolphin": "wrong-from-desktop"},
        )
        # exe basename is "dolphin", which is not an electron binary → use it
        assert result == "dolphin"

    def test_stage2_beats_stage3(self):
        result = self._resolve(
            "org.kde.dolphin",
            exe_path=None,
            desktop={"org.kde.dolphin": "dolphin"},
            bundled={"org.kde.dolphin": "wrong-from-bundled"},
        )
        assert result == "dolphin"


class TestGetDesktopSearchDirs:
    def test_respects_xdg_data_dirs_and_home(self):
        import os
        from unittest.mock import patch

        from hypr_session.mapping import _get_desktop_search_dirs

        env_mock = {
            "XDG_DATA_HOME": "/tmp/custom_data_home",
            "XDG_DATA_DIRS": "/tmp/custom_dir1:/tmp/custom_dir2",
        }
        with patch.dict(os.environ, env_mock):
            dirs = _get_desktop_search_dirs()
            dir_strs = [str(d) for d in dirs]
            assert "/tmp/custom_data_home/applications" in dir_strs
            assert "/tmp/custom_dir1/applications" in dir_strs
            assert "/tmp/custom_dir2/applications" in dir_strs
            assert "/run/current-system/sw/share/applications" in dir_strs
            assert "/var/lib/snapd/desktop/applications" in dir_strs

    def test_flatpak_preserves_command(self):
        from hypr_session.mapping import _parse_exec_command
        assert _parse_exec_command("flatpak run com.spotify.Client") == "flatpak run com.spotify.Client"
        assert _parse_exec_command("/usr/bin/flatpak run com.spotify.Client") == "/usr/bin/flatpak run com.spotify.Client"

    def test_flatpak_app_not_skipped_in_desktop_map(self, tmp_path):
        from unittest.mock import patch

        from hypr_session.mapping import build_desktop_map

        desktop_file = tmp_path / "spotify.desktop"
        content = "[Desktop Entry]\nName=Spotify\nExec=flatpak run com.spotify.Client %U\nStartupWMClass=Spotify\n"
        desktop_file.write_text(content)

        with patch("hypr_session.mapping._get_desktop_search_dirs") as mock_get_dirs:
            mock_get_dirs.return_value = [tmp_path]
            res = build_desktop_map()
            assert "spotify" in res
            assert res["spotify"] == "flatpak run com.spotify.Client"
