"""
Global hotkey handler for stopping the RPA agent.
Uses Windows API to detect Ctrl+Alt hotkey without blocking.
"""

import ctypes
import threading
import time
from ctypes import wintypes
from typing import Callable, Optional

# Windows API
user32 = ctypes.windll.user32

# Virtual key codes
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt key
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5


def is_key_pressed(vk_code: int) -> bool:
    """Check if a key is currently pressed."""
    return (user32.GetAsyncKeyState(vk_code) & 0x8000) != 0


class HotkeyMonitor:
    """
    Monitors for global hotkey combinations.
    Default: Ctrl+Alt to stop the agent.
    """

    def __init__(
        self,
        callback: Callable[[], None],
        check_interval: float = 0.05  # 50ms
    ):
        """
        Initialize hotkey monitor.

        Args:
            callback: Function to call when hotkey is detected
            check_interval: How often to check for hotkey (seconds)
        """
        self.callback = callback
        self.check_interval = check_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._triggered = False

    def _check_hotkey(self) -> bool:
        """Check if Ctrl+Alt is pressed."""
        ctrl_pressed = is_key_pressed(VK_CONTROL) or is_key_pressed(VK_LCONTROL) or is_key_pressed(VK_RCONTROL)
        alt_pressed = is_key_pressed(VK_MENU) or is_key_pressed(VK_LMENU) or is_key_pressed(VK_RMENU)
        return ctrl_pressed and alt_pressed

    def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            if self._check_hotkey() and not self._triggered:
                self._triggered = True
                self.callback()
                # Don't trigger again until keys are released
            elif not self._check_hotkey():
                self._triggered = False

            time.sleep(self.check_interval)

    def start(self) -> None:
        """Start monitoring for hotkey."""
        if self._running:
            return

        self._running = True
        self._triggered = False
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop monitoring."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


# Global monitor instance
_monitor: Optional[HotkeyMonitor] = None


def start_hotkey_monitor(callback: Callable[[], None]) -> HotkeyMonitor:
    """Start the global hotkey monitor."""
    global _monitor
    if _monitor:
        _monitor.stop()
    _monitor = HotkeyMonitor(callback)
    _monitor.start()
    return _monitor


def stop_hotkey_monitor() -> None:
    """Stop the global hotkey monitor."""
    global _monitor
    if _monitor:
        _monitor.stop()
        _monitor = None
