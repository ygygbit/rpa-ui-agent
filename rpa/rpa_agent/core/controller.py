"""
UI Controller module for mouse and keyboard automation.

Uses pyautogui for cross-platform support with additional
safety features and precise coordinate handling.
"""

import time
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple

import pyautogui


class MouseButton(str, Enum):
    """Mouse button types."""
    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"


@dataclass
class Point:
    """Screen coordinate point."""
    x: int
    y: int

    def to_tuple(self) -> Tuple[int, int]:
        return (self.x, self.y)


class UIController:
    """
    UI Controller for mouse and keyboard automation.

    Features:
    - Safe movement with boundaries
    - Human-like delays
    - Click verification
    - Keyboard input with modifiers
    """

    # Safety boundaries (prevent clicking outside screen)
    SAFE_MARGIN = 5

    def __init__(
        self,
        fail_safe: bool = True,
        pause: float = 0.1,
        move_duration: float = 0.2
    ):
        """
        Initialize UI controller.

        Args:
            fail_safe: Enable pyautogui failsafe (move to corner to abort)
            pause: Default pause between actions
            move_duration: Duration for mouse movements
        """
        pyautogui.FAILSAFE = fail_safe
        pyautogui.PAUSE = pause
        self.move_duration = move_duration
        self._screen_size = pyautogui.size()

    @property
    def screen_size(self) -> Tuple[int, int]:
        """Get screen size."""
        return self._screen_size

    @property
    def mouse_position(self) -> Point:
        """Get current mouse position."""
        pos = pyautogui.position()
        return Point(pos[0], pos[1])

    def _clamp_coordinates(self, x: int, y: int) -> Tuple[int, int]:
        """Clamp coordinates to safe screen boundaries."""
        max_x = self._screen_size[0] - self.SAFE_MARGIN
        max_y = self._screen_size[1] - self.SAFE_MARGIN
        return (
            max(self.SAFE_MARGIN, min(x, max_x)),
            max(self.SAFE_MARGIN, min(y, max_y))
        )

    def move_to(self, x: int, y: int, duration: Optional[float] = None) -> Point:
        """
        Move mouse to coordinates.

        Args:
            x: X coordinate
            y: Y coordinate
            duration: Movement duration (uses default if None)

        Returns:
            Final mouse position
        """
        x, y = self._clamp_coordinates(x, y)
        dur = duration if duration is not None else self.move_duration
        pyautogui.moveTo(x, y, duration=dur)
        return Point(x, y)

    def click(
        self,
        x: Optional[int] = None,
        y: Optional[int] = None,
        button: MouseButton = MouseButton.LEFT,
        clicks: int = 1,
        interval: float = 0.1
    ) -> Point:
        """
        Click at coordinates or current position.

        Args:
            x: X coordinate (None = current position)
            y: Y coordinate (None = current position)
            button: Mouse button to click
            clicks: Number of clicks
            interval: Interval between clicks

        Returns:
            Click position
        """
        if x is not None and y is not None:
            x, y = self._clamp_coordinates(x, y)
            pyautogui.click(x, y, clicks=clicks, interval=interval, button=button.value)
            return Point(x, y)
        else:
            pos = pyautogui.position()
            pyautogui.click(clicks=clicks, interval=interval, button=button.value)
            return Point(pos[0], pos[1])

    def double_click(self, x: Optional[int] = None, y: Optional[int] = None) -> Point:
        """Double-click at coordinates."""
        return self.click(x, y, clicks=2)

    def right_click(self, x: Optional[int] = None, y: Optional[int] = None) -> Point:
        """Right-click at coordinates."""
        return self.click(x, y, button=MouseButton.RIGHT)

    def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.5,
        button: MouseButton = MouseButton.LEFT
    ) -> None:
        """
        Drag from start to end coordinates.

        Args:
            start_x, start_y: Starting coordinates
            end_x, end_y: Ending coordinates
            duration: Drag duration
            button: Mouse button to use
        """
        start_x, start_y = self._clamp_coordinates(start_x, start_y)
        end_x, end_y = self._clamp_coordinates(end_x, end_y)

        self.move_to(start_x, start_y)
        pyautogui.drag(
            end_x - start_x,
            end_y - start_y,
            duration=duration,
            button=button.value
        )

    def scroll(
        self,
        clicks: int,
        x: Optional[int] = None,
        y: Optional[int] = None
    ) -> None:
        """
        Scroll at position.

        Args:
            clicks: Number of scroll clicks (positive = up, negative = down)
            x, y: Position to scroll at (None = current position)
        """
        if x is not None and y is not None:
            x, y = self._clamp_coordinates(x, y)
            pyautogui.scroll(clicks, x, y)
        else:
            pyautogui.scroll(clicks)

    def type_text(
        self,
        text: str,
        interval: float = 0.02,
        press_enter: bool = False
    ) -> None:
        """
        Type text with optional enter press.

        Args:
            text: Text to type
            interval: Interval between keystrokes
            press_enter: Press enter after typing
        """
        pyautogui.typewrite(text, interval=interval)
        if press_enter:
            time.sleep(0.05)
            pyautogui.press("enter")

    def write(self, text: str, interval: float = 0.0) -> None:
        """
        Write text (supports unicode, unlike typewrite).

        Args:
            text: Text to write
            interval: Interval between characters
        """
        pyautogui.write(text, interval=interval)

    def press_key(self, key: str, presses: int = 1, interval: float = 0.1) -> None:
        """
        Press a keyboard key.

        Args:
            key: Key name (e.g., 'enter', 'tab', 'escape', 'f1')
            presses: Number of key presses
            interval: Interval between presses
        """
        pyautogui.press(key, presses=presses, interval=interval)

    def hotkey(self, *keys: str) -> None:
        """
        Press a hotkey combination.

        Args:
            keys: Keys to press together (e.g., 'ctrl', 'c')
        """
        pyautogui.hotkey(*keys)

    def hold_key(self, key: str) -> None:
        """Hold down a key."""
        pyautogui.keyDown(key)

    def release_key(self, key: str) -> None:
        """Release a held key."""
        pyautogui.keyUp(key)

    def key_combo(self, keys: List[str]) -> None:
        """
        Execute a key combination.

        Args:
            keys: List of keys (modifiers first)
        """
        if len(keys) == 0:
            return

        # Press modifiers
        for key in keys[:-1]:
            pyautogui.keyDown(key)

        # Press main key
        pyautogui.press(keys[-1])

        # Release modifiers
        for key in reversed(keys[:-1]):
            pyautogui.keyUp(key)

    def wait(self, seconds: float) -> None:
        """Wait for specified seconds."""
        time.sleep(seconds)
