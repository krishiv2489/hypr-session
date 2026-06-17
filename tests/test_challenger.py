import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from hypr_session.cli import app
from hypr_session.mapping import _get_desktop_search_dirs, _parse_exec_command
from hypr_session.models import Session, WindowEntry
from hypr_session.session import get_session_path, list_sessions, load_session, save_session


@pytest.fixture
def mock_env(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    config_dir = tmp_path / "config"
    data_dir.mkdir()
    config_dir.mkdir()

    monkeypatch.setenv("XDG_DATA_HOME", str(data_dir))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "mock_sig_123")

    # Patch modules' global state/constants
    import hypr_session.cli
    import hypr_session.config
    import hypr_session.restore
    import hypr_session.session

    monkeypatch.setattr(hypr_session.config, "DATA_DIR", data_dir)
    monkeypatch.setattr(hypr_session.config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(hypr_session.config, "CONFIG_FILE", config_dir / "config.toml")
    monkeypatch.setattr(hypr_session.config, "BACKUPS_DIR", data_dir / "backups")
    monkeypatch.setattr(hypr_session.config, "PERMANENT_PAUSE_LOCK", config_dir / "disabled")

    monkeypatch.setattr(hypr_session.cli, "DATA_DIR", data_dir)
    monkeypatch.setattr(hypr_session.cli, "CONFIG_FILE", config_dir / "config.toml")
    monkeypatch.setattr(hypr_session.cli, "PERMANENT_PAUSE_LOCK", config_dir / "disabled")

    monkeypatch.setattr(hypr_session.session, "DATA_DIR", data_dir)
    monkeypatch.setattr(hypr_session.session, "BACKUPS_DIR", data_dir / "backups")

    return data_dir, config_dir

# ---------------------------------------------------------------------------
# 1. Robustness fixes
# ---------------------------------------------------------------------------

def test_get_desktop_search_dirs_robustness(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data_home"))
    monkeypatch.setenv("XDG_DATA_DIRS", f"{tmp_path}/dir1:{tmp_path}/dir2::")

    original_exists = Path.exists
    def exists_mock(self):
        if "flatpak" in str(self):
            return True
        return original_exists(self)

    with patch.object(Path, "exists", exists_mock):
        dirs = _get_desktop_search_dirs()
        dir_strs = [str(d) for d in dirs]

        # Check XDG
        assert str(tmp_path / "data_home" / "applications") in dir_strs
        assert str(tmp_path / "dir1" / "applications") in dir_strs
        assert str(tmp_path / "dir2" / "applications") in dir_strs
        # Check NixOS
        assert "/run/current-system/sw/share/applications" in dir_strs
        # Check Snap
        assert "/var/lib/snapd/desktop/applications" in dir_strs
        # Check Flatpak
        assert "/var/lib/flatpak/exports/share/applications" in dir_strs
        assert str(Path.home() / ".local/share/flatpak/exports/share/applications") in dir_strs

def test_flatpak_handling_in_exec_parsing():
    # Verify we correctly parse flatpak commands
    assert _parse_exec_command("flatpak run org.mozilla.firefox %u") == "flatpak run org.mozilla.firefox"
    assert _parse_exec_command("/usr/bin/flatpak run org.kde.okular --foo") == "/usr/bin/flatpak run org.kde.okular --foo"
    assert _parse_exec_command("flatpak list") == "flatpak"  # not "run" subcommand

def test_secure_tmp_fallback_permissions(monkeypatch, tmp_path):
    # Simulate non-existent /run/user/<uid> and verify we create /tmp/hypr-session-<uid> securely
    # Set high UID
    unique_uid = 299999
    tmp_fallback = Path(f"/tmp/hypr-session-{unique_uid}")
    if tmp_fallback.exists():
        shutil.rmtree(tmp_fallback, ignore_errors=True)

    # Patch XDG_RUNTIME_DIR to non-existent, and getuid to unique_uid
    monkeypatch.setenv("XDG_RUNTIME_DIR", "")
    with patch("os.getuid", return_value=unique_uid):
        import importlib

        import hypr_session.config
        importlib.reload(hypr_session.config)

        assert hypr_session.config.RUNTIME_PAUSE_LOCK == tmp_fallback / "hypr-session.paused"
        assert tmp_fallback.exists()
        # Ensure directory is 0o700
        stat = tmp_fallback.stat()
        assert (stat.st_mode & 0o777) == 0o700

    # Clean up
    shutil.rmtree(tmp_fallback, ignore_errors=True)

def test_secure_tmp_fallback_mkdir_exception(monkeypatch):
    # If mkdir throws an error, make sure reload doesn't crash
    monkeypatch.setenv("XDG_RUNTIME_DIR", "")
    with patch("os.getuid", return_value=399999), \
         patch("pathlib.Path.mkdir", side_effect=PermissionError("Permission Denied")):
        import importlib

        import hypr_session.config
        # Should complete without throwing an exception
        importlib.reload(hypr_session.config)

def test_backup_rotation_logic(mock_env, monkeypatch):
    data_dir, _ = mock_env
    windows = [
        WindowEntry(address="0x1", initial_class="kitty", cmd="kitty", workspace_id=1, monitor=0, floating=False, at=(0,0), size=(0,0), fullscreen=0, pinned=False, focus_history_id=1)
    ]
    monkeypatch.setattr("hypr_session.session.get_current_session_windows", lambda only_active=False: windows)

    # Mock time.time to return an incrementing counter so each save gets a unique filename
    time_counter = [1000]
    def mock_time():
        time_counter[0] += 1
        return time_counter[0]

    with patch("time.time", mock_time):
        # Perform 15 saves
        for _ in range(15):
            save_session(profile="rotation_test")

    backups_dir = data_dir / "backups"
    backups = list(backups_dir.glob("session-rotation_test.json.*.bak"))
    assert len(backups) == 10

# ---------------------------------------------------------------------------
# 2. UI/UX feature updates & targeted flags
# ---------------------------------------------------------------------------

def test_diff_visual_formatting_runner(mock_env, monkeypatch):
    # Test rendering differences via diff command
    saved = Session(windows=[
        WindowEntry(address="0x1", initial_class="kitty", cmd="kitty", workspace_id=1, monitor=0, floating=True, at=(10, 10), size=(100, 100), fullscreen=0, pinned=False, focus_history_id=1),
        WindowEntry(address="0x2", initial_class="firefox", cmd="firefox", workspace_id=2, monitor=0, floating=False, at=(0,0), size=(0,0), fullscreen=0, pinned=False, focus_history_id=2)
    ])

    # Active desktop has:
    # 1. kitty (floating but different geometry)
    # 2. chromium (new)
    # 3. firefox is missing
    active = [
        WindowEntry(address="0x3", initial_class="kitty", cmd="kitty", workspace_id=1, monitor=0, floating=True, at=(20, 20), size=(100, 100), fullscreen=0, pinned=False, focus_history_id=1),
        WindowEntry(address="0x4", initial_class="chromium", cmd="chromium", workspace_id=3, monitor=0, floating=False, at=(0,0), size=(0,0), fullscreen=0, pinned=False, focus_history_id=3)
    ]

    monkeypatch.setattr("hypr_session.cli.load_session", lambda profile: saved)
    monkeypatch.setattr("hypr_session.cli.get_current_session_windows", lambda: active)
    monkeypatch.setattr("hypr_session.cli.is_hyprland_running", lambda: True)

    runner = CliRunner()
    result = runner.invoke(app, ["diff"])
    assert result.exit_code == 0
    assert "Session Comparison" in result.stdout
    assert "Δ geom" in result.stdout
    assert "<- missing" in result.stdout
    assert "new ->" in result.stdout
    assert "Warning: Some floating window geometries differ" in result.stdout

def test_status_tree_rendering_runner(mock_env, monkeypatch):
    session = Session(windows=[
        WindowEntry(address="0x1", initial_class="kitty", cmd="kitty", workspace_id=1, monitor=0, floating=False, at=(0,0), size=(0,0), fullscreen=0, pinned=False, focus_history_id=1, cwd="/home/user"),
        WindowEntry(address="0x2", initial_class="firefox", cmd="firefox", workspace_id=2, monitor=1, floating=True, at=(10,10), size=(500,500), fullscreen=0, pinned=True, focus_history_id=2)
    ])

    monkeypatch.setattr("hypr_session.cli.list_sessions", lambda: [("test_profile", Path("session-test_profile.json"), session)])

    runner = CliRunner()
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "Profile: test_profile" in result.stdout
    assert "Monitor 0" in result.stdout
    assert "Monitor 1" in result.stdout
    assert "Workspace 1" in result.stdout
    assert "Workspace 2" in result.stdout
    assert "kitty (tiling)" in result.stdout
    assert "cwd: /home/user" in result.stdout
    assert "firefox (floating)" in result.stdout

def test_restore_workspace_flag_validation(mock_env, monkeypatch):
    session = Session(windows=[
        WindowEntry(address="0x1", initial_class="kitty", cmd="kitty", workspace_id=1, monitor=0, floating=False, at=(0,0), size=(0,0), fullscreen=0, pinned=False, focus_history_id=1)
    ])
    monkeypatch.setattr("hypr_session.cli.load_session", lambda profile: session)

    runner = CliRunner()
    result = runner.invoke(app, ["restore", "--workspace", "1,a,2"])
    assert result.exit_code == 1
    assert "Error: --workspace must be a comma-separated list of integers." in result.stdout

def test_missing_hyprland_env_error(mock_env, monkeypatch):
    # Remove HYPRLAND_INSTANCE_SIGNATURE
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    runner = CliRunner()

    result = runner.invoke(app, ["save"])
    assert result.exit_code == 1
    assert "Error: HYPRLAND_INSTANCE_SIGNATURE is not set." in result.stdout

# ---------------------------------------------------------------------------
# 3. Profile management commands edge cases
# ---------------------------------------------------------------------------

def test_profile_rename_edge_cases(mock_env):
    runner = CliRunner()

    # Old profile does not exist
    result = runner.invoke(app, ["rename", "non_existent", "target"])
    assert result.exit_code == 1
    assert "Error: Profile 'non_existent' does not exist." in result.stdout

    # Create source profile
    src_path = get_session_path("source_profile")
    src_path.write_text('{"version": 2, "timestamp": "2026", "windows": []}')

    # Target profile already exists
    dest_path = get_session_path("dest_profile")
    dest_path.write_text('{"version": 2, "timestamp": "2026", "windows": []}')

    result = runner.invoke(app, ["rename", "source_profile", "dest_profile"])
    assert result.exit_code == 1
    assert "Error: Profile 'dest_profile' already exists." in result.stdout

    # Shutil move throws exception
    with patch("shutil.move", side_effect=OSError("Disk Full")):
        result = runner.invoke(app, ["rename", "source_profile", "new_profile"])
        assert result.exit_code == 1
        assert "Error renaming profile" in result.stdout

def test_profile_copy_edge_cases(mock_env):
    runner = CliRunner()

    # Source profile does not exist
    result = runner.invoke(app, ["copy", "non_existent", "target"])
    assert result.exit_code == 1
    assert "Error: Profile 'non_existent' does not exist." in result.stdout

    # Create source
    src_path = get_session_path("source_profile")
    src_path.write_text('{"version": 2, "timestamp": "2026", "windows": []}')

    # Dest profile already exists
    dest_path = get_session_path("dest_profile")
    dest_path.write_text('{"version": 2, "timestamp": "2026", "windows": []}')

    result = runner.invoke(app, ["copy", "source_profile", "dest_profile"])
    assert result.exit_code == 1
    assert "Error: Profile 'dest_profile' already exists." in result.stdout

    # Shutil copy2 raises exception
    with patch("shutil.copy2", side_effect=PermissionError("Permission Denied")):
        result = runner.invoke(app, ["copy", "source_profile", "new_profile"])
        assert result.exit_code == 1
        assert "Error copying profile" in result.stdout

def test_profile_export_edge_cases(mock_env, tmp_path):
    runner = CliRunner()

    # Source does not exist
    result = runner.invoke(app, ["export", "non_existent", str(tmp_path / "export.json")])
    assert result.exit_code == 1
    assert "Error: Profile 'non_existent' does not exist." in result.stdout

    # Create source
    src_path = get_session_path("source_profile")
    src_path.write_text('{"version": 2, "timestamp": "2026", "windows": []}')

    # Destination already exists
    dest_file = tmp_path / "exists.json"
    dest_file.write_text("content")
    result = runner.invoke(app, ["export", "source_profile", str(dest_file)])
    assert result.exit_code == 1
    assert "already exists" in result.stdout

    # Export to nested non-existent directory (should automatically create parent directories)
    nested_dest = tmp_path / "subdir" / "nested_export.json"
    result = runner.invoke(app, ["export", "source_profile", str(nested_dest)])
    assert result.exit_code == 0
    assert nested_dest.exists()

def test_profile_import_edge_cases(mock_env, tmp_path):
    runner = CliRunner()

    # File does not exist
    result = runner.invoke(app, ["import", str(tmp_path / "non_existent.json"), "--profile", "imported"])
    assert result.exit_code == 1
    assert "does not exist or is not a file" in result.stdout

    # Corrupted / invalid JSON
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{invalid")
    result = runner.invoke(app, ["import", str(bad_json), "--profile", "imported"])
    assert result.exit_code == 1
    assert "not a valid session file" in result.stdout

    # Valid JSON but schema mismatch (e.g. wrong version or format)
    invalid_schema = tmp_path / "invalid_schema.json"
    invalid_schema.write_text('{"version": 99, "timestamp": "2026", "windows": []}')
    result = runner.invoke(app, ["import", str(invalid_schema), "--profile", "imported"])
    assert result.exit_code == 1
    assert "not a valid session file" in result.stdout

    # Target profile already exists
    valid_session = tmp_path / "valid.json"
    valid_session.write_text('{"version": 2, "timestamp": "2026", "windows": []}')

    dest_path = get_session_path("existing_profile")
    dest_path.write_text('{"version": 2, "timestamp": "2026", "windows": []}')

    result = runner.invoke(app, ["import", str(valid_session), "--profile", "existing_profile"])
    assert result.exit_code == 1
    assert "already exists" in result.stdout

# ---------------------------------------------------------------------------
# 4. Stress testing and corrupt session files
# ---------------------------------------------------------------------------

def test_load_corrupted_session_raises(mock_env):
    path = get_session_path("corrupted_profile")
    path.write_text("{broken json")

    with pytest.raises(RuntimeError) as excinfo:
        load_session("corrupted_profile")
    assert "corrupted and cannot be loaded" in str(excinfo.value)

def test_list_sessions_handles_corruption_gracefully(mock_env):
    # Create one valid and one corrupted session file
    valid_path = get_session_path("valid_p")
    valid_path.write_text('{"version": 2, "timestamp": "2026-06-17T12:00:00", "windows": []}')

    corrupt_path = get_session_path("corrupt_p")
    corrupt_path.write_text("{broken")

    results = list_sessions()
    # Should be sorted by profile name: corrupt_p, valid_p
    assert len(results) == 2

    assert results[0][0] == "corrupt_p"
    assert results[0][2] is None  # Session is None due to corruption

    assert results[1][0] == "valid_p"
    assert results[1][2] is not None
    assert results[1][2].version == 2
