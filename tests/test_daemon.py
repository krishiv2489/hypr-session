import os
import signal
import socket
from unittest.mock import MagicMock, patch

import pytest

from hypr_session.daemon import HyprlandDaemon, run_daemon


@patch("hypr_session.daemon.save_session")
def test_debounce_timer_resets(mock_save_session):
    daemon = HyprlandDaemon(debounce_seconds=0.1)
    
    # First event
    daemon._schedule_save()
    assert daemon.save_timer is not None
    timer1 = daemon.save_timer
    
    # Second event before timer1 expires
    daemon._schedule_save()
    assert daemon.save_timer is not timer1
    
    # Let timer expire
    daemon.save_timer.join()
    
    # It should only save once, even though we scheduled it twice
    mock_save_session.assert_called_once()


@patch("hypr_session.daemon.save_session")
@patch("sys.exit")
def test_sigterm_triggers_final_save(mock_exit, mock_save_session):
    daemon = HyprlandDaemon(debounce_seconds=1.0)
    daemon.running = True
    
    # Schedule save
    daemon._schedule_save()
    
    # Handle signal
    daemon.handle_signal(signal.SIGTERM, None)
    
    assert daemon.running is False
    mock_exit.assert_called_once_with(0)
    # The scheduled save was cancelled, and a final save was executed
    mock_save_session.assert_called_once_with(None, force_empty=True)


@patch("hypr_session.daemon.os.environ.get")
@patch("hypr_session.daemon.os.getuid")
@patch("hypr_session.daemon.socket.socket")
@patch("hypr_session.daemon.HyprlandDaemon._schedule_save")
def test_mock_socket_connection(mock_schedule, mock_socket_class, mock_getuid, mock_environ_get):
    mock_environ_get.side_effect = lambda k, d=None: "mock_sig" if k == "HYPRLAND_INSTANCE_SIGNATURE" else d
    mock_getuid.return_value = 1000
    
    mock_socket = MagicMock()
    mock_socket_class.return_value.__enter__.return_value = mock_socket
    
    mock_file = MagicMock()
    daemon = HyprlandDaemon()
    
    # Custom side effect to exit loop on EOF
    def mock_readline():
        nonlocal count
        if count == 0:
            count += 1
            return b"openwindow>>0x123\n"
        elif count == 1:
            count += 1
            return b"invalid>>abc\n"
        else:
            daemon.running = False
            return b""
            
    count = 0
    mock_file.readline.side_effect = mock_readline
    mock_socket.makefile.return_value.__enter__.return_value = mock_file
    
    with patch("hypr_session.daemon.time.sleep"):
        daemon.run()
    
    assert mock_socket.connect.called
    assert mock_socket.connect.call_args[0][0] == "/run/user/1000/hypr/mock_sig/.socket2.sock"
    
    # openwindow should trigger save
    mock_schedule.assert_called_once()


@patch("hypr_session.daemon.os.environ.get")
@patch("hypr_session.daemon.os.getuid")
@patch("hypr_session.daemon.socket.socket")
@patch("hypr_session.daemon.time.sleep")
def test_retry_logic(mock_sleep, mock_socket_class, mock_getuid, mock_environ_get):
    mock_environ_get.side_effect = lambda k, d=None: "mock_sig" if k == "HYPRLAND_INSTANCE_SIGNATURE" else d
    mock_getuid.return_value = 1000
    
    # socket connection fails
    mock_socket_class.side_effect = Exception("Connection failed")
    
    daemon = HyprlandDaemon()
    daemon.run()
    
    # Should have retried 3 times
    assert mock_socket_class.call_count == 3
    assert mock_sleep.call_count == 2
