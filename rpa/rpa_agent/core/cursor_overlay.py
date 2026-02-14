"""
Visual cursor overlay that draws a visible indicator around the mouse cursor.
Uses Windows GDI to draw directly on the screen.
"""

import ctypes
import threading
import time
from ctypes import wintypes
from typing import Optional, Tuple

# Windows GDI constants
PS_SOLID = 0
NULL_BRUSH = 5
SRCCOPY = 0x00CC0020

# Load Windows DLLs
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


class CursorOverlay:
    """
    Draws a visible cursor indicator on screen.

    This creates a visual ring/crosshair around the mouse cursor
    that's always visible, even when the system cursor is hidden.
    """

    def __init__(
        self,
        color: Tuple[int, int, int] = (255, 0, 0),  # Red
        size: int = 25,
        line_width: int = 3,
        refresh_rate: float = 0.016  # ~60 fps
    ):
        """
        Initialize cursor overlay.

        Args:
            color: RGB color tuple for the indicator
            size: Radius of the cursor indicator
            line_width: Width of the indicator lines
            refresh_rate: How often to redraw (in seconds)
        """
        self.color = color
        self.size = size
        self.line_width = line_width
        self.refresh_rate = refresh_rate

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_pos: Tuple[int, int] = (0, 0)

        # Create GDI pen for drawing
        self._pen_color = self._rgb_to_colorref(color)

    def _rgb_to_colorref(self, rgb: Tuple[int, int, int]) -> int:
        """Convert RGB tuple to Windows COLORREF."""
        return rgb[0] | (rgb[1] << 8) | (rgb[2] << 16)

    def _get_cursor_pos(self) -> Tuple[int, int]:
        """Get current cursor position."""
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        return point.x, point.y

    def _draw_indicator(self, x: int, y: int) -> None:
        """Draw cursor indicator at position."""
        # Get screen DC
        hdc = user32.GetDC(None)
        if not hdc:
            return

        try:
            # Create pen
            pen = gdi32.CreatePen(PS_SOLID, self.line_width, self._pen_color)
            old_pen = gdi32.SelectObject(hdc, pen)

            # Use null brush for hollow shapes
            old_brush = gdi32.SelectObject(hdc, gdi32.GetStockObject(NULL_BRUSH))

            # Set ROP2 mode for XOR drawing (so we can erase by redrawing)
            old_rop = gdi32.SetROP2(hdc, 6)  # R2_NOTXORPEN

            # Draw circle
            gdi32.Ellipse(
                hdc,
                x - self.size, y - self.size,
                x + self.size, y + self.size
            )

            # Draw crosshair lines
            line_ext = self.size + 8
            gdi32.MoveToEx(hdc, x - line_ext, y, None)
            gdi32.LineTo(hdc, x - self.size + 5, y)

            gdi32.MoveToEx(hdc, x + self.size - 5, y, None)
            gdi32.LineTo(hdc, x + line_ext, y)

            gdi32.MoveToEx(hdc, x, y - line_ext, None)
            gdi32.LineTo(hdc, x, y - self.size + 5)

            gdi32.MoveToEx(hdc, x, y + self.size - 5, None)
            gdi32.LineTo(hdc, x, y + line_ext)

            # Restore old objects
            gdi32.SetROP2(hdc, old_rop)
            gdi32.SelectObject(hdc, old_brush)
            gdi32.SelectObject(hdc, old_pen)
            gdi32.DeleteObject(pen)

        finally:
            user32.ReleaseDC(None, hdc)

    def _erase_indicator(self, x: int, y: int) -> None:
        """Erase cursor indicator at position (by redrawing with XOR)."""
        # XOR drawing means drawing again erases
        self._draw_indicator(x, y)

    def _overlay_loop(self) -> None:
        """Main loop for drawing overlay."""
        while self._running:
            current_pos = self._get_cursor_pos()

            # Erase old indicator if position changed
            if self._last_pos != current_pos and self._last_pos != (0, 0):
                self._erase_indicator(*self._last_pos)

            # Draw new indicator
            self._draw_indicator(*current_pos)
            self._last_pos = current_pos

            time.sleep(self.refresh_rate)

        # Clean up - erase last indicator
        if self._last_pos != (0, 0):
            self._erase_indicator(*self._last_pos)

    def start(self) -> None:
        """Start the cursor overlay."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._overlay_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the cursor overlay."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def flash(self, times: int = 3, duration: float = 0.1) -> None:
        """Flash the indicator at current position."""
        pos = self._get_cursor_pos()
        for _ in range(times):
            self._draw_indicator(*pos)
            time.sleep(duration)
            self._erase_indicator(*pos)
            time.sleep(duration)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


# Global overlay instance
_overlay: Optional[CursorOverlay] = None


def start_cursor_overlay(
    color: Tuple[int, int, int] = (255, 0, 0),
    size: int = 25,
    line_width: int = 3
) -> CursorOverlay:
    """Start the global cursor overlay."""
    global _overlay
    if _overlay:
        _overlay.stop()
    _overlay = CursorOverlay(color=color, size=size, line_width=line_width)
    _overlay.start()
    return _overlay


def stop_cursor_overlay() -> None:
    """Stop the global cursor overlay."""
    global _overlay
    if _overlay:
        _overlay.stop()
        _overlay = None
