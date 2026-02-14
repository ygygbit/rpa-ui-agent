"""
Visual cursor overlay using a transparent tkinter window.
Much more reliable than GDI drawing - no ghosting or artifacts.
Uses click-through window so it doesn't intercept mouse events.
"""

import ctypes
import threading
import time
from ctypes import wintypes
from typing import Optional, Tuple

# Windows API for cursor position and window styles
user32 = ctypes.windll.user32

# Windows constants for click-through window
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020


def get_cursor_position() -> Tuple[int, int]:
    """Get current cursor position using Windows API."""
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def make_window_click_through(hwnd: int) -> None:
    """Make a window click-through using Windows API."""
    # Get current extended style
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    # Add layered and transparent styles
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)


class CursorOverlay:
    """
    Draws a visible cursor indicator on screen using a transparent tkinter window.
    This is much more reliable than GDI drawing - no ghosting or artifacts.
    """

    def __init__(
        self,
        color: str = "red",
        size: int = 40,
        line_width: int = 4,
        refresh_rate: float = 0.016  # ~60 fps
    ):
        """
        Initialize cursor overlay.

        Args:
            color: Color name for the indicator (e.g., "red", "#FF0000")
            size: Size of the cursor indicator (diameter)
            line_width: Width of the indicator lines
            refresh_rate: How often to update position (in seconds)
        """
        self.color = color
        self.size = size
        self.line_width = line_width
        self.refresh_rate = refresh_rate

        self._running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._root = None
        self._canvas = None

    def _create_window(self):
        """Create the transparent overlay window."""
        import tkinter as tk

        # Create root window
        self._root = tk.Tk()
        self._root.title("")

        # Calculate window size (slightly larger than indicator)
        window_size = self.size + 20

        # Make window transparent and always on top
        self._root.attributes("-topmost", True)  # Always on top
        self._root.attributes("-transparentcolor", "white")  # White = transparent
        self._root.overrideredirect(True)  # No window decorations

        # Set window size
        self._root.geometry(f"{window_size}x{window_size}")

        # Create canvas with white background (transparent)
        self._canvas = tk.Canvas(
            self._root,
            width=window_size,
            height=window_size,
            bg="white",
            highlightthickness=0
        )
        self._canvas.pack()

        # Draw the cursor indicator
        center = window_size // 2
        radius = self.size // 2

        # Outer circle
        self._canvas.create_oval(
            center - radius, center - radius,
            center + radius, center + radius,
            outline=self.color,
            width=self.line_width
        )

        # Inner circle
        inner_radius = radius - 8
        self._canvas.create_oval(
            center - inner_radius, center - inner_radius,
            center + inner_radius, center + inner_radius,
            outline=self.color,
            width=max(2, self.line_width - 2)
        )

        # Crosshair lines (extending beyond circle)
        line_ext = radius + 10
        gap = radius - 5

        # Horizontal lines
        self._canvas.create_line(
            center - line_ext, center,
            center - gap, center,
            fill=self.color, width=self.line_width
        )
        self._canvas.create_line(
            center + gap, center,
            center + line_ext, center,
            fill=self.color, width=self.line_width
        )

        # Vertical lines
        self._canvas.create_line(
            center, center - line_ext,
            center, center - gap,
            fill=self.color, width=self.line_width
        )
        self._canvas.create_line(
            center, center + gap,
            center, center + line_ext,
            fill=self.color, width=self.line_width
        )

        # Center dot
        dot_size = 5
        self._canvas.create_oval(
            center - dot_size, center - dot_size,
            center + dot_size, center + dot_size,
            fill=self.color, outline=self.color
        )

        # Make the window click-through after it's fully created
        self._root.update()  # Ensure window is created
        hwnd = ctypes.windll.user32.GetParent(self._root.winfo_id())
        if hwnd == 0:
            # If GetParent returns 0, try getting the window directly
            hwnd = self._root.winfo_id()
        # Find the top-level window
        hwnd = ctypes.windll.user32.GetAncestor(self._root.winfo_id(), 2)  # GA_ROOT = 2
        make_window_click_through(hwnd)

    def _update_position(self):
        """Update window position to follow cursor."""
        if not self._running or not self._root:
            return

        if self._paused:
            # Hide window when paused
            self._root.withdraw()
        else:
            # Show window and update position
            self._root.deiconify()
            x, y = get_cursor_position()
            window_size = self.size + 20
            # Center the window on cursor
            self._root.geometry(f"+{x - window_size // 2}+{y - window_size // 2}")

        # Schedule next update
        if self._running:
            self._root.after(int(self.refresh_rate * 1000), self._update_position)

    def _run_mainloop(self):
        """Run the tkinter main loop in a thread."""
        self._create_window()
        self._update_position()
        self._root.mainloop()

    def start(self) -> None:
        """Start the cursor overlay."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_mainloop, daemon=True)
        self._thread.start()
        # Give time for window to initialize
        time.sleep(0.1)

    def stop(self) -> None:
        """Stop the cursor overlay."""
        self._running = False
        if self._root:
            try:
                self._root.quit()
                self._root.destroy()
            except Exception:
                pass
            self._root = None
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def pause(self) -> None:
        """Pause the overlay (hide it temporarily)."""
        self._paused = True
        time.sleep(self.refresh_rate * 2)  # Wait for update cycle

    def resume(self) -> None:
        """Resume the overlay after pausing."""
        self._paused = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


# Global overlay instance
_overlay: Optional[CursorOverlay] = None


def start_cursor_overlay(
    color: str = "red",
    size: int = 40,
    line_width: int = 4
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
