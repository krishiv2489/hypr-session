import importlib
import os
from pathlib import Path
from unittest.mock import patch

import hypr_session.config


def test_xdg_runtime_dir_resolution(tmp_path):
    custom_runtime = tmp_path / "runtime"
    custom_runtime.mkdir()

    with patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(custom_runtime)}):
        importlib.reload(hypr_session.config)
        assert hypr_session.config.RUNTIME_PAUSE_LOCK == custom_runtime / "hypr-session.paused"

def test_secure_tmp_fallback():
    # Use a high UID to guarantee /run/user/<uid> does not exist
    unique_uid = 199999
    tmp_dir = Path(f"/tmp/hypr-session-{unique_uid}")

    if tmp_dir.exists():
        try:
            tmp_dir.rmdir()
        except OSError:
            pass

    with patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/nonexistent_dir_12345"}), \
         patch("os.getuid", return_value=unique_uid):

        importlib.reload(hypr_session.config)
        assert hypr_session.config.RUNTIME_PAUSE_LOCK == tmp_dir / "hypr-session.paused"
        assert tmp_dir.exists()
        stat = tmp_dir.stat()
        assert (stat.st_mode & 0o777) == 0o700

        # Cleanup
        try:
            tmp_dir.rmdir()
        except OSError:
            pass

def test_load_config_warning(tmp_path, capsys):
    config_file = tmp_path / "config.toml"
    config_file.write_text("invalid = = toml")

    with patch("hypr_session.config.CONFIG_FILE", config_file):
        from hypr_session.config import load_config
        load_config()

    captured = capsys.readouterr()
    assert "Warning: Failed to load configuration" in captured.err
