"""
Screen capture module using mss for fast, cross-platform screenshots.
Includes mouse cursor overlay for human-like navigation.
"""

import base64
import ctypes
import io
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import mss
from PIL import Image, ImageDraw


# Windows API for cursor position
user32 = ctypes.windll.user32


def get_cursor_position() -> Tuple[int, int]:
    """Get current mouse cursor position using Windows API."""
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def draw_cursor_on_image(img: Image.Image, cursor_pos: Tuple[int, int], scale: float = 1.0) -> Image.Image:
    """
    Draw a visible cursor indicator on the screenshot.

    Args:
        img: PIL Image to draw on
        cursor_pos: (x, y) position of cursor on screen
        scale: Scale factor applied to the image

    Returns:
        Image with cursor overlay
    """
    # Scale cursor position if image was scaled
    cx = int(cursor_pos[0] * scale)
    cy = int(cursor_pos[1] * scale)

    # Create a copy to draw on
    img = img.copy()
    draw = ImageDraw.Draw(img)

    # Draw a prominent cursor indicator (red crosshair with circle)
    cursor_size = max(15, int(20 * scale))
    line_width = max(2, int(3 * scale))

    # Outer circle (white for visibility)
    draw.ellipse(
        [cx - cursor_size, cy - cursor_size, cx + cursor_size, cy + cursor_size],
        outline="white",
        width=line_width + 2
    )

    # Inner circle (red)
    draw.ellipse(
        [cx - cursor_size, cy - cursor_size, cx + cursor_size, cy + cursor_size],
        outline="red",
        width=line_width
    )

    # Crosshair lines (white background)
    draw.line([(cx - cursor_size - 5, cy), (cx + cursor_size + 5, cy)], fill="white", width=line_width + 2)
    draw.line([(cx, cy - cursor_size - 5), (cx, cy + cursor_size + 5)], fill="white", width=line_width + 2)

    # Crosshair lines (red)
    draw.line([(cx - cursor_size - 5, cy), (cx + cursor_size + 5, cy)], fill="red", width=line_width)
    draw.line([(cx, cy - cursor_size - 5), (cx, cy + cursor_size + 5)], fill="red", width=line_width)

    # Center dot
    dot_size = max(3, int(4 * scale))
    draw.ellipse(
        [cx - dot_size, cy - dot_size, cx + dot_size, cy + dot_size],
        fill="red",
        outline="white"
    )

    return img


@dataclass
class ScreenInfo:
    """Information about the captured screen."""
    width: int
    height: int
    timestamp: float
    monitor_index: int


class ScreenCapture:
    """
    Fast screen capture using mss library.

    Supports:
    - Full screen capture
    - Region capture
    - Multi-monitor support
    - Base64 encoding for VLM API
    """

    def __init__(self, monitor_index: int = 1):
        """
        Initialize screen capture.

        Args:
            monitor_index: Monitor to capture (0 = all monitors, 1 = primary, 2+ = secondary)
        """
        self.monitor_index = monitor_index
        self._sct = mss.mss()

    @property
    def monitors(self) -> list:
        """Get list of available monitors."""
        return self._sct.monitors

    @property
    def screen_size(self) -> Tuple[int, int]:
        """Get the size of the current monitor."""
        mon = self._sct.monitors[self.monitor_index]
        return mon["width"], mon["height"]

    def capture(
        self,
        region: Optional[Tuple[int, int, int, int]] = None,
        scale: float = 1.0,
        include_cursor: bool = True
    ) -> Image.Image:
        """
        Capture the screen or a region.

        Args:
            region: Optional (left, top, width, height) tuple for region capture
            scale: Scale factor for the output image (0.5 = half size)
            include_cursor: Whether to draw cursor indicator on screenshot

        Returns:
            PIL Image of the captured screen
        """
        # Get cursor position BEFORE capturing (for accuracy)
        cursor_pos = get_cursor_position() if include_cursor else None

        if region:
            monitor = {
                "left": region[0],
                "top": region[1],
                "width": region[2],
                "height": region[3]
            }
        else:
            monitor = self._sct.monitors[self.monitor_index]

        # Capture screenshot
        sct_img = self._sct.grab(monitor)

        # Convert to PIL Image (BGRA to RGB)
        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

        # Scale if needed
        if scale != 1.0:
            new_size = (int(img.width * scale), int(img.height * scale))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        # Draw cursor indicator
        if include_cursor and cursor_pos:
            img = draw_cursor_on_image(img, cursor_pos, scale)

        return img

    def capture_to_base64(
        self,
        region: Optional[Tuple[int, int, int, int]] = None,
        scale: float = 1.0,
        format: str = "PNG",
        quality: int = 85,
        include_cursor: bool = True
    ) -> Tuple[str, ScreenInfo]:
        """
        Capture screen and encode as base64 for VLM API.

        Args:
            region: Optional region to capture
            scale: Scale factor
            format: Image format (PNG or JPEG)
            quality: JPEG quality (1-100)
            include_cursor: Whether to draw cursor indicator on screenshot

        Returns:
            Tuple of (base64 encoded string, ScreenInfo)
        """
        img = self.capture(region, scale, include_cursor=include_cursor)

        # Encode to base64
        buffer = io.BytesIO()
        if format.upper() == "JPEG":
            img.save(buffer, format="JPEG", quality=quality)
        else:
            img.save(buffer, format="PNG", optimize=True)

        base64_str = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")

        info = ScreenInfo(
            width=img.width,
            height=img.height,
            timestamp=time.time(),
            monitor_index=self.monitor_index
        )

        return base64_str, info

    def save_screenshot(
        self,
        path: Path,
        region: Optional[Tuple[int, int, int, int]] = None,
        scale: float = 1.0
    ) -> Path:
        """
        Capture and save screenshot to file.

        Args:
            path: Path to save the screenshot
            region: Optional region to capture
            scale: Scale factor

        Returns:
            Path to the saved file
        """
        img = self.capture(region, scale)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path)
        return path

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._sct.close()
