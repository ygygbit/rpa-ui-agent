"""
UI Controller module for mouse and keyboard automation.

Uses Windows native SendInput API for hardware-level input simulation
that mimics physical mouse and keyboard interactions.
"""

import ctypes
import time
import random
from ctypes import wintypes
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple


# Windows API constants
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

# Mouse event flags
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_ABSOLUTE = 0x8000

# Keyboard event flags
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

# Virtual key codes
VK_CODES = {
    'backspace': 0x08, 'tab': 0x09, 'enter': 0x0D, 'return': 0x0D,
    'shift': 0x10, 'ctrl': 0x11, 'control': 0x11, 'alt': 0x12, 'menu': 0x12,
    'pause': 0x13, 'capslock': 0x14, 'escape': 0x1B, 'esc': 0x1B,
    'space': 0x20, 'pageup': 0x21, 'pagedown': 0x22,
    'end': 0x23, 'home': 0x24,
    'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28,
    'printscreen': 0x2C, 'insert': 0x2D, 'delete': 0x2E, 'del': 0x2E,
    'win': 0x5B, 'winleft': 0x5B, 'winright': 0x5C, 'windows': 0x5B,
    'apps': 0x5D,
    'sleep': 0x5F,
    'numpad0': 0x60, 'numpad1': 0x61, 'numpad2': 0x62, 'numpad3': 0x63,
    'numpad4': 0x64, 'numpad5': 0x65, 'numpad6': 0x66, 'numpad7': 0x67,
    'numpad8': 0x68, 'numpad9': 0x69,
    'multiply': 0x6A, 'add': 0x6B, 'separator': 0x6C,
    'subtract': 0x6D, 'decimal': 0x6E, 'divide': 0x6F,
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73,
    'f5': 0x74, 'f6': 0x75, 'f7': 0x76, 'f8': 0x77,
    'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
    'numlock': 0x90, 'scrolllock': 0x91,
    'lshift': 0xA0, 'rshift': 0xA1,
    'lctrl': 0xA2, 'lcontrol': 0xA2, 'rctrl': 0xA3, 'rcontrol': 0xA3,
    'lalt': 0xA4, 'lmenu': 0xA4, 'ralt': 0xA5, 'rmenu': 0xA5,
    'volumemute': 0xAD, 'volumedown': 0xAE, 'volumeup': 0xAF,
    'nexttrack': 0xB0, 'prevtrack': 0xB1, 'stop': 0xB2, 'playpause': 0xB3,
}


# Windows structures for SendInput
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", INPUT_UNION),
    ]


# Load Windows APIs
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Get screen metrics
SM_CXSCREEN = 0
SM_CYSCREEN = 1


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


class BlockedKeyError(Exception):
    """Raised when attempting to use a blocked key."""
    pass


class UIController:
    """
    UI Controller for mouse and keyboard automation.

    Uses Windows native SendInput API for hardware-level input simulation
    that mimics physical mouse and keyboard interactions as closely as possible.
    """

    # Safety boundaries (prevent clicking outside screen)
    SAFE_MARGIN = 5

    # Blocked keys - these keys are disabled for safety
    BLOCKED_KEYS = frozenset({
        # Windows/system keys
        "win", "winleft", "winright", "windows",
        # Function keys that can cause system actions
        "printscreen", "prtsc", "prtscr",
        "scrolllock", "pause", "numlock",
        # Alt+Tab, Alt+F4 type combinations are blocked via modifiers
        "apps",  # Application/context menu key
        # Power/sleep keys
        "sleep", "power", "wake",
        # Media keys that could disrupt workflow
        "volumemute", "volumedown", "volumeup",
        "playpause", "stop", "nexttrack", "prevtrack",
        # Browser keys
        "browserback", "browserforward", "browserrefresh",
        "browserstop", "browsersearch", "browserfavorites", "browserhome",
        # Launch keys
        "launchmail", "launchmediaselect", "launchapp1", "launchapp2",
    })

    def __init__(
        self,
        fail_safe: bool = True,
        pause: float = 0.05,
        move_duration: float = 0.2,
        human_like: bool = True
    ):
        """
        Initialize UI controller.

        Args:
            fail_safe: Reserved for compatibility (not used with native API)
            pause: Default pause between actions
            move_duration: Duration for mouse movements
            human_like: Add small random delays to mimic human behavior
        """
        self.pause = pause
        self.move_duration = move_duration
        self.human_like = human_like
        self._screen_width = user32.GetSystemMetrics(SM_CXSCREEN)
        self._screen_height = user32.GetSystemMetrics(SM_CYSCREEN)
        self._screen_size = (self._screen_width, self._screen_height)

    @property
    def screen_size(self) -> Tuple[int, int]:
        """Get screen size."""
        return self._screen_size

    def _check_blocked_key(self, key: str) -> None:
        """Check if a key is blocked and raise an error if so."""
        if key.lower() in self.BLOCKED_KEYS:
            raise BlockedKeyError(f"Key '{key}' is blocked for safety reasons")

    def _human_delay(self, base: float = 0.01, variance: float = 0.02) -> None:
        """Add human-like random delay."""
        if self.human_like:
            delay = base + random.uniform(0, variance)
            time.sleep(delay)

    def _send_input(self, *inputs: INPUT) -> int:
        """Send input events using SendInput API."""
        n_inputs = len(inputs)
        input_array = (INPUT * n_inputs)(*inputs)
        return user32.SendInput(n_inputs, input_array, ctypes.sizeof(INPUT))

    def _create_mouse_input(
        self,
        dx: int = 0,
        dy: int = 0,
        mouse_data: int = 0,
        flags: int = 0
    ) -> INPUT:
        """Create a mouse input structure."""
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi.dx = dx
        inp.union.mi.dy = dy
        inp.union.mi.mouseData = mouse_data
        inp.union.mi.dwFlags = flags
        inp.union.mi.time = 0
        inp.union.mi.dwExtraInfo = None
        return inp

    def _create_keyboard_input(
        self,
        vk: int = 0,
        scan: int = 0,
        flags: int = 0
    ) -> INPUT:
        """Create a keyboard input structure."""
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki.wVk = vk
        inp.union.ki.wScan = scan
        inp.union.ki.dwFlags = flags
        inp.union.ki.time = 0
        inp.union.ki.dwExtraInfo = None
        return inp

    def _to_absolute_coords(self, x: int, y: int) -> Tuple[int, int]:
        """Convert screen coordinates to absolute coordinates (0-65535 range)."""
        abs_x = int((x * 65536) / self._screen_width)
        abs_y = int((y * 65536) / self._screen_height)
        return abs_x, abs_y

    @property
    def mouse_position(self) -> Point:
        """Get current mouse position."""
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        return Point(point.x, point.y)

    def _clamp_coordinates(self, x: int, y: int) -> Tuple[int, int]:
        """Clamp coordinates to safe screen boundaries."""
        max_x = self._screen_width - self.SAFE_MARGIN
        max_y = self._screen_height - self.SAFE_MARGIN
        return (
            max(self.SAFE_MARGIN, min(x, max_x)),
            max(self.SAFE_MARGIN, min(y, max_y))
        )

    def move_to(self, x: int, y: int, duration: Optional[float] = None) -> Point:
        """
        Move mouse to coordinates with smooth human-like movement.

        Args:
            x: X coordinate
            y: Y coordinate
            duration: Movement duration (uses default if None)

        Returns:
            Final mouse position
        """
        x, y = self._clamp_coordinates(x, y)
        dur = duration if duration is not None else self.move_duration

        # Get current position
        current = self.mouse_position
        start_x, start_y = current.x, current.y

        if dur <= 0:
            # Instant move
            abs_x, abs_y = self._to_absolute_coords(x, y)
            inp = self._create_mouse_input(
                dx=abs_x, dy=abs_y,
                flags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
            )
            self._send_input(inp)
        else:
            # Smooth movement with easing
            steps = max(int(dur * 60), 5)  # ~60 fps
            for i in range(1, steps + 1):
                # Use ease-out cubic for natural movement
                t = i / steps
                ease_t = 1 - (1 - t) ** 3

                cx = int(start_x + (x - start_x) * ease_t)
                cy = int(start_y + (y - start_y) * ease_t)

                abs_x, abs_y = self._to_absolute_coords(cx, cy)
                inp = self._create_mouse_input(
                    dx=abs_x, dy=abs_y,
                    flags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
                )
                self._send_input(inp)
                time.sleep(dur / steps)

        self._human_delay(0.01, 0.02)
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
            self.move_to(x, y, duration=self.move_duration)
        else:
            pos = self.mouse_position
            x, y = pos.x, pos.y

        # Determine button flags
        if button == MouseButton.LEFT:
            down_flag = MOUSEEVENTF_LEFTDOWN
            up_flag = MOUSEEVENTF_LEFTUP
        elif button == MouseButton.RIGHT:
            down_flag = MOUSEEVENTF_RIGHTDOWN
            up_flag = MOUSEEVENTF_RIGHTUP
        else:  # MIDDLE
            down_flag = MOUSEEVENTF_MIDDLEDOWN
            up_flag = MOUSEEVENTF_MIDDLEUP

        for i in range(clicks):
            # Mouse down
            down_inp = self._create_mouse_input(flags=down_flag)
            self._send_input(down_inp)
            self._human_delay(0.02, 0.03)

            # Mouse up
            up_inp = self._create_mouse_input(flags=up_flag)
            self._send_input(up_inp)

            if i < clicks - 1:
                time.sleep(interval)
            self._human_delay(0.01, 0.02)

        time.sleep(self.pause)
        return Point(x, y)

    def double_click(self, x: Optional[int] = None, y: Optional[int] = None) -> Point:
        """Double-click at coordinates."""
        return self.click(x, y, clicks=2, interval=0.05)

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

        # Move to start and press
        self.move_to(start_x, start_y)
        self._human_delay(0.05, 0.05)

        # Determine button flags
        if button == MouseButton.LEFT:
            down_flag = MOUSEEVENTF_LEFTDOWN
            up_flag = MOUSEEVENTF_LEFTUP
        elif button == MouseButton.RIGHT:
            down_flag = MOUSEEVENTF_RIGHTDOWN
            up_flag = MOUSEEVENTF_RIGHTUP
        else:
            down_flag = MOUSEEVENTF_MIDDLEDOWN
            up_flag = MOUSEEVENTF_MIDDLEUP

        # Press button
        down_inp = self._create_mouse_input(flags=down_flag)
        self._send_input(down_inp)
        self._human_delay(0.05, 0.03)

        # Move to end position
        self.move_to(end_x, end_y, duration=duration)
        self._human_delay(0.05, 0.03)

        # Release button
        up_inp = self._create_mouse_input(flags=up_flag)
        self._send_input(up_inp)
        self._human_delay(0.02, 0.02)

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
            self.move_to(x, y)

        # Each click is 120 units (WHEEL_DELTA)
        wheel_delta = clicks * 120
        inp = self._create_mouse_input(
            mouse_data=wheel_delta,
            flags=MOUSEEVENTF_WHEEL
        )
        self._send_input(inp)
        self._human_delay(0.05, 0.05)

    def _get_vk_code(self, key: str) -> int:
        """Get virtual key code for a key name or character."""
        key_lower = key.lower()
        if key_lower in VK_CODES:
            return VK_CODES[key_lower]
        # For single characters, use VkKeyScan
        if len(key) == 1:
            result = user32.VkKeyScanW(ord(key))
            if result != -1:
                return result & 0xFF
        raise ValueError(f"Unknown key: {key}")

    def type_text(
        self,
        text: str,
        interval: float = 0.02,
        press_enter: bool = False
    ) -> None:
        """
        Type text with optional enter press. Supports Unicode.

        Args:
            text: Text to type
            interval: Interval between keystrokes
            press_enter: Press enter after typing
        """
        for char in text:
            self._type_unicode_char(char)
            if self.human_like:
                time.sleep(interval + random.uniform(0, interval))
            else:
                time.sleep(interval)

        if press_enter:
            self._human_delay(0.05, 0.05)
            self.press_key("enter")

    def _type_unicode_char(self, char: str) -> None:
        """Type a single Unicode character using SendInput."""
        # Create key down event
        down_inp = self._create_keyboard_input(
            scan=ord(char),
            flags=KEYEVENTF_UNICODE
        )
        # Create key up event
        up_inp = self._create_keyboard_input(
            scan=ord(char),
            flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
        )
        self._send_input(down_inp, up_inp)

    def write(self, text: str, interval: float = 0.0) -> None:
        """
        Write text (supports unicode).

        Args:
            text: Text to write
            interval: Interval between characters
        """
        self.type_text(text, interval=interval)

    def press_key(self, key: str, presses: int = 1, interval: float = 0.1) -> None:
        """
        Press a keyboard key.

        Args:
            key: Key name (e.g., 'enter', 'tab', 'escape', 'f1')
            presses: Number of key presses
            interval: Interval between presses

        Raises:
            BlockedKeyError: If the key is in the blocked list
        """
        self._check_blocked_key(key)
        vk = self._get_vk_code(key)

        for i in range(presses):
            # Key down
            down_inp = self._create_keyboard_input(vk=vk)
            self._send_input(down_inp)
            self._human_delay(0.02, 0.03)

            # Key up
            up_inp = self._create_keyboard_input(vk=vk, flags=KEYEVENTF_KEYUP)
            self._send_input(up_inp)

            if i < presses - 1:
                time.sleep(interval)
            self._human_delay(0.01, 0.02)

    def hotkey(self, *keys: str) -> None:
        """
        Press a hotkey combination.

        Args:
            keys: Keys to press together (e.g., 'ctrl', 'c')

        Raises:
            BlockedKeyError: If any key is in the blocked list
        """
        for key in keys:
            self._check_blocked_key(key)

        # Press all keys down
        for key in keys:
            vk = self._get_vk_code(key)
            down_inp = self._create_keyboard_input(vk=vk)
            self._send_input(down_inp)
            self._human_delay(0.01, 0.02)

        self._human_delay(0.02, 0.03)

        # Release all keys in reverse order
        for key in reversed(keys):
            vk = self._get_vk_code(key)
            up_inp = self._create_keyboard_input(vk=vk, flags=KEYEVENTF_KEYUP)
            self._send_input(up_inp)
            self._human_delay(0.01, 0.02)

    def hold_key(self, key: str) -> None:
        """
        Hold down a key.

        Raises:
            BlockedKeyError: If the key is in the blocked list
        """
        self._check_blocked_key(key)
        vk = self._get_vk_code(key)
        down_inp = self._create_keyboard_input(vk=vk)
        self._send_input(down_inp)

    def release_key(self, key: str) -> None:
        """
        Release a held key.

        Raises:
            BlockedKeyError: If the key is in the blocked list
        """
        self._check_blocked_key(key)
        vk = self._get_vk_code(key)
        up_inp = self._create_keyboard_input(vk=vk, flags=KEYEVENTF_KEYUP)
        self._send_input(up_inp)

    def key_combo(self, keys: List[str]) -> None:
        """
        Execute a key combination.

        Args:
            keys: List of keys (modifiers first)

        Raises:
            BlockedKeyError: If any key is in the blocked list
        """
        if len(keys) == 0:
            return
        self.hotkey(*keys)

    def wait(self, seconds: float) -> None:
        """Wait for specified seconds."""
        time.sleep(seconds)
