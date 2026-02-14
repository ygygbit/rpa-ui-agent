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

# Enable Per-Monitor DPI awareness for accurate screen capture coordinates
# This MUST be called before any mss capture to get physical pixel coordinates
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    # Fall back to system DPI aware if per-monitor fails
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

# Colors for navigation aids
CURSOR_COLOR = (255, 0, 0)  # Red for cursor indicator
RING_COLORS = {
    50: (0, 255, 255),     # Cyan for 50px
    100: (255, 255, 0),    # Yellow for 100px
    150: (255, 165, 0),    # Orange for 150px
    200: (255, 100, 100),  # Light red for 200px
    300: (200, 100, 255),  # Purple for 300px
}
# Cardinal direction colors
DIRECTION_COLORS = {
    "up": (0, 255, 0),      # Green
    "down": (255, 0, 255),  # Magenta
    "left": (255, 255, 0),  # Yellow
    "right": (0, 255, 255), # Cyan
}


def get_cursor_position() -> Tuple[int, int]:
    """Get current mouse cursor position using Windows API."""
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def draw_radial_overlay(img: Image.Image, cursor_pos: Tuple[int, int], scale: float = 1.0) -> Image.Image:
    """
    Draw a radial coordinate overlay centered on the cursor position.

    This creates a polar coordinate system with:
    - Distance rings at 50, 100, 150, 200, 300 pixels from cursor
    - Cardinal direction indicators (up, down, left, right) with arrows
    - Distance labels on rings
    - NO axis margins - coordinates are relative to cursor

    Args:
        img: PIL Image to draw on (already captured screenshot)
        cursor_pos: (x, y) position of cursor on screen
        scale: Scale factor (for label sizing)

    Returns:
        Image with radial overlay (same dimensions as input)
    """
    import math

    # Work on a copy with alpha
    img = img.copy()
    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    draw = ImageDraw.Draw(img, 'RGBA')

    cx, cy = int(cursor_pos[0] * scale), int(cursor_pos[1] * scale)

    # Load fonts
    try:
        font = ImageFont.truetype("arial.ttf", 14)
        small_font = ImageFont.truetype("arial.ttf", 11)
    except:
        font = ImageFont.load_default()
        small_font = font

    # Draw distance rings centered on cursor
    for distance, color in sorted(RING_COLORS.items()):
        radius = int(distance * scale)

        # Draw the ring
        draw.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            outline=(*color, 180),
            width=2
        )

        # Draw distance label at multiple positions around the ring
        # Place labels at 45-degree intervals on the ring
        for angle_deg in [45, 135, 225, 315]:
            angle_rad = math.radians(angle_deg)
            label_x = cx + int(radius * math.cos(angle_rad))
            label_y = cy + int(radius * math.sin(angle_rad))

            label = f"{distance}px"
            bbox = draw.textbbox((0, 0), label, font=small_font)
            w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]

            # Check bounds
            if 0 <= label_x - w//2 < img.width - w and 0 <= label_y - h//2 < img.height - h:
                # Draw background for readability
                draw.rectangle(
                    [label_x - w//2 - 2, label_y - h//2 - 1,
                     label_x + w//2 + 2, label_y + h//2 + 1],
                    fill=(0, 0, 0, 200)
                )
                draw.text((label_x - w//2, label_y - h//2), label, fill=(*color, 255), font=small_font)

    # Draw cardinal direction indicators with arrows
    arrow_len = 30
    for direction, (dx, dy) in [("up", (0, -1)), ("down", (0, 1)),
                                 ("left", (-1, 0)), ("right", (1, 0))]:
        color = DIRECTION_COLORS[direction]

        # Calculate arrow start (at 300px ring) and direction
        start_dist = 320  # Just outside the largest ring
        end_dist = start_dist + arrow_len

        start_x = cx + int(dx * start_dist)
        start_y = cy + int(dy * start_dist)
        end_x = cx + int(dx * end_dist)
        end_y = cy + int(dy * end_dist)

        # Check if arrow is within bounds
        if (0 <= end_x < img.width and 0 <= end_y < img.height):
            # Draw arrow line
            draw.line([(start_x, start_y), (end_x, end_y)], fill=(*color, 220), width=3)

            # Draw arrowhead
            head_size = 8
            if direction == "up":
                draw.polygon([(end_x, end_y), (end_x - head_size, end_y + head_size),
                              (end_x + head_size, end_y + head_size)], fill=(*color, 220))
            elif direction == "down":
                draw.polygon([(end_x, end_y), (end_x - head_size, end_y - head_size),
                              (end_x + head_size, end_y - head_size)], fill=(*color, 220))
            elif direction == "left":
                draw.polygon([(end_x, end_y), (end_x + head_size, end_y - head_size),
                              (end_x + head_size, end_y + head_size)], fill=(*color, 220))
            elif direction == "right":
                draw.polygon([(end_x, end_y), (end_x - head_size, end_y - head_size),
                              (end_x - head_size, end_y + head_size)], fill=(*color, 220))

            # Draw direction label
            label_x = cx + int(dx * (end_dist + 25))
            label_y = cy + int(dy * (end_dist + 25))
            label = direction.upper()

            bbox = draw.textbbox((0, 0), label, font=font)
            w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]

            if 0 <= label_x - w//2 < img.width - w and 0 <= label_y - h//2 < img.height - h:
                draw.rectangle(
                    [label_x - w//2 - 2, label_y - h//2 - 1,
                     label_x + w//2 + 2, label_y + h//2 + 1],
                    fill=(0, 0, 0, 200)
                )
                draw.text((label_x - w//2, label_y - h//2), label, fill=(*color, 255), font=font)

    # Draw diagonal direction indicators (smaller)
    for direction, (dx, dy) in [("up-left", (-0.707, -0.707)), ("up-right", (0.707, -0.707)),
                                 ("down-left", (-0.707, 0.707)), ("down-right", (0.707, 0.707))]:
        start_dist = 320
        label_dist = 350

        label_x = cx + int(dx * label_dist)
        label_y = cy + int(dy * label_dist)

        # Abbreviated labels for diagonals
        abbrev = {"up-left": "UL", "up-right": "UR", "down-left": "DL", "down-right": "DR"}
        label = abbrev[direction]

        bbox = draw.textbbox((0, 0), label, font=small_font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]

        if 0 <= label_x - w//2 < img.width - w and 0 <= label_y - h//2 < img.height - h:
            draw.rectangle(
                [label_x - w//2 - 2, label_y - h//2 - 1,
                 label_x + w//2 + 2, label_y + h//2 + 1],
                fill=(0, 0, 0, 180)
            )
            draw.text((label_x - w//2, label_y - h//2), label, fill=(200, 200, 200, 255), font=small_font)

    return img


def draw_distance_rings(img: Image.Image, cursor_pos: Tuple[int, int], scale: float = 1.0, margin: int = 0) -> Image.Image:
    """
    Draw distance rings around the cursor position.

    Args:
        img: PIL Image to draw on
        cursor_pos: (x, y) position of cursor on screen (before scaling)
        scale: Scale factor applied to the image
        margin: Offset for axis margin (added to cursor position)

    Returns:
        Image with distance rings
    """
    draw = ImageDraw.Draw(img, 'RGBA')

    # Scale cursor position and add margin offset
    cx = int(cursor_pos[0] * scale) + margin
    cy = int(cursor_pos[1] * scale) + margin

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


def draw_cursor_on_image(img: Image.Image, cursor_pos: Tuple[int, int], scale: float = 1.0, margin: int = 0) -> Image.Image:
    """
    Draw a visible cursor indicator on the screenshot.

    Args:
        img: PIL Image to draw on
        cursor_pos: (x, y) position of cursor on screen
        scale: Scale factor applied to the image
        margin: Offset for axis margin (added to cursor position)

    Returns:
        Image with cursor overlay
    """
    # Scale cursor position if image was scaled, and add margin offset
    cx = int(cursor_pos[0] * scale) + margin
    cy = int(cursor_pos[1] * scale) + margin

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
        include_radial_overlay: bool = True,
        grid_spacing: int = 50  # Unused, kept for compatibility
    ) -> Image.Image:
        """
        Capture the screen or a region with radial coordinate overlay.

        Args:
            region: Optional (left, top, width, height) tuple for region capture
            scale: Scale factor for the output image (0.5 = half size)
            include_cursor: Whether to draw cursor indicator on screenshot
            include_radial_overlay: Whether to draw radial distance rings and direction indicators

        Returns:
            PIL Image of the captured screen (NO margins added - same size as screen)
        """
        # Get cursor position BEFORE capturing (for accuracy)
        cursor_pos = get_cursor_position() if (include_cursor or include_radial_overlay) else None

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

        # Draw radial overlay centered on cursor (includes distance rings and direction indicators)
        if include_radial_overlay and cursor_pos:
            img = draw_radial_overlay(img, cursor_pos, scale)

        # Draw cursor indicator on top
        if include_cursor and cursor_pos:
            img = draw_cursor_on_image(img, cursor_pos, scale, margin=0)

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
