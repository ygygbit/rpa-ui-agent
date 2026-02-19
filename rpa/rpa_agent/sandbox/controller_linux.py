"""
Linux/Xvfb Controller Module

Provides mouse and keyboard control for Linux environments using
python-xlib XTEST extension for all input injection. XTEST events
are indistinguishable from real hardware input at the X11 level
(send_event=False), making them work reliably everywhere:
address bar, web page content, and non-Chrome applications.

Previous approach used xdotool subprocess calls + CDP fallback.
xdotool's --window flag forced XSendEvent (not XTEST), which Chrome
rejected for web content. This module eliminates both xdotool and CDP
by using python-xlib XTEST directly.
"""

import os
import subprocess
import time
from typing import Optional, Tuple, List
import sys

# Only import Linux-specific modules when on Linux
if sys.platform == 'linux':
    try:
        from Xlib.display import Display
        from Xlib import X, XK
        from Xlib.ext.xtest import fake_input as _xtest_fake_input
        HAS_XLIB = True
    except ImportError:
        HAS_XLIB = False
else:
    HAS_XLIB = False


class XTestInput:
    """Low-level XTEST event injection via python-xlib.

    All mouse and keyboard events are injected through the XTEST extension,
    which produces trusted events (send_event=False) that are accepted by
    all X11 applications including Chrome's web content area.
    """

    # Shift-required characters (US keyboard layout)
    SHIFT_CHARS = set('~!@#$%^&*()_+{}|:"<>?ABCDEFGHIJKLMNOPQRSTUVWXYZ')

    # Character to X11 keysym name mapping for special characters
    CHAR_TO_KEYSYM_NAME = {
        ' ': 'space',
        '\t': 'Tab',
        '\n': 'Return',
        '!': 'exclam',
        '@': 'at',
        '#': 'numbersign',
        '$': 'dollar',
        '%': 'percent',
        '^': 'asciicircum',
        '&': 'ampersand',
        '*': 'asterisk',
        '(': 'parenleft',
        ')': 'parenright',
        '-': 'minus',
        '_': 'underscore',
        '=': 'equal',
        '+': 'plus',
        '[': 'bracketleft',
        ']': 'bracketright',
        '{': 'braceleft',
        '}': 'braceright',
        '\\': 'backslash',
        '|': 'bar',
        ';': 'semicolon',
        ':': 'colon',
        "'": 'apostrophe',
        '"': 'quotedbl',
        ',': 'comma',
        '.': 'period',
        '<': 'less',
        '>': 'greater',
        '/': 'slash',
        '?': 'question',
        '`': 'grave',
        '~': 'asciitilde',
    }

    # Named key to X11 keysym constant mapping
    KEY_TO_KEYSYM = {
        'return': XK.XK_Return if HAS_XLIB else 0,
        'enter': XK.XK_Return if HAS_XLIB else 0,
        'escape': XK.XK_Escape if HAS_XLIB else 0,
        'esc': XK.XK_Escape if HAS_XLIB else 0,
        'backspace': XK.XK_BackSpace if HAS_XLIB else 0,
        'delete': XK.XK_Delete if HAS_XLIB else 0,
        'tab': XK.XK_Tab if HAS_XLIB else 0,
        'space': XK.XK_space if HAS_XLIB else 0,
        'up': XK.XK_Up if HAS_XLIB else 0,
        'down': XK.XK_Down if HAS_XLIB else 0,
        'left': XK.XK_Left if HAS_XLIB else 0,
        'right': XK.XK_Right if HAS_XLIB else 0,
        'home': XK.XK_Home if HAS_XLIB else 0,
        'end': XK.XK_End if HAS_XLIB else 0,
        'pageup': XK.XK_Page_Up if HAS_XLIB else 0,
        'page_up': XK.XK_Page_Up if HAS_XLIB else 0,
        'pagedown': XK.XK_Page_Down if HAS_XLIB else 0,
        'page_down': XK.XK_Page_Down if HAS_XLIB else 0,
        'f1': XK.XK_F1 if HAS_XLIB else 0,
        'f2': XK.XK_F2 if HAS_XLIB else 0,
        'f3': XK.XK_F3 if HAS_XLIB else 0,
        'f4': XK.XK_F4 if HAS_XLIB else 0,
        'f5': XK.XK_F5 if HAS_XLIB else 0,
        'f6': XK.XK_F6 if HAS_XLIB else 0,
        'f7': XK.XK_F7 if HAS_XLIB else 0,
        'f8': XK.XK_F8 if HAS_XLIB else 0,
        'f9': XK.XK_F9 if HAS_XLIB else 0,
        'f10': XK.XK_F10 if HAS_XLIB else 0,
        'f11': XK.XK_F11 if HAS_XLIB else 0,
        'f12': XK.XK_F12 if HAS_XLIB else 0,
    }

    # Modifier key names to keysym
    MODIFIER_KEYSYMS = {
        'ctrl': XK.XK_Control_L if HAS_XLIB else 0,
        'control': XK.XK_Control_L if HAS_XLIB else 0,
        'alt': XK.XK_Alt_L if HAS_XLIB else 0,
        'shift': XK.XK_Shift_L if HAS_XLIB else 0,
        'super': XK.XK_Super_L if HAS_XLIB else 0,
        'win': XK.XK_Super_L if HAS_XLIB else 0,
        'meta': XK.XK_Super_L if HAS_XLIB else 0,
    }

    def __init__(self, display_str: str = ':99'):
        if not HAS_XLIB:
            raise RuntimeError("python-xlib not available")
        self._display = Display(display_str)
        self._root = self._display.screen().root
        self._shift_keycode = self._display.keysym_to_keycode(XK.XK_Shift_L)
        # Cache keycodes for characters
        self._char_keycode_cache = {}

    def _flush(self):
        """Flush display buffer to ensure events are sent."""
        self._display.flush()

    # ==================== Mouse Operations ====================

    def move_to(self, x: int, y: int):
        """Move mouse to absolute position."""
        _xtest_fake_input(self._display, X.MotionNotify, x=x, y=y)
        self._flush()

    def button_press(self, button: int = 1):
        """Press a mouse button (1=left, 2=middle, 3=right)."""
        _xtest_fake_input(self._display, X.ButtonPress, button)
        self._flush()

    def button_release(self, button: int = 1):
        """Release a mouse button."""
        _xtest_fake_input(self._display, X.ButtonRelease, button)
        self._flush()

    def click(self, x: int, y: int, button: int = 1):
        """Move to position and click."""
        self.move_to(x, y)
        time.sleep(0.03)
        self.button_press(button)
        time.sleep(0.02)
        self.button_release(button)

    def get_cursor_position(self) -> Tuple[int, int]:
        """Get current mouse cursor position."""
        ptr = self._root.query_pointer()
        return (ptr.root_x, ptr.root_y)

    def get_screen_size(self) -> Tuple[int, int]:
        """Get screen dimensions."""
        screen = self._display.screen()
        return (screen.width_in_pixels, screen.height_in_pixels)

    # ==================== Keyboard Operations ====================

    def _char_to_keycode(self, char: str) -> Tuple[Optional[int], bool]:
        """Convert a character to (keycode, needs_shift)."""
        if char in self._char_keycode_cache:
            return self._char_keycode_cache[char]

        needs_shift = char in self.SHIFT_CHARS

        # Try keysym name mapping for special characters
        if char in self.CHAR_TO_KEYSYM_NAME:
            keysym = XK.string_to_keysym(self.CHAR_TO_KEYSYM_NAME[char])
        else:
            # Regular letters/digits
            keysym = XK.string_to_keysym(char)

        if keysym == 0:
            keysym = XK.string_to_keysym(char.lower())
            if keysym == 0:
                self._char_keycode_cache[char] = (None, False)
                return (None, False)

        keycode = self._display.keysym_to_keycode(keysym)
        if keycode == 0:
            # Try lowercase variant for shifted chars
            keysym_lower = XK.string_to_keysym(char.lower())
            keycode = self._display.keysym_to_keycode(keysym_lower)
            if keycode == 0:
                self._char_keycode_cache[char] = (None, False)
                return (None, False)

        self._char_keycode_cache[char] = (keycode, needs_shift)
        return (keycode, needs_shift)

    def _key_name_to_keycode(self, key_name: str) -> Optional[int]:
        """Convert a named key to a keycode."""
        key_lower = key_name.lower()

        # Check modifier keys
        if key_lower in self.MODIFIER_KEYSYMS:
            keysym = self.MODIFIER_KEYSYMS[key_lower]
            return self._display.keysym_to_keycode(keysym) if keysym else None

        # Check named keys (Enter, Escape, etc.)
        if key_lower in self.KEY_TO_KEYSYM:
            keysym = self.KEY_TO_KEYSYM[key_lower]
            return self._display.keysym_to_keycode(keysym) if keysym else None

        # Single character
        if len(key_name) == 1:
            kc, _ = self._char_to_keycode(key_name)
            return kc

        # Try as X11 keysym name directly (e.g., 'Return', 'BackSpace')
        keysym = XK.string_to_keysym(key_name)
        if keysym:
            return self._display.keysym_to_keycode(keysym)

        return None

    def key_press(self, keycode: int):
        """Press a key (without releasing)."""
        _xtest_fake_input(self._display, X.KeyPress, keycode)
        self._flush()

    def key_release(self, keycode: int):
        """Release a key."""
        _xtest_fake_input(self._display, X.KeyRelease, keycode)
        self._flush()

    def press_key(self, keycode: int, shift: bool = False):
        """Press and release a key, optionally with shift."""
        if shift:
            self.key_press(self._shift_keycode)
        self.key_press(keycode)
        time.sleep(0.01)
        self.key_release(keycode)
        if shift:
            self.key_release(self._shift_keycode)

    def type_char(self, char: str):
        """Type a single character."""
        keycode, needs_shift = self._char_to_keycode(char)
        if keycode is not None:
            self.press_key(keycode, shift=needs_shift)

    def type_string(self, text: str, interval: float = 0.02):
        """Type a full string character by character."""
        for char in text:
            self.type_char(char)
            if interval > 0:
                time.sleep(interval)

    def press_named_key(self, key_name: str):
        """Press a named key (e.g., 'Return', 'Escape', 'Tab')."""
        keycode = self._key_name_to_keycode(key_name)
        if keycode is not None:
            self.press_key(keycode)

    def hotkey(self, *key_names: str):
        """Press a key combination (e.g., hotkey('ctrl', 'a'))."""
        keycodes = []
        for name in key_names:
            kc = self._key_name_to_keycode(name)
            if kc is not None:
                keycodes.append(kc)

        # Press all keys down
        for kc in keycodes:
            self.key_press(kc)
        time.sleep(0.02)
        # Release in reverse order
        for kc in reversed(keycodes):
            self.key_release(kc)

    # ==================== Window Operations ====================

    def get_focused_window(self):
        """Get the currently focused window."""
        focus = self._display.get_input_focus()
        return focus.focus


class LinuxController:
    """Mouse and keyboard controller for Linux/Xvfb environments.

    Uses XTEST extension via python-xlib for all input injection.
    Falls back to xdotool only for complex window search operations.
    """

    def __init__(self, display: Optional[str] = None):
        """
        Initialize controller.

        Args:
            display: X11 display string (e.g., ':99'). If None, uses DISPLAY env var.
        """
        self.display_str = display or os.environ.get('DISPLAY', ':99')
        self._env = os.environ.copy()
        self._env['DISPLAY'] = self.display_str

        # Primary input backend: XTEST via python-xlib
        if HAS_XLIB:
            self._xtest = XTestInput(self.display_str)
        else:
            self._xtest = None

    def _run_xdotool(self, args: List[str]) -> subprocess.CompletedProcess:
        """Run xdotool command (fallback for window operations only)."""
        return subprocess.run(
            ['xdotool'] + args,
            env=self._env,
            capture_output=True,
            text=True
        )

    # ==================== Mouse Operations ====================

    def move_to(self, x: int, y: int, duration: float = 0.0) -> None:
        """Move mouse to absolute position."""
        if self._xtest:
            if duration > 0:
                # Smooth motion: interpolate positions
                cur_x, cur_y = self._xtest.get_cursor_position()
                steps = max(int(duration * 60), 2)  # ~60fps
                for i in range(1, steps + 1):
                    t = i / steps
                    ix = int(cur_x + (x - cur_x) * t)
                    iy = int(cur_y + (y - cur_y) * t)
                    self._xtest.move_to(ix, iy)
                    time.sleep(duration / steps)
            else:
                self._xtest.move_to(x, y)
        else:
            self._run_xdotool(['mousemove', str(x), str(y)])

    def move_relative(self, dx: int, dy: int, duration: float = 0.0) -> None:
        """Move mouse relative to current position."""
        if self._xtest:
            cur_x, cur_y = self._xtest.get_cursor_position()
            self.move_to(cur_x + dx, cur_y + dy, duration=duration)
        else:
            self._run_xdotool(['mousemove_relative', str(dx), str(dy)])

    def click(
        self,
        x: Optional[int] = None,
        y: Optional[int] = None,
        button: str = 'left'
    ) -> None:
        """Click at position (or current position if x, y not specified)."""
        button_map = {'left': 1, 'middle': 2, 'right': 3}
        btn = button_map.get(button, 1)

        if self._xtest:
            if x is not None and y is not None:
                self._xtest.move_to(x, y)
                time.sleep(0.03)
            self._xtest.button_press(btn)
            time.sleep(0.02)
            self._xtest.button_release(btn)
        else:
            xdotool_btn = str(btn)
            if x is not None and y is not None:
                self._run_xdotool(['mousemove', str(x), str(y)])
                time.sleep(0.05)
            self._run_xdotool(['click', xdotool_btn])

    def double_click(self, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """Double-click at position."""
        if self._xtest:
            if x is not None and y is not None:
                self._xtest.move_to(x, y)
                time.sleep(0.03)
            self._xtest.button_press(1)
            time.sleep(0.02)
            self._xtest.button_release(1)
            time.sleep(0.05)
            self._xtest.button_press(1)
            time.sleep(0.02)
            self._xtest.button_release(1)
        else:
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
        """Drag from start to end position."""
        button_map = {'left': 1, 'middle': 2, 'right': 3}
        btn = button_map.get(button, 1)

        if self._xtest:
            self._xtest.move_to(start_x, start_y)
            time.sleep(0.1)
            self._xtest.button_press(btn)
            time.sleep(0.05)

            # Smooth drag motion
            steps = max(int(duration * 60), 2)
            for i in range(1, steps + 1):
                t = i / steps
                ix = int(start_x + (end_x - start_x) * t)
                iy = int(start_y + (end_y - start_y) * t)
                self._xtest.move_to(ix, iy)
                time.sleep(duration / steps)

            time.sleep(0.05)
            self._xtest.button_release(btn)
        else:
            xdotool_btn = str(btn)
            self._run_xdotool(['mousemove', str(start_x), str(start_y)])
            time.sleep(0.1)
            self._run_xdotool(['mousedown', xdotool_btn])
            time.sleep(0.05)
            self._run_xdotool(['mousemove', str(end_x), str(end_y)])
            time.sleep(0.05)
            self._run_xdotool(['mouseup', xdotool_btn])

    def scroll(self, amount: int, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """Scroll at position. Positive = up, negative = down."""
        if self._xtest:
            if x is not None and y is not None:
                self._xtest.move_to(x, y)
                time.sleep(0.03)
            # Button 4 = scroll up, button 5 = scroll down
            btn = 4 if amount > 0 else 5
            for _ in range(abs(amount)):
                self._xtest.button_press(btn)
                self._xtest.button_release(btn)
                time.sleep(0.02)
        else:
            if x is not None and y is not None:
                self._run_xdotool(['mousemove', str(x), str(y)])
                time.sleep(0.05)
            if amount > 0:
                for _ in range(abs(amount)):
                    self._run_xdotool(['click', '4'])
            else:
                for _ in range(abs(amount)):
                    self._run_xdotool(['click', '5'])

    # ==================== Keyboard Operations ====================

    def type_text(self, text: str, interval: float = 0.02) -> None:
        """Type text string using XTEST key events."""
        if self._xtest:
            self._xtest.type_string(text, interval=interval)
        else:
            self._run_xdotool(['type', '--', text])

    def press_key(self, key: str) -> None:
        """Press and release a single key."""
        if self._xtest:
            self._xtest.press_named_key(key)
        else:
            self._run_xdotool(['key', key])

    def hotkey(self, *keys: str) -> None:
        """Press a key combination (e.g., hotkey('ctrl', 'c'))."""
        if self._xtest:
            self._xtest.hotkey(*keys)
        else:
            key_combo = '+'.join(keys)
            self._run_xdotool(['key', key_combo])

    def key_down(self, key: str) -> None:
        """Press key without releasing."""
        if self._xtest:
            keycode = self._xtest._key_name_to_keycode(key)
            if keycode is not None:
                self._xtest.key_press(keycode)
        else:
            self._run_xdotool(['keydown', key])

    def key_up(self, key: str) -> None:
        """Release key."""
        if self._xtest:
            keycode = self._xtest._key_name_to_keycode(key)
            if keycode is not None:
                self._xtest.key_release(keycode)
        else:
            self._run_xdotool(['keyup', key])

    # ==================== Window Operations ====================

    def get_active_window(self) -> Optional[str]:
        """Get active window ID."""
        result = self._run_xdotool(['getactivewindow'])
        if result.returncode == 0:
            return result.stdout.strip()
        return None

    def focus_window(self, title: str) -> bool:
        """Focus window by title (partial match)."""
        result = self._run_xdotool(['search', '--name', title, 'windowactivate'])
        return result.returncode == 0

    def get_window_geometry(self, window_id: Optional[str] = None) -> Optional[Tuple[int, int, int, int]]:
        """Get window geometry. Returns (x, y, width, height) or None."""
        if window_id is None:
            window_id = self.get_active_window()
            if window_id is None:
                return None

        result = self._run_xdotool(['getwindowgeometry', '--shell', window_id])
        if result.returncode != 0:
            return None

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
        if self._xtest:
            return self._xtest.get_cursor_position()
        else:
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
