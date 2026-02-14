"""
Screen capture module using mss for fast, cross-platform screenshots.
Includes mouse cursor overlay and navigation aids for human-like navigation.
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
from PIL import Image, ImageDraw, ImageFont


# Windows API for cursor position
user32 = ctypes.windll.user32

# Colors for navigation aids (semi-transparent look achieved via color choice)
GRID_COLOR = (100, 100, 100)  # Gray for grid lines
GRID_LABEL_COLOR = (200, 200, 50)  # Yellow for coordinate labels
RING_COLORS = {
    50: (0, 255, 255),    # Cyan for 50px
    100: (255, 255, 0),   # Yellow for 100px
    200: (255, 165, 0),   # Orange for 200px
}


def get_cursor_position() -> Tuple[int, int]:
    """Get current mouse cursor position using Windows API."""
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def draw_navigation_grid(img: Image.Image, grid_spacing: int = 200, scale: float = 1.0) -> Image.Image:
    """
    Draw a navigation grid with coordinate labels on the image.

    Args:
        img: PIL Image to draw on
        grid_spacing: Spacing between grid lines in pixels (before scaling)
        scale: Scale factor applied to the image

    Returns:
        Image with grid overlay
    """
    draw = ImageDraw.Draw(img, 'RGBA')
    width, height = img.size

    # Scaled grid spacing
    spacing = int(grid_spacing * scale)

    # Try to load a font, fall back to default
    try:
        font = ImageFont.truetype("arial.ttf", max(10, int(12 * scale)))
    except:
        font = ImageFont.load_default()

    # Draw vertical lines and labels
    x = 0
    while x < width:
        # Draw line (thin, semi-transparent gray)
        draw.line([(x, 0), (x, height)], fill=(*GRID_COLOR, 80), width=1)

        # Draw coordinate label at top
        label = str(int(x / scale))
        draw.text((x + 2, 2), label, fill=(*GRID_LABEL_COLOR, 200), font=font)

        x += spacing

    # Draw horizontal lines and labels
    y = 0
    while y < height:
        # Draw line
        draw.line([(0, y), (width, y)], fill=(*GRID_COLOR, 80), width=1)

        # Draw coordinate label at left edge
        label = str(int(y / scale))
        draw.text((2, y + 2), label, fill=(*GRID_LABEL_COLOR, 200), font=font)

        y += spacing

    return img


def draw_distance_rings(img: Image.Image, cursor_pos: Tuple[int, int], scale: float = 1.0) -> Image.Image:
    """
    Draw distance rings around the cursor position.

    Args:
        img: PIL Image to draw on
        cursor_pos: (x, y) position of cursor on screen (before scaling)
        scale: Scale factor applied to the image

    Returns:
        Image with distance rings
    """
    draw = ImageDraw.Draw(img, 'RGBA')

    # Scale cursor position
    cx = int(cursor_pos[0] * scale)
    cy = int(cursor_pos[1] * scale)

    # Try to load a font for labels
    try:
        font = ImageFont.truetype("arial.ttf", max(10, int(11 * scale)))
    except:
        font = ImageFont.load_default()

    # Draw rings at different distances
    for distance, color in RING_COLORS.items():
        radius = int(distance * scale)

        # Draw dashed circle effect using arc segments
        # Full circle for simplicity (dashed is complex in PIL)
        draw.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            outline=(*color, 150),
            width=max(1, int(2 * scale))
        )

        # Draw distance label at the right side of ring
        label = f"{distance}px"
        label_x = cx + radius + 3
        label_y = cy - 6

        # Only draw label if it's within image bounds
        if label_x < img.width - 30:
            # Draw background for label
            draw.rectangle(
                [label_x - 1, label_y - 1, label_x + 35, label_y + 12],
                fill=(0, 0, 0, 180)
            )
            draw.text((label_x, label_y), label, fill=(*color, 255), font=font)

    return img


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

    # Draw a very prominent cursor indicator (large red crosshair with circle)
    # Make it big enough to be easily visible
    cursor_size = max(30, int(40 * scale))  # Much larger
    line_width = max(4, int(5 * scale))  # Thicker lines

    # Draw multiple rings for visibility
    # Outer white ring (for contrast on dark backgrounds)
    draw.ellipse(
        [cx - cursor_size - 2, cy - cursor_size - 2, cx + cursor_size + 2, cy + cursor_size + 2],
        outline="white",
        width=line_width + 4
    )

    # Main red ring
    draw.ellipse(
        [cx - cursor_size, cy - cursor_size, cx + cursor_size, cy + cursor_size],
        outline="red",
        width=line_width
    )

    # Inner ring for extra visibility
    inner_size = cursor_size - 8
    draw.ellipse(
        [cx - inner_size, cy - inner_size, cx + inner_size, cy + inner_size],
        outline="red",
        width=max(2, line_width - 2)
    )

    # Crosshair lines extending beyond circle
    line_ext = cursor_size + 15

    # White outline for lines (for contrast)
    draw.line([(cx - line_ext, cy), (cx - cursor_size + 10, cy)], fill="white", width=line_width + 4)
    draw.line([(cx + cursor_size - 10, cy), (cx + line_ext, cy)], fill="white", width=line_width + 4)
    draw.line([(cx, cy - line_ext), (cx, cy - cursor_size + 10)], fill="white", width=line_width + 4)
    draw.line([(cx, cy + cursor_size - 10), (cx, cy + line_ext)], fill="white", width=line_width + 4)

    # Red crosshair lines
    draw.line([(cx - line_ext, cy), (cx - cursor_size + 10, cy)], fill="red", width=line_width)
    draw.line([(cx + cursor_size - 10, cy), (cx + line_ext, cy)], fill="red", width=line_width)
    draw.line([(cx, cy - line_ext), (cx, cy - cursor_size + 10)], fill="red", width=line_width)
    draw.line([(cx, cy + cursor_size - 10), (cx, cy + line_ext)], fill="red", width=line_width)

    # Large center dot with white outline
    dot_size = max(8, int(10 * scale))
    draw.ellipse(
        [cx - dot_size - 2, cy - dot_size - 2, cx + dot_size + 2, cy + dot_size + 2],
        fill="white"
    )
    draw.ellipse(
        [cx - dot_size, cy - dot_size, cx + dot_size, cy + dot_size],
        fill="red"
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
        include_cursor: bool = True,
        include_grid: bool = True,
        include_distance_rings: bool = True,
        grid_spacing: int = 200
    ) -> Image.Image:
        """
        Capture the screen or a region.

        Args:
            region: Optional (left, top, width, height) tuple for region capture
            scale: Scale factor for the output image (0.5 = half size)
            include_cursor: Whether to draw cursor indicator on screenshot
            include_grid: Whether to draw navigation grid
            include_distance_rings: Whether to draw distance rings around cursor

        Returns:
            PIL Image of the captured screen
        """
        # Get cursor position BEFORE capturing (for accuracy)
        cursor_pos = get_cursor_position() if (include_cursor or include_distance_rings) else None

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

        # Convert to PIL Image (BGRA to RGB) then to RGBA for transparency support
        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        img = img.convert("RGBA")

        # Scale if needed
        if scale != 1.0:
            new_size = (int(img.width * scale), int(img.height * scale))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        # Draw navigation aids (order matters: grid first, then rings, then cursor)
        if include_grid:
            img = draw_navigation_grid(img, grid_spacing=grid_spacing, scale=scale)

        if include_distance_rings and cursor_pos:
            img = draw_distance_rings(img, cursor_pos, scale)

        # Draw cursor indicator on top
        if include_cursor and cursor_pos:
            img = draw_cursor_on_image(img, cursor_pos, scale)

        # Convert back to RGB for saving
        img = img.convert("RGB")

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
