"""
Linux/Xvfb Controller Module

This module provides mouse and keyboard control for Linux environments,
using xdotool for mouse/key control and Chrome DevTools Protocol (CDP)
for typing into web page content (where xdotool fails).
"""

import json
import os
import subprocess
import time
import urllib.request
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
    try:
        import websocket
        HAS_WEBSOCKET = True
    except ImportError:
        HAS_WEBSOCKET = False
else:
    HAS_PYAUTOGUI = False
    HAS_WEBSOCKET = False


class LinuxController:
    """Mouse and keyboard controller for Linux/Xvfb environments."""

    # Map common key names to X11 keysym names used by xdotool
    KEY_MAP = {
        'enter': 'Return',
        'esc': 'Escape',
        'escape': 'Escape',
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

    # CDP key mapping for special keys
    CDP_KEY_MAP = {
        'Return': {'key': 'Enter', 'code': 'Enter', 'windowsVirtualKeyCode': 13},
        'Escape': {'key': 'Escape', 'code': 'Escape', 'windowsVirtualKeyCode': 27},
        'BackSpace': {'key': 'Backspace', 'code': 'Backspace', 'windowsVirtualKeyCode': 8},
        'Delete': {'key': 'Delete', 'code': 'Delete', 'windowsVirtualKeyCode': 46},
        'Tab': {'key': 'Tab', 'code': 'Tab', 'windowsVirtualKeyCode': 9},
        'space': {'key': ' ', 'code': 'Space', 'windowsVirtualKeyCode': 32},
        'Up': {'key': 'ArrowUp', 'code': 'ArrowUp', 'windowsVirtualKeyCode': 38},
        'Down': {'key': 'ArrowDown', 'code': 'ArrowDown', 'windowsVirtualKeyCode': 40},
        'Left': {'key': 'ArrowLeft', 'code': 'ArrowLeft', 'windowsVirtualKeyCode': 37},
        'Right': {'key': 'ArrowRight', 'code': 'ArrowRight', 'windowsVirtualKeyCode': 39},
        'Home': {'key': 'Home', 'code': 'Home', 'windowsVirtualKeyCode': 36},
        'End': {'key': 'End', 'code': 'End', 'windowsVirtualKeyCode': 35},
        'Page_Up': {'key': 'PageUp', 'code': 'PageUp', 'windowsVirtualKeyCode': 33},
        'Page_Down': {'key': 'PageDown', 'code': 'PageDown', 'windowsVirtualKeyCode': 34},
    }

    def __init__(self, display: Optional[str] = None, cdp_port: int = 9222):
        """
        Initialize controller.

        Args:
            display: X11 display string (e.g., ':99'). If None, uses DISPLAY env var.
            cdp_port: Chrome DevTools Protocol port for typing into web content.
        """
        self.display_str = display or os.environ.get('DISPLAY', ':99')
        self._env = os.environ.copy()
        self._env['DISPLAY'] = self.display_str
        self._cdp_port = cdp_port
        self._cdp_ws = None
        self._cdp_ws_url = None  # Track which WS URL we're connected to
        self._cdp_msg_id = 1

    def _run_xdotool(self, args: List[str]) -> subprocess.CompletedProcess:
        """Run xdotool command with proper display."""
        return subprocess.run(
            ['xdotool'] + args,
            env=self._env,
            capture_output=True,
            text=True
        )

    # ==================== CDP (Chrome DevTools Protocol) ====================

    def _cdp_get_ws_url(self) -> Optional[str]:
        """Get WebSocket URL for the active Chrome tab via CDP.
        Prefers http/https pages over chrome:// internal pages."""
        try:
            data = urllib.request.urlopen(
                f'http://127.0.0.1:{self._cdp_port}/json', timeout=2
            ).read()
            tabs = json.loads(data)
            # Collect page-type targets, preferring http/https URLs
            pages = [t for t in tabs if t.get('type') == 'page' and 'webSocketDebuggerUrl' in t]
            # Prefer non-chrome:// pages
            for tab in pages:
                url = tab.get('url', '')
                if url.startswith('http://') or url.startswith('https://') or url == 'about:blank':
                    return tab['webSocketDebuggerUrl']
            # Fall back to any page target
            if pages:
                return pages[0]['webSocketDebuggerUrl']
            return None
        except Exception:
            return None

    def _cdp_connect(self) -> bool:
        """Connect to Chrome via CDP WebSocket. Returns True if connected.
        Always verifies the connection points to the current active tab,
        reconnecting if the page target changed (e.g. after navigation)."""
        if not HAS_WEBSOCKET:
            return False

        ws_url = self._cdp_get_ws_url()
        if ws_url is None:
            self._cdp_disconnect()
            return False

        # If connected to a different target, disconnect and reconnect
        if self._cdp_ws is not None and self._cdp_ws_url != ws_url:
            self._cdp_disconnect()

        # Reuse existing connection if still open
        if self._cdp_ws is not None:
            try:
                self._cdp_ws.ping()
                return True
            except Exception:
                self._cdp_ws = None
                self._cdp_ws_url = None

        try:
            self._cdp_ws = websocket.create_connection(ws_url, timeout=5)
            self._cdp_ws_url = ws_url
            return True
        except Exception:
            self._cdp_ws = None
            self._cdp_ws_url = None
            return False

    def _cdp_send(self, method: str, params: Optional[dict] = None) -> Optional[dict]:
        """Send a CDP command and return the response."""
        if self._cdp_ws is None:
            return None
        msg = {'id': self._cdp_msg_id, 'method': method}
        if params:
            msg['params'] = params
        expected_id = self._cdp_msg_id
        self._cdp_msg_id += 1
        try:
            self._cdp_ws.send(json.dumps(msg))
            # Read responses until we get the matching id
            deadline = time.time() + 5
            while time.time() < deadline:
                resp = json.loads(self._cdp_ws.recv())
                if resp.get('id') == expected_id:
                    return resp
            return None
        except Exception:
            # Connection broken, reset
            self._cdp_ws = None
            return None

    def _cdp_disconnect(self):
        """Close CDP WebSocket connection."""
        if self._cdp_ws is not None:
            try:
                self._cdp_ws.close()
            except Exception:
                pass
            self._cdp_ws = None
        self._cdp_ws_url = None

    def _page_has_focused_editable(self) -> bool:
        """Check if there's a focused editable element in the page via CDP."""
        if not self._cdp_connect():
            return False
        check = self._cdp_send('Runtime.evaluate', {
            'expression': (
                '(() => {'
                '  const el = document.activeElement;'
                '  if (!el || el === document.body) return false;'
                '  const tag = el.tagName;'
                '  if (tag === "INPUT" || tag === "TEXTAREA") return true;'
                '  if (el.isContentEditable) return true;'
                '  if (el.getAttribute("role") === "textbox") return true;'
                '  if (el.getAttribute("role") === "combobox") return true;'
                '  return false;'
                '})()'
            ),
            'returnByValue': True,
        })
        return (
            check is not None
            and 'result' in check
            and check['result'].get('result', {}).get('value') is True
        )

    def _type_via_cdp(self, text: str) -> bool:
        """Type text using CDP Input.insertText. Returns True on success.
        Only uses CDP if there's a focused editable element in the page,
        to avoid intercepting typing intended for native UI (address bar).
        If no element is focused but the cursor is over a web page,
        dispatches a CDP click at cursor position to focus the element first."""
        if not self._cdp_connect():
            return False
        if not self._page_has_focused_editable():
            # Try a CDP click at current cursor position to focus the element.
            # xdotool clicks may not propagate focus to Chrome's DOM properly.
            cursor = self.get_cursor_position()
            if cursor == (0, 0):
                return False
            self._cdp_send('Input.dispatchMouseEvent', {
                'type': 'mousePressed',
                'x': cursor[0],
                'y': cursor[1],
                'button': 'left',
                'clickCount': 1,
            })
            time.sleep(0.05)
            self._cdp_send('Input.dispatchMouseEvent', {
                'type': 'mouseReleased',
                'x': cursor[0],
                'y': cursor[1],
                'button': 'left',
                'clickCount': 1,
            })
            time.sleep(0.2)
            # Re-check after CDP click
            if not self._page_has_focused_editable():
                return False
        resp = self._cdp_send('Input.insertText', {'text': text})
        return resp is not None and 'error' not in resp

    def _press_key_via_cdp(self, key_name: str) -> bool:
        """Press a key using CDP Input.dispatchKeyEvent. Returns True on success.
        Only uses CDP if a page element is focused (not native Chrome UI)."""
        cdp_info = self.CDP_KEY_MAP.get(key_name)
        if cdp_info is None:
            return False
        if not self._page_has_focused_editable():
            return False
        # keyDown
        params = {
            'type': 'keyDown',
            'key': cdp_info['key'],
            'code': cdp_info['code'],
            'windowsVirtualKeyCode': cdp_info['windowsVirtualKeyCode'],
            'nativeVirtualKeyCode': cdp_info['windowsVirtualKeyCode'],
        }
        resp = self._cdp_send('Input.dispatchKeyEvent', params)
        if resp is None or 'error' in resp:
            return False
        # keyUp
        params['type'] = 'keyUp'
        self._cdp_send('Input.dispatchKeyEvent', params)
        return True

    def _hotkey_via_cdp(self, keys: List[str]) -> bool:
        """Press a key combination using CDP. Returns True on success.
        Only uses CDP if a page element is focused (not native Chrome UI)."""
        if not self._page_has_focused_editable():
            return False

        # Map modifier names to CDP modifier flags
        cdp_mod_flags = {'ctrl': 2, 'alt': 1, 'shift': 8, 'meta': 4, 'super': 4}
        modifiers = 0
        non_mod_key = None
        for k in keys:
            flag = cdp_mod_flags.get(k.lower())
            if flag is not None:
                modifiers |= flag
            else:
                non_mod_key = k

        if non_mod_key is None:
            return False

        # Look up CDP key info
        cdp_info = self.CDP_KEY_MAP.get(non_mod_key)
        if cdp_info is None:
            # For letter keys
            if len(non_mod_key) == 1:
                cdp_info = {
                    'key': non_mod_key,
                    'code': f'Key{non_mod_key.upper()}',
                    'windowsVirtualKeyCode': ord(non_mod_key.upper()),
                }
            else:
                return False

        params = {
            'type': 'keyDown',
            'key': cdp_info['key'],
            'code': cdp_info['code'],
            'windowsVirtualKeyCode': cdp_info['windowsVirtualKeyCode'],
            'nativeVirtualKeyCode': cdp_info['windowsVirtualKeyCode'],
            'modifiers': modifiers,
        }
        resp = self._cdp_send('Input.dispatchKeyEvent', params)
        if resp is None or 'error' in resp:
            return False
        params['type'] = 'keyUp'
        self._cdp_send('Input.dispatchKeyEvent', params)
        return True

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

    def _get_focused_window(self) -> Optional[str]:
        """Get the currently focused window ID for targeted key delivery."""
        result = self._run_xdotool(['getactivewindow'])
        if result.returncode == 0:
            return result.stdout.strip()
        return None

    def type_text(self, text: str, interval: float = 0.0) -> None:
        """
        Type text string. Uses CDP (Chrome DevTools Protocol) as primary method,
        falls back to xdotool if CDP is unavailable.

        Args:
            text: Text to type.
            interval: Delay between keystrokes in seconds.
        """
        # Try CDP first — works reliably for web page content
        if self._type_via_cdp(text):
            return

        # Fallback to xdotool (works for native X11 widgets like address bar)
        window_id = self._get_focused_window()
        window_args = ['--window', window_id] if window_id else []

        if interval > 0:
            delay_ms = int(interval * 1000)
            self._run_xdotool(['type'] + window_args + ['--delay', str(delay_ms), '--', text])
        else:
            self._run_xdotool(['type'] + window_args + ['--', text])

    def press_key(self, key: str) -> None:
        """
        Press and release a single key. Tries CDP first, falls back to xdotool.

        Args:
            key: Key name (e.g., 'Return', 'Tab', 'Escape', 'a', 'F1').
        """
        mapped_key = self.KEY_MAP.get(key.lower(), key)

        # Try CDP first
        if self._press_key_via_cdp(mapped_key):
            return

        # Fallback to xdotool
        window_id = self._get_focused_window()
        if window_id:
            self._run_xdotool(['key', '--window', window_id, mapped_key])
        else:
            self._run_xdotool(['key', mapped_key])

    def hotkey(self, *keys: str) -> None:
        """
        Press a key combination. Tries CDP first, falls back to xdotool.

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

        # Build mapped key list for xdotool (also used to determine CDP key)
        mapped_keys = []
        for k in keys:
            mapped = mod_map.get(k.lower())
            if mapped is None:
                mapped = self.KEY_MAP.get(k.lower(), k)
            mapped_keys.append(mapped)

        # Try CDP first
        if self._hotkey_via_cdp(mapped_keys):
            return

        # Fallback to xdotool
        key_combo = '+'.join(mapped_keys)
        window_id = self._get_focused_window()
        if window_id:
            self._run_xdotool(['key', '--window', window_id, key_combo])
        else:
            self._run_xdotool(['key', key_combo])

    def key_down(self, key: str) -> None:
        """Press key without releasing."""
        window_id = self._get_focused_window()
        if window_id:
            self._run_xdotool(['keydown', '--window', window_id, key])
        else:
            self._run_xdotool(['keydown', key])

    def key_up(self, key: str) -> None:
        """Release key."""
        window_id = self._get_focused_window()
        if window_id:
            self._run_xdotool(['keyup', '--window', window_id, key])
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
