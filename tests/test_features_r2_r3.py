import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hypr_session.models import Session, WindowEntry


@pytest.fixture
def mock_dirs(tmp_path, monkeypatch):
    temp_data_dir = tmp_path / "data"
    temp_config_dir = tmp_path / "config"
    temp_data_dir.mkdir()
    temp_config_dir.mkdir()

    # Patch env variables
    monkeypatch.setenv("XDG_DATA_HOME", str(temp_data_dir))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(temp_config_dir))
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "mock_signature")

    # Patch constants in modules
    import hypr_session.cli
    import hypr_session.config
    import hypr_session.restore
    import hypr_session.session

    monkeypatch.setattr(hypr_session.config, "DATA_DIR", temp_data_dir)
    monkeypatch.setattr(hypr_session.config, "CONFIG_DIR", temp_config_dir)
    monkeypatch.setattr(hypr_session.config, "CONFIG_FILE", temp_config_dir / "config.toml")
    monkeypatch.setattr(hypr_session.config, "BACKUPS_DIR", temp_data_dir / "backups")
    monkeypatch.setattr(hypr_session.config, "PERMANENT_PAUSE_LOCK", temp_config_dir / "disabled")

    monkeypatch.setattr(hypr_session.cli, "DATA_DIR", temp_data_dir)
    monkeypatch.setattr(hypr_session.cli, "CONFIG_FILE", temp_config_dir / "config.toml")
    monkeypatch.setattr(hypr_session.cli, "PERMANENT_PAUSE_LOCK", temp_config_dir / "disabled")

    monkeypatch.setattr(hypr_session.session, "DATA_DIR", temp_data_dir)
    monkeypatch.setattr(hypr_session.session, "BACKUPS_DIR", temp_data_dir / "backups")

    return temp_data_dir, temp_config_dir

def test_diff_counter_based(mock_dirs, monkeypatch):
    from hypr_session.cli import app

    saved_windows = [
        WindowEntry(address="0x1", initial_class="kitty", cmd="kitty", workspace_id=1, monitor=0, floating=False, at=(0,0), size=(0,0), fullscreen=0, pinned=False, focus_history_id=1),
        WindowEntry(address="0x2", initial_class="kitty", cmd="kitty", workspace_id=1, monitor=0, floating=False, at=(0,0), size=(0,0), fullscreen=0, pinned=False, focus_history_id=2),
        WindowEntry(address="0x3", initial_class="firefox", cmd="firefox", workspace_id=2, monitor=0, floating=False, at=(0,0), size=(0,0), fullscreen=0, pinned=False, focus_history_id=3),
    ]
    current_windows = [
        WindowEntry(address="0x4", initial_class="kitty", cmd="kitty", workspace_id=1, monitor=0, floating=False, at=(0,0), size=(0,0), fullscreen=0, pinned=False, focus_history_id=1),
        WindowEntry(address="0x5", initial_class="firefox", cmd="firefox", workspace_id=2, monitor=0, floating=False, at=(0,0), size=(0,0), fullscreen=0, pinned=False, focus_history_id=2),
        WindowEntry(address="0x6", initial_class="firefox", cmd="firefox", workspace_id=2, monitor=0, floating=False, at=(0,0), size=(0,0), fullscreen=0, pinned=False, focus_history_id=3),
    ]

    monkeypatch.setattr("hypr_session.cli.load_session", lambda profile: Session(windows=saved_windows))
    monkeypatch.setattr("hypr_session.cli.get_current_session_windows", lambda: current_windows)
    monkeypatch.setattr("hypr_session.cli.is_hyprland_running", lambda: True)

    runner = CliRunner()
    result = runner.invoke(app, ["diff"])

    assert result.exit_code == 0
    assert "Session Comparison: Saved vs Active" in result.stdout
    assert "missing" in result.stdout
    assert "new" in result.stdout
    assert "kitty" in result.stdout
    assert "firefox" in result.stdout

def test_diff_geometry_warning(mock_dirs, monkeypatch):
    from hypr_session.cli import app

    saved_windows = [
        WindowEntry(address="0x1", initial_class="kitty", cmd="kitty", workspace_id=1, monitor=0, floating=True, at=(10,10), size=(100,100), fullscreen=0, pinned=False, focus_history_id=1),
    ]
    current_windows = [
        WindowEntry(address="0x2", initial_class="kitty", cmd="kitty", workspace_id=1, monitor=0, floating=True, at=(20,20), size=(200,200), fullscreen=0, pinned=False, focus_history_id=1),
    ]

    monkeypatch.setattr("hypr_session.cli.load_session", lambda profile: Session(windows=saved_windows))
    monkeypatch.setattr("hypr_session.cli.get_current_session_windows", lambda: current_windows)
    monkeypatch.setattr("hypr_session.cli.is_hyprland_running", lambda: True)

    runner = CliRunner()
    result = runner.invoke(app, ["diff"])

    assert result.exit_code == 0
    assert "Δ geom" in result.stdout
    assert "Warning: Some floating window geometries differ" in result.stdout

def test_profile_management_commands(mock_dirs, monkeypatch):
    from hypr_session.cli import app
    from hypr_session.session import get_session_path

    data_dir, config_dir = mock_dirs

    # Create dummy session file
    session_data = Session(windows=[
        WindowEntry(address="0x1", initial_class="kitty", cmd="kitty", workspace_id=1, monitor=0, floating=False, at=(0,0), size=(0,0), fullscreen=0, pinned=False, focus_history_id=1)
    ])

    default_path = get_session_path(None)
    default_path.write_text(json.dumps(session_data.to_dict()))

    runner = CliRunner()

    # Test copy command: default -> backup_profile
    result = runner.invoke(app, ["copy", "default", "backup_profile"])
    assert result.exit_code == 0
    assert "successfully copied" in result.stdout
    backup_path = get_session_path("backup_profile")
    assert backup_path.exists()

    # Test copy conflict: copy to existing should fail
    result = runner.invoke(app, ["copy", "default", "backup_profile"])
    assert result.exit_code == 1
    assert "already exists" in result.stdout

    # Test rename command: backup_profile -> renamed_profile
    result = runner.invoke(app, ["rename", "backup_profile", "renamed_profile"])
    assert result.exit_code == 0
    assert "successfully renamed" in result.stdout
    assert not backup_path.exists()
    renamed_path = get_session_path("renamed_profile")
    assert renamed_path.exists()

    # Test export command: renamed_profile -> export_file.json
    export_file = data_dir / "exported_session.json"
    result = runner.invoke(app, ["export", "renamed_profile", str(export_file)])
    assert result.exit_code == 0
    assert "successfully exported" in result.stdout
    assert export_file.exists()

    # Test export conflict: export to existing file should fail
    result = runner.invoke(app, ["export", "renamed_profile", str(export_file)])
    assert result.exit_code == 1
    assert "already exists" in result.stdout

    # Test import command: export_file.json -> imported_profile
    result = runner.invoke(app, ["import", str(export_file), "--profile", "imported_profile"])
    assert result.exit_code == 0
    assert "Successfully imported" in result.stdout
    imported_path = get_session_path("imported_profile")
    assert imported_path.exists()

    # Test import with invalid JSON
    bad_file = data_dir / "bad_session.json"
    bad_file.write_text("{invalid json")
    result = runner.invoke(app, ["import", str(bad_file), "--profile", "another_profile"])
    assert result.exit_code == 1
    assert "not a valid session file" in result.stdout

def test_save_only_active_flag(mock_dirs, monkeypatch):
    from hypr_session.cli import app
    from hypr_session.session import load_session

    def mock_run_hyprctl(command):
        if command == "activeworkspace":
            return {"id": 1}
        elif command == "clients":
            return [
                {
                    "address": "0x1",
                    "initialClass": "kitty",
                    "class": "kitty",
                    "workspace": {"id": 1},
                    "monitor": 0,
                    "floating": False,
                    "at": [0, 0],
                    "size": [800, 600],
                    "fullscreen": 0,
                    "pinned": False,
                    "focusHistoryID": 1
                },
                {
                    "address": "0x2",
                    "initialClass": "firefox",
                    "class": "firefox",
                    "workspace": {"id": 2},
                    "monitor": 0,
                    "floating": False,
                    "at": [0, 0],
                    "size": [800, 600],
                    "fullscreen": 0,
                    "pinned": False,
                    "focusHistoryID": 2
                }
            ]
        return {}

    monkeypatch.setattr("hypr_session.session.run_hyprctl", mock_run_hyprctl)
    monkeypatch.setattr("hypr_session.cli.is_hyprland_running", lambda: True)

    runner = CliRunner()
    result = runner.invoke(app, ["save", "--profile", "only_active_profile", "--only-active"])
    assert result.exit_code == 0

    saved_session = load_session("only_active_profile")
    assert saved_session is not None
    assert len(saved_session.windows) == 1
    assert saved_session.windows[0].initial_class == "kitty"
    assert saved_session.windows[0].workspace_id == 1

def test_restore_filter_flags(mock_dirs, monkeypatch):
    from hypr_session.cli import app

    session_data = Session(windows=[
        WindowEntry(address="0x1", initial_class="kitty", cmd="kitty", workspace_id=1, monitor=0, floating=False, at=(0,0), size=(0,0), fullscreen=0, pinned=False, focus_history_id=1),
        WindowEntry(address="0x2", initial_class="firefox", cmd="firefox", workspace_id=2, monitor=0, floating=False, at=(0,0), size=(0,0), fullscreen=0, pinned=False, focus_history_id=2),
    ])

    monkeypatch.setattr("hypr_session.cli.load_session", lambda profile: session_data)
    monkeypatch.setattr("hypr_session.restore.load_session", lambda profile: session_data)
    monkeypatch.setattr("hypr_session.cli.is_hyprland_running", lambda: True)
    monkeypatch.setattr("hypr_session.restore.shutil.which", lambda x: "/usr/bin/" + x)

    runner = CliRunner()

    # Test 1: Restore only workspace 1
    result = runner.invoke(app, ["restore", "--dry-run", "--workspace", "1"])
    assert result.exit_code == 0
    assert "kitty → ws:1" in result.stdout
    assert "firefox" not in result.stdout

    # Test 2: Exclude class kitty
    result = runner.invoke(app, ["restore", "--dry-run", "--exclude", "kitty"])
    assert result.exit_code == 0
    assert "firefox → ws:2" in result.stdout
    assert "kitty" not in result.stdout

def test_status_dashboard_tree(mock_dirs, monkeypatch):
    from hypr_session.cli import app

    session_data = Session(windows=[
        WindowEntry(address="0x1", initial_class="kitty", cmd="kitty", workspace_id=1, monitor=0, floating=False, at=(0,0), size=(0,0), fullscreen=0, pinned=False, focus_history_id=1, cwd="/tmp"),
    ])

    monkeypatch.setattr("hypr_session.cli.list_sessions", lambda: [("default", Path("session.json"), session_data)])

    runner = CliRunner()
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "Profile: default" in result.stdout
    assert "Monitor 0" in result.stdout
    assert "Workspace 1" in result.stdout
    assert "kitty" in result.stdout
    assert "cwd: /tmp" in result.stdout
