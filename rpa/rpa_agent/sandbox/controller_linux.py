"""
Linux/Xvfb Controller Module

This module provides mouse and keyboard control for Linux environments,
using xdotool and pyautogui for X11 automation in Docker/Xvfb.
"""

import os
import subprocess
import time
from typing import Optional, Tuple, List
import sys

# Only import Linux-specific modules when on Linux
if sys.platform == 'linux':
    try:
        import pyautogui
        # Disable pyautogui's failsafe (we're in a sandbox)
        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0.1
        HAS_PYAUTOGUI = True
    except ImportError:
        HAS_PYAUTOGUI = False
else:
    HAS_PYAUTOGUI = False


class LinuxController:
    """Mouse and keyboard controller for Linux/Xvfb environments."""

    def __init__(self, display: Optional[str] = None):
        """
        Initialize controller.

        Args:
            display: X11 display string (e.g., ':99'). If None, uses DISPLAY env var.
        """
        self.display_str = display or os.environ.get('DISPLAY', ':99')
        self._env = os.environ.copy()
        self._env['DISPLAY'] = self.display_str

    def _run_xdotool(self, args: List[str]) -> subprocess.CompletedProcess:
        """Run xdotool command with proper display."""
        return subprocess.run(
            ['xdotool'] + args,
            env=self._env,
            capture_output=True,
            text=True
        )

    # ==================== Mouse Operations ====================

    def move_to(self, x: int, y: int, duration: float = 0.0) -> None:
        """
        Move mouse to absolute position.

        Args:
            x: X coordinate.
            y: Y coordinate.
            duration: Movement duration in seconds (for smooth motion).
        """
        if HAS_PYAUTOGUI and duration > 0:
            pyautogui.moveTo(x, y, duration=duration)
        else:
            self._run_xdotool(['mousemove', str(x), str(y)])

    def move_relative(self, dx: int, dy: int, duration: float = 0.0) -> None:
        """
        Move mouse relative to current position.

        Args:
            dx: Horizontal offset.
            dy: Vertical offset.
            duration: Movement duration in seconds.
        """
        if HAS_PYAUTOGUI and duration > 0:
            pyautogui.move(dx, dy, duration=duration)
        else:
            self._run_xdotool(['mousemove_relative', str(dx), str(dy)])

    def click(
        self,
        x: Optional[int] = None,
        y: Optional[int] = None,
        button: str = 'left'
    ) -> None:
        """
        Click at position (or current position if x, y not specified).

        Args:
            x: X coordinate (optional).
            y: Y coordinate (optional).
            button: 'left', 'right', or 'middle'.
        """
        button_map = {'left': '1', 'middle': '2', 'right': '3'}
        btn = button_map.get(button, '1')

        if x is not None and y is not None:
            self._run_xdotool(['mousemove', str(x), str(y)])
            time.sleep(0.05)

        self._run_xdotool(['click', btn])

    def double_click(self, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """Double-click at position."""
        if x is not None and y is not None:
            self._run_xdotool(['mousemove', str(x), str(y)])
            time.sleep(0.05)

        self._run_xdotool(['click', '--repeat', '2', '--delay', '50', '1'])

    def right_click(self, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """Right-click at position."""
        self.click(x, y, button='right')

    def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        button: str = 'left',
        duration: float = 0.5
    ) -> None:
        """
        Drag from start to end position.

        Args:
            start_x, start_y: Starting coordinates.
            end_x, end_y: Ending coordinates.
            button: Mouse button to hold during drag.
            duration: Drag duration in seconds.
        """
        button_map = {'left': '1', 'middle': '2', 'right': '3'}
        btn = button_map.get(button, '1')

        # Move to start
        self._run_xdotool(['mousemove', str(start_x), str(start_y)])
        time.sleep(0.1)

        # Press button
        self._run_xdotool(['mousedown', btn])
        time.sleep(0.05)

        # Move to end (with optional smooth motion)
        if HAS_PYAUTOGUI and duration > 0:
            pyautogui.moveTo(end_x, end_y, duration=duration)
        else:
            self._run_xdotool(['mousemove', str(end_x), str(end_y)])

        time.sleep(0.05)

        # Release button
        self._run_xdotool(['mouseup', btn])

    def scroll(self, amount: int, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """
        Scroll at position.

        Args:
            amount: Positive = scroll up, negative = scroll down.
            x, y: Position to scroll at (optional).
        """
        if x is not None and y is not None:
            self._run_xdotool(['mousemove', str(x), str(y)])
            time.sleep(0.05)

        # xdotool: button 4 = scroll up, button 5 = scroll down
        if amount > 0:
            for _ in range(abs(amount)):
                self._run_xdotool(['click', '4'])
        else:
            for _ in range(abs(amount)):
                self._run_xdotool(['click', '5'])

    # ==================== Keyboard Operations ====================

    def type_text(self, text: str, interval: float = 0.0) -> None:
        """
        Type text string.

        Args:
            text: Text to type.
            interval: Delay between keystrokes in seconds.
        """
        if interval > 0:
            delay_ms = int(interval * 1000)
            self._run_xdotool(['type', '--delay', str(delay_ms), '--', text])
        else:
            self._run_xdotool(['type', '--', text])

    def press_key(self, key: str) -> None:
        """
        Press and release a single key.

        Args:
            key: Key name (e.g., 'Return', 'Tab', 'Escape', 'a', 'F1').
        """
        # Map common key names
        key_map = {
            'enter': 'Return',
            'esc': 'Escape',
            'backspace': 'BackSpace',
            'delete': 'Delete',
            'space': 'space',
            'tab': 'Tab',
            'up': 'Up',
            'down': 'Down',
            'left': 'Left',
            'right': 'Right',
            'home': 'Home',
            'end': 'End',
            'pageup': 'Page_Up',
            'pagedown': 'Page_Down',
        }
        key = key_map.get(key.lower(), key)
        self._run_xdotool(['key', key])

    def hotkey(self, *keys: str) -> None:
        """
        Press a key combination.

        Args:
            keys: Keys to press together (e.g., 'ctrl', 'c').
        """
        # Map modifier names
        mod_map = {
            'ctrl': 'ctrl',
            'control': 'ctrl',
            'alt': 'alt',
            'shift': 'shift',
            'super': 'super',
            'win': 'super',
            'meta': 'super',
        }

        # Build xdotool key string (e.g., 'ctrl+shift+t')
        mapped_keys = []
        for k in keys:
            mapped = mod_map.get(k.lower(), k)
            mapped_keys.append(mapped)

        key_combo = '+'.join(mapped_keys)
        self._run_xdotool(['key', key_combo])

    def key_down(self, key: str) -> None:
        """Press key without releasing."""
        self._run_xdotool(['keydown', key])

    def key_up(self, key: str) -> None:
        """Release key."""
        self._run_xdotool(['keyup', key])

    # ==================== Window Operations ====================

    def get_active_window(self) -> Optional[str]:
        """Get active window ID."""
        result = self._run_xdotool(['getactivewindow'])
        if result.returncode == 0:
            return result.stdout.strip()
        return None

    def focus_window(self, title: str) -> bool:
        """
        Focus window by title.

        Args:
            title: Window title (partial match).

        Returns:
            True if window was found and focused.
        """
        result = self._run_xdotool(['search', '--name', title, 'windowactivate'])
        return result.returncode == 0

    def get_window_geometry(self, window_id: Optional[str] = None) -> Optional[Tuple[int, int, int, int]]:
        """
        Get window geometry.

        Args:
            window_id: Window ID (or active window if None).

        Returns:
            (x, y, width, height) or None if failed.
        """
        if window_id is None:
            window_id = self.get_active_window()
            if window_id is None:
                return None

        result = self._run_xdotool(['getwindowgeometry', '--shell', window_id])
        if result.returncode != 0:
            return None

        # Parse output like "X=123\nY=456\nWIDTH=800\nHEIGHT=600\n"
        geometry = {}
        for line in result.stdout.strip().split('\n'):
            if '=' in line:
                key, value = line.split('=', 1)
                geometry[key] = int(value)

        return (
            geometry.get('X', 0),
            geometry.get('Y', 0),
            geometry.get('WIDTH', 0),
            geometry.get('HEIGHT', 0)
        )

    # ==================== Utility ====================

    def wait(self, seconds: float) -> None:
        """Wait for specified duration."""
        time.sleep(seconds)

    def get_cursor_position(self) -> Tuple[int, int]:
        """Get current mouse position."""
        result = self._run_xdotool(['getmouselocation', '--shell'])
        if result.returncode != 0:
            return (0, 0)

        coords = {}
        for line in result.stdout.strip().split('\n'):
            if '=' in line:
                key, value = line.split('=', 1)
                coords[key] = int(value)

        return (coords.get('X', 0), coords.get('Y', 0))


# Singleton instance
_controller: Optional[LinuxController] = None


def get_controller() -> LinuxController:
    """Get or create controller singleton."""
    global _controller
    if _controller is None:
        _controller = LinuxController()
    return _controller
