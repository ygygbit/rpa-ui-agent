"""
Screen capture module with Windows GDI support for RDP compatibility.
Includes mouse cursor overlay and navigation aids for human-like navigation.

Supports two capture methods:
1. Windows GDI (default) - Works reliably over RDP/Remote Desktop
2. mss library (fallback) - Fast cross-platform capture for local sessions
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


# Windows API handles
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

# GDI constants
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0

# Enable Per-Monitor DPI awareness for accurate screen capture coordinates
# This MUST be called before any capture to get physical pixel coordinates
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    # Fall back to system DPI aware if per-monitor fails
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


class BITMAPINFOHEADER(ctypes.Structure):
    """Windows BITMAPINFOHEADER structure for GDI capture."""
    _fields_ = [
        ('biSize', ctypes.c_uint32),
        ('biWidth', ctypes.c_int32),
        ('biHeight', ctypes.c_int32),
        ('biPlanes', ctypes.c_uint16),
        ('biBitCount', ctypes.c_uint16),
        ('biCompression', ctypes.c_uint32),
        ('biSizeImage', ctypes.c_uint32),
        ('biXPelsPerMeter', ctypes.c_int32),
        ('biYPelsPerMeter', ctypes.c_int32),
        ('biClrUsed', ctypes.c_uint32),
        ('biClrImportant', ctypes.c_uint32),
    ]


class BITMAPINFO(ctypes.Structure):
    """Windows BITMAPINFO structure for GDI capture."""
    _fields_ = [
        ('bmiHeader', BITMAPINFOHEADER),
        ('bmiColors', ctypes.c_uint32 * 3),
    ]


def capture_screen_gdi(region: Optional[Tuple[int, int, int, int]] = None) -> Optional[Image.Image]:
    """
    Capture the screen using Windows GDI.

    This method works reliably over RDP/Remote Desktop sessions.

    Args:
        region: Optional (left, top, width, height) tuple for region capture.
                If None, captures the entire primary monitor.

    Returns:
        PIL Image of the captured screen, or None if capture fails.
    """
    try:
        # Get screen dimensions
        if region:
            left, top, width, height = region
        else:
            left = 0
            top = 0
            width = user32.GetSystemMetrics(0)  # SM_CXSCREEN
            height = user32.GetSystemMetrics(1)  # SM_CYSCREEN

        # Get device context for the entire screen
        hdesktop = user32.GetDesktopWindow()
        desktop_dc = user32.GetWindowDC(hdesktop)

        if not desktop_dc:
            return None

        # Create a compatible DC and bitmap
        compatible_dc = gdi32.CreateCompatibleDC(desktop_dc)
        if not compatible_dc:
            user32.ReleaseDC(hdesktop, desktop_dc)
            return None

        bitmap = gdi32.CreateCompatibleBitmap(desktop_dc, width, height)
        if not bitmap:
            gdi32.DeleteDC(compatible_dc)
            user32.ReleaseDC(hdesktop, desktop_dc)
            return None

        # Select the bitmap into the compatible DC
        old_bitmap = gdi32.SelectObject(compatible_dc, bitmap)

        # Copy screen content to our bitmap
        gdi32.BitBlt(
            compatible_dc, 0, 0, width, height,
            desktop_dc, left, top,
            SRCCOPY
        )

        # Set up BITMAPINFO structure
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height  # Negative for top-down DIB
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        bmi.bmiHeader.biSizeImage = width * height * 4

        # Create buffer for pixel data
        buffer = ctypes.create_string_buffer(width * height * 4)

        # Get the bitmap bits
        gdi32.GetDIBits(
            compatible_dc, bitmap, 0, height,
            buffer, ctypes.byref(bmi), DIB_RGB_COLORS
        )

        # Clean up GDI objects
        gdi32.SelectObject(compatible_dc, old_bitmap)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(compatible_dc)
        user32.ReleaseDC(hdesktop, desktop_dc)

        # Convert to PIL Image (BGRA format)
        img = Image.frombuffer('RGBA', (width, height), buffer, 'raw', 'BGRA', 0, 1)

        # Convert to RGB (drop alpha)
        img = img.convert('RGB')

        return img

    except Exception as e:
        print(f"GDI capture failed: {e}")
        return None

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
    Draw a minimal radial coordinate overlay centered on the cursor position.

    This creates a simple polar coordinate system with:
    - Distance rings at 50, 100, 150, 200, 300 pixels from cursor (semi-transparent)
    - Distance labels ONLY on the right side of each ring (to minimize clutter)
    - NO direction arrows or labels (the cursor crosshair already shows position)

    Args:
        img: PIL Image to draw on (already captured screenshot)
        cursor_pos: (x, y) position of cursor on screen
        scale: Scale factor (for label sizing)

    Returns:
        Image with radial overlay (same dimensions as input)
    """
    # Work on a copy with alpha
    img = img.copy()
    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    draw = ImageDraw.Draw(img, 'RGBA')

    cx, cy = int(cursor_pos[0] * scale), int(cursor_pos[1] * scale)

    # Load fonts
    try:
        small_font = ImageFont.truetype("arial.ttf", 10)
    except:
        small_font = ImageFont.load_default()

    # Draw distance rings centered on cursor - VERY transparent to not obscure content
    for distance, color in sorted(RING_COLORS.items()):
        radius = int(distance * scale)

        # Draw the ring with low opacity (just visible enough to estimate distance)
        draw.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            outline=(*color, 80),  # Very low opacity (was 180)
            width=1  # Thin line (was 2)
        )

        # Draw distance label ONLY on the right side of each ring
        label_x = cx + radius + 3
        label_y = cy - 6

        label = f"{distance}"
        bbox = draw.textbbox((0, 0), label, font=small_font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]

        # Check bounds - only draw if within image
        if label_x < img.width - w - 5:
            # Small semi-transparent background
            draw.rectangle(
                [label_x - 1, label_y - 1, label_x + w + 1, label_y + h + 1],
                fill=(0, 0, 0, 120)
            )
            draw.text((label_x, label_y), label, fill=(*color, 200), font=small_font)

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


def draw_coordinate_display(img: Image.Image, cursor_pos: Tuple[int, int], screen_size: Tuple[int, int], scale: float = 1.0) -> Image.Image:
    """
    Draw a coordinate display panel showing cursor position and screen info.

    This provides explicit coordinate information to help VLM calculate offsets.

    Args:
        img: PIL Image to draw on
        cursor_pos: (x, y) position of cursor on screen (original, unscaled)
        screen_size: (width, height) of screen
        scale: Scale factor applied to the image

    Returns:
        Image with coordinate display overlay
    """
    img = img.copy()
    draw = ImageDraw.Draw(img, 'RGBA')

    # Try to load a readable font
    try:
        font = ImageFont.truetype("arial.ttf", 14)
        small_font = ImageFont.truetype("arial.ttf", 11)
    except:
        font = ImageFont.load_default()
        small_font = font

    # Position the display in top-left corner
    panel_x = 10
    panel_y = 10
    panel_width = 200
    panel_height = 60

    # Draw semi-transparent background
    draw.rectangle(
        [panel_x, panel_y, panel_x + panel_width, panel_y + panel_height],
        fill=(0, 0, 0, 200)
    )
    draw.rectangle(
        [panel_x, panel_y, panel_x + panel_width, panel_y + panel_height],
        outline=(100, 100, 100, 255),
        width=1
    )

    # Draw cursor coordinates
    cursor_text = f"CURSOR: ({cursor_pos[0]}, {cursor_pos[1]})"
    draw.text((panel_x + 10, panel_y + 8), cursor_text, fill=(0, 255, 0, 255), font=font)

    # Draw screen size
    screen_text = f"Screen: {screen_size[0]} x {screen_size[1]}"
    draw.text((panel_x + 10, panel_y + 30), screen_text, fill=(200, 200, 200, 255), font=small_font)

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
    Screen capture with Windows GDI support for RDP compatibility.

    Supports:
    - Windows GDI capture (default) - Works over RDP/Remote Desktop
    - mss library capture (fallback) - Fast cross-platform capture
    - Full screen capture
    - Region capture
    - Multi-monitor support
    - Base64 encoding for VLM API
    """

    def __init__(self, monitor_index: int = 1, use_gdi: bool = True):
        """
        Initialize screen capture.

        Args:
            monitor_index: Monitor to capture (0 = all monitors, 1 = primary, 2+ = secondary)
            use_gdi: If True, use Windows GDI capture (works over RDP). If False, use mss.
        """
        self.monitor_index = monitor_index
        self.use_gdi = use_gdi
        self._sct = mss.mss()

    @property
    def monitors(self) -> list:
        """Get list of available monitors."""
        return self._sct.monitors

    @property
    def screen_size(self) -> Tuple[int, int]:
        """Get the size of the current monitor."""
        if self.use_gdi:
            width = user32.GetSystemMetrics(0)  # SM_CXSCREEN
            height = user32.GetSystemMetrics(1)  # SM_CYSCREEN
            return width, height
        else:
            mon = self._sct.monitors[self.monitor_index]
            return mon["width"], mon["height"]

    def _capture_with_gdi(self, region: Optional[Tuple[int, int, int, int]] = None) -> Optional[Image.Image]:
        """Capture screen using Windows GDI (RDP-compatible)."""
        return capture_screen_gdi(region)

    def _capture_with_mss(self, region: Optional[Tuple[int, int, int, int]] = None) -> Image.Image:
        """Capture screen using mss library (fast, cross-platform)."""
        if region:
            monitor = {
                "left": region[0],
                "top": region[1],
                "width": region[2],
                "height": region[3]
            }
        else:
            monitor = self._sct.monitors[self.monitor_index]

        sct_img = self._sct.grab(monitor)
        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        return img

    def capture(
        self,
        region: Optional[Tuple[int, int, int, int]] = None,
        scale: float = 1.0,
        include_cursor: bool = True,
        include_radial_overlay: bool = True,
        include_coordinate_display: bool = False,
        grid_spacing: int = 50  # Unused, kept for compatibility
    ) -> Image.Image:
        """
        Capture the screen or a region with radial coordinate overlay.

        Uses Windows GDI by default (works over RDP), falls back to mss if GDI fails.

        Args:
            region: Optional (left, top, width, height) tuple for region capture
            scale: Scale factor for the output image (0.5 = half size)
            include_cursor: Whether to draw cursor indicator on screenshot
            include_radial_overlay: Whether to draw radial distance rings and direction indicators
            include_coordinate_display: Whether to show cursor coordinates numerically on screen

        Returns:
            PIL Image of the captured screen (NO margins added - same size as screen)
        """
        # Get cursor position BEFORE capturing (for accuracy)
        cursor_pos = get_cursor_position() if (include_cursor or include_radial_overlay or include_coordinate_display) else None
        screen_size = self.screen_size

        # Try GDI capture first (works over RDP), fall back to mss
        img = None
        if self.use_gdi:
            img = self._capture_with_gdi(region)

        if img is None:
            # Fallback to mss
            img = self._capture_with_mss(region)

        # Convert to RGBA for transparency support
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

        # Draw coordinate display panel
        if include_coordinate_display and cursor_pos:
            img = draw_coordinate_display(img, cursor_pos, screen_size, scale)

        # Convert back to RGB for saving
        img = img.convert("RGB")

        return img

    def capture_with_overlay(
        self,
        scale: float = 1.0,
        include_coordinates: bool = True
    ) -> Image.Image:
        """
        Capture screen with full overlay including coordinate display.

        This is the recommended method for VLM-guided automation as it
        provides explicit coordinate information.

        Args:
            scale: Scale factor for the output image
            include_coordinates: Whether to show cursor coordinates numerically

        Returns:
            PIL Image with cursor, radial overlay, and coordinate display
        """
        return self.capture(
            scale=scale,
            include_cursor=True,
            include_radial_overlay=True,
            include_coordinate_display=include_coordinates
        )

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
