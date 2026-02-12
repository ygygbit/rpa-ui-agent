"""
Window management module for Windows using win32 APIs.

Provides window enumeration, focus, resize, and positioning.
"""

import ctypes
from dataclasses import dataclass
from typing import List, Optional, Tuple

try:
    import win32gui
    import win32con
    import win32process
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


@dataclass
class WindowInfo:
    """Information about a window."""
    hwnd: int
    title: str
    class_name: str
    rect: Tuple[int, int, int, int]  # left, top, right, bottom
    is_visible: bool
    is_minimized: bool
    process_id: int

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]

    @property
    def position(self) -> Tuple[int, int]:
        return (self.rect[0], self.rect[1])

    @property
    def size(self) -> Tuple[int, int]:
        return (self.width, self.height)


class WindowManager:
    """
    Windows window management using win32 APIs.

    Features:
    - Window enumeration
    - Focus and activation
    - Resize and move
    - Minimize/maximize/restore
    """

    def __init__(self):
        if not HAS_WIN32:
            raise ImportError(
                "pywin32 is required for WindowManager. "
                "Install with: pip install pywin32"
            )

    def get_all_windows(self, visible_only: bool = True) -> List[WindowInfo]:
        """
        Get all windows.

        Args:
            visible_only: Only return visible windows

        Returns:
            List of WindowInfo objects
        """
        windows = []

        def enum_callback(hwnd, _):
            if visible_only and not win32gui.IsWindowVisible(hwnd):
                return True

            try:
                title = win32gui.GetWindowText(hwnd)
                class_name = win32gui.GetClassName(hwnd)
                rect = win32gui.GetWindowRect(hwnd)
                is_minimized = win32gui.IsIconic(hwnd)

                _, pid = win32process.GetWindowThreadProcessId(hwnd)

                windows.append(WindowInfo(
                    hwnd=hwnd,
                    title=title,
                    class_name=class_name,
                    rect=rect,
                    is_visible=win32gui.IsWindowVisible(hwnd),
                    is_minimized=bool(is_minimized),
                    process_id=pid
                ))
            except Exception:
                pass

            return True

        win32gui.EnumWindows(enum_callback, None)
        return windows

    def find_window(self, title: Optional[str] = None, class_name: Optional[str] = None) -> Optional[WindowInfo]:
        """
        Find a window by title or class name.

        Args:
            title: Window title (partial match)
            class_name: Window class name (exact match)

        Returns:
            WindowInfo or None if not found
        """
        windows = self.get_all_windows()

        for win in windows:
            if title and title.lower() in win.title.lower():
                return win
            if class_name and win.class_name == class_name:
                return win

        return None

    def find_windows_by_title(self, title: str) -> List[WindowInfo]:
        """Find all windows matching title (partial match)."""
        windows = self.get_all_windows()
        return [w for w in windows if title.lower() in w.title.lower()]

    def get_foreground_window(self) -> Optional[WindowInfo]:
        """Get the currently focused window."""
        hwnd = win32gui.GetForegroundWindow()
        if hwnd == 0:
            return None

        try:
            title = win32gui.GetWindowText(hwnd)
            class_name = win32gui.GetClassName(hwnd)
            rect = win32gui.GetWindowRect(hwnd)
            is_minimized = win32gui.IsIconic(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)

            return WindowInfo(
                hwnd=hwnd,
                title=title,
                class_name=class_name,
                rect=rect,
                is_visible=True,
                is_minimized=bool(is_minimized),
                process_id=pid
            )
        except Exception:
            return None

    def focus_window(self, hwnd: int) -> bool:
        """
        Bring window to foreground and focus it.

        Args:
            hwnd: Window handle

        Returns:
            True if successful
        """
        try:
            # Restore if minimized
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

            # Set foreground window
            win32gui.SetForegroundWindow(hwnd)
            return True
        except Exception:
            return False

    def focus_window_by_title(self, title: str) -> bool:
        """Focus window by title (partial match)."""
        window = self.find_window(title=title)
        if window:
            return self.focus_window(window.hwnd)
        return False

    def minimize_window(self, hwnd: int) -> bool:
        """Minimize a window."""
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
            return True
        except Exception:
            return False

    def maximize_window(self, hwnd: int) -> bool:
        """Maximize a window."""
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
            return True
        except Exception:
            return False

    def restore_window(self, hwnd: int) -> bool:
        """Restore a minimized/maximized window."""
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            return True
        except Exception:
            return False

    def move_window(self, hwnd: int, x: int, y: int) -> bool:
        """
        Move window to position.

        Args:
            hwnd: Window handle
            x, y: New position

        Returns:
            True if successful
        """
        try:
            rect = win32gui.GetWindowRect(hwnd)
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]
            win32gui.MoveWindow(hwnd, x, y, width, height, True)
            return True
        except Exception:
            return False

    def resize_window(self, hwnd: int, width: int, height: int) -> bool:
        """
        Resize window.

        Args:
            hwnd: Window handle
            width, height: New size

        Returns:
            True if successful
        """
        try:
            rect = win32gui.GetWindowRect(hwnd)
            win32gui.MoveWindow(hwnd, rect[0], rect[1], width, height, True)
            return True
        except Exception:
            return False

    def set_window_position(
        self,
        hwnd: int,
        x: int,
        y: int,
        width: int,
        height: int
    ) -> bool:
        """
        Set window position and size.

        Args:
            hwnd: Window handle
            x, y: Position
            width, height: Size

        Returns:
            True if successful
        """
        try:
            win32gui.MoveWindow(hwnd, x, y, width, height, True)
            return True
        except Exception:
            return False

    def close_window(self, hwnd: int) -> bool:
        """
        Send close message to window.

        Args:
            hwnd: Window handle

        Returns:
            True if message sent successfully
        """
        try:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            return True
        except Exception:
            return False

    def get_window_at_point(self, x: int, y: int) -> Optional[WindowInfo]:
        """Get window at screen coordinates."""
        hwnd = win32gui.WindowFromPoint((x, y))
        if hwnd == 0:
            return None

        # Get top-level parent
        while True:
            parent = win32gui.GetParent(hwnd)
            if parent == 0:
                break
            hwnd = parent

        try:
            title = win32gui.GetWindowText(hwnd)
            class_name = win32gui.GetClassName(hwnd)
            rect = win32gui.GetWindowRect(hwnd)
            is_minimized = win32gui.IsIconic(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)

            return WindowInfo(
                hwnd=hwnd,
                title=title,
                class_name=class_name,
                rect=rect,
                is_visible=True,
                is_minimized=bool(is_minimized),
                process_id=pid
            )
        except Exception:
            return None
