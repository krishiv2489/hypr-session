import os
from unittest.mock import patch

from hypr_session.cli import install_hooks


def test_install_hooks_success(tmp_path):
    # Setup test directories and files
    xdg_config = tmp_path / "config"
    xdg_config.mkdir()
    hypr_dir = xdg_config / "hypr"
    hypr_dir.mkdir()

    hypr_conf = hypr_dir / "hyprland.conf"
    content = "# Some configuration\nbind = $mainMod, M, exit # Exit Hyprland\n# another config line\n"
    hypr_conf.write_text(content)

    env_mock = {"XDG_CONFIG_HOME": str(xdg_config)}
    argv_mock = ["/usr/local/bin/hypr-session", "install-hooks"]

    with patch.dict(os.environ, env_mock), \
         patch("sys.argv", argv_mock), \
         patch("shutil.which", return_value="/usr/local/bin/hypr-session"):
        install_hooks()

    backup = hypr_conf.with_suffix(".conf.bak")
    assert backup.exists()
    assert backup.read_text() == content

    modified_content = hypr_conf.read_text()
    assert "# [Auto-commented by hypr-session]" in modified_content
    assert "# bind = $mainMod, M, exit # Exit Hyprland" in modified_content
    assert "bind = $mainMod, M, exec, /usr/local/bin/hypr-session save ; hyprctl dispatch exit" in modified_content
    assert "exec-once = /usr/local/bin/hypr-session restore --wait" in modified_content

def test_install_hooks_backup_exists_not_overwritten(tmp_path):
    xdg_config = tmp_path / "config"
    xdg_config.mkdir()
    hypr_dir = xdg_config / "hypr"
    hypr_dir.mkdir()

    hypr_conf = hypr_dir / "hyprland.conf"
    hypr_conf.write_text("bind = $mainMod, M, exit")

    backup = hypr_conf.with_suffix(".conf.bak")
    original_backup_content = "ORIGINAL BACKUP CONTENT"
    backup.write_text(original_backup_content)

    env_mock = {"XDG_CONFIG_HOME": str(xdg_config)}

    with patch.dict(os.environ, env_mock), \
         patch("shutil.which", return_value="/usr/local/bin/hypr-session"):
        install_hooks()

    assert backup.read_text() == original_backup_content
