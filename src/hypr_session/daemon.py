import logging
import os
import signal
import socket
import sys
import threading
import time
import typing
from typing import Optional

from .session import save_session
from .config import PERMANENT_PAUSE_LOCK, RUNTIME_PAUSE_LOCK

logger = logging.getLogger(__name__)

class HyprlandDaemon:
    def __init__(self, profile: Optional[str] = None, debounce_seconds: float = 30.0):
        self.profile = profile
        self.debounce_seconds = debounce_seconds
        self.running = False
        self.save_timer: Optional[threading.Timer] = None
        self.save_lock = threading.Lock()
        
        # Events that should trigger a save
        self.trigger_events = {
            b"openwindow",
            b"closewindow",
            b"movewindow",
            b"changefloatingmode"
        }

    def _do_save(self) -> None:
        if PERMANENT_PAUSE_LOCK.exists() or RUNTIME_PAUSE_LOCK.exists():
            logger.info("Auto-save is paused. Skipping save.")
            return
        with self.save_lock:
            try:
                logger.info(f"Triggering auto-save for profile: {self.profile or 'default'}")
                save_session(self.profile, force_empty=True)
                logger.info("Auto-save completed successfully.")
            except Exception as e:
                logger.error(f"Auto-save failed: {e}")

    def _schedule_save(self) -> None:
        if self.save_timer is not None:
            self.save_timer.cancel()
        
        self.save_timer = threading.Timer(self.debounce_seconds, self._do_save)
        self.save_timer.start()
        logger.debug(f"Save scheduled in {self.debounce_seconds} seconds.")

    def _get_socket_path(self) -> str:
        signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
        if not signature:
            raise RuntimeError("HYPRLAND_INSTANCE_SIGNATURE is not set.")
        
        xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
        if xdg_runtime:
            base = xdg_runtime
        else:
            base = f"/run/user/{os.getuid()}"
        return f"{base}/hypr/{signature}/.socket2.sock"

    def handle_signal(self, signum: int, frame: 'typing.Any') -> None:
        logger.info(f"Received signal {signum}, performing final save and exiting...")
        self.running = False
        if self.save_timer is not None:
            self.save_timer.cancel()
        if self.save_lock.acquire(blocking=False):
            try:
                try:
                    save_session(self.profile, force_empty=True)
                except Exception as e:
                    logger.error(f"Final save failed: {e}")
            finally:
                self.save_lock.release()
        else:
            logger.warning("Save lock held during shutdown — skipping final save (in-progress save will complete).")
        sys.exit(0)

    def run(self) -> None:
        self.running = True
        
        signal.signal(signal.SIGINT, self.handle_signal)
        signal.signal(signal.SIGTERM, self.handle_signal)

        retries = 3
        while self.running and retries > 0:
            try:
                sock_path = self._get_socket_path()
                logger.info(f"Connecting to Hyprland socket: {sock_path}")
                
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.connect(sock_path)
                    logger.info("Connected to Hyprland IPC socket.")
                    retries = 3  # Reset retries on successful connection
                    
                    # File wrapper around socket to read line by line
                    with sock.makefile('rb') as f:
                        while self.running:
                            line = f.readline()
                            if not line:
                                logger.warning("Socket disconnected.")
                                break
                            
                            parts = line.split(b">>", 1)
                            if parts:
                                event = parts[0]
                                if event in self.trigger_events:
                                    logger.debug(f"Received trigger event: {event.decode('utf-8')}")
                                    self._schedule_save()
                                    
            except Exception as e:
                logger.error(f"Socket connection error: {e}")
            
            if self.running:
                retries -= 1
                if retries > 0:
                    logger.info(f"Retrying connection in 5 seconds... ({retries} retries left)")
                    time.sleep(5)
                else:
                    logger.error("Maximum retries reached. Exiting.")
                    break
        
        # Clean up timer if exiting loop naturally
        if self.save_timer is not None:
            self.save_timer.cancel()


def run_daemon(profile: Optional[str] = None, debounce_seconds: float = 30.0) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    daemon = HyprlandDaemon(profile=profile, debounce_seconds=debounce_seconds)
    daemon.run()
