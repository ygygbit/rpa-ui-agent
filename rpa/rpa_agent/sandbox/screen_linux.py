"""
Linux/Xvfb Screen Capture Module

This module provides screen capture functionality for Linux environments,
specifically designed for use with Xvfb virtual framebuffer in Docker.
"""

import os
import io
from typing import Optional, Tuple
from PIL import Image

# Only import Linux-specific modules when on Linux
import sys
if sys.platform == 'linux':
    try:
        import mss
        import pyscreenshot
        from Xlib import display as xlib_display
        from Xlib import X
        HAS_XLIB = True
    except ImportError:
        HAS_XLIB = False
else:
    HAS_XLIB = False


class LinuxScreenCapture:
    """Screen capture for Linux/Xvfb environments."""

    def __init__(self, display: Optional[str] = None):
        """
        Initialize screen capture.

        Args:
            display: X11 display string (e.g., ':99'). If None, uses DISPLAY env var.
        """
        self.display_str = display or os.environ.get('DISPLAY', ':99')
        self._mss = None
        self._xlib_display = None

    @property
    def screen_size(self) -> Tuple[int, int]:
        """Get screen dimensions (width, height)."""
        if HAS_XLIB:
            try:
                d = xlib_display.Display(self.display_str)
                screen = d.screen()
                return (screen.width_in_pixels, screen.height_in_pixels)
            except Exception:
                pass

        # Fallback: try mss
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[0]  # Primary monitor
                return (monitor['width'], monitor['height'])
        except Exception:
            pass

        # Default to 1080p
        return (1920, 1080)

    def capture(
        self,
        region: Optional[Tuple[int, int, int, int]] = None,
        scale: float = 1.0,
        quality: int = 85
    ) -> Image.Image:
        """
        Capture the screen or a region of it.

        Args:
            region: Optional (left, top, width, height) tuple for partial capture.
            scale: Scale factor (1.0 = original size, 0.5 = half size).
            quality: JPEG quality (not used for PNG, kept for API compatibility).

        Returns:
            PIL Image of the captured screen.
        """
        # Try mss first (fastest)
        try:
            return self._capture_mss(region, scale)
        except Exception as e:
            print(f"mss capture failed: {e}")

        # Fallback to pyscreenshot
        try:
            return self._capture_pyscreenshot(region, scale)
        except Exception as e:
            print(f"pyscreenshot capture failed: {e}")

        # Last resort: scrot command
        return self._capture_scrot(region, scale)

    def _capture_mss(
        self,
        region: Optional[Tuple[int, int, int, int]],
        scale: float
    ) -> Image.Image:
        """Capture using mss library."""
        with mss.mss() as sct:
            if region:
                left, top, width, height = region
                monitor = {
                    'left': left,
                    'top': top,
                    'width': width,
                    'height': height
                }
            else:
                monitor = sct.monitors[0]  # Full screen

            screenshot = sct.grab(monitor)
            img = Image.frombytes('RGB', screenshot.size, screenshot.bgra, 'raw', 'BGRX')

            if scale != 1.0:
                new_size = (int(img.width * scale), int(img.height * scale))
                img = img.resize(new_size, Image.Resampling.LANCZOS)

            return img

    def _capture_pyscreenshot(
        self,
        region: Optional[Tuple[int, int, int, int]],
        scale: float
    ) -> Image.Image:
        """Capture using pyscreenshot library."""
        if region:
            left, top, width, height = region
            bbox = (left, top, left + width, top + height)
            img = pyscreenshot.grab(bbox=bbox)
        else:
            img = pyscreenshot.grab()

        if scale != 1.0:
            new_size = (int(img.width * scale), int(img.height * scale))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        return img

    def _capture_scrot(
        self,
        region: Optional[Tuple[int, int, int, int]],
        scale: float
    ) -> Image.Image:
        """Capture using scrot command (last resort)."""
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            temp_path = f.name

        try:
            env = os.environ.copy()
            env['DISPLAY'] = self.display_str

            subprocess.run(
                ['scrot', '-o', temp_path],
                env=env,
                check=True,
                capture_output=True
            )

            img = Image.open(temp_path)
            img.load()  # Force load before deleting file

            if region:
                left, top, width, height = region
                img = img.crop((left, top, left + width, top + height))

            if scale != 1.0:
                new_size = (int(img.width * scale), int(img.height * scale))
                img = img.resize(new_size, Image.Resampling.LANCZOS)

            return img
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def get_cursor_position(self) -> Tuple[int, int]:
        """Get current mouse cursor position."""
        if HAS_XLIB:
            try:
                d = xlib_display.Display(self.display_str)
                root = d.screen().root
                pointer = root.query_pointer()
                return (pointer.root_x, pointer.root_y)
            except Exception:
                pass

        # Fallback: try xdotool
        try:
            import subprocess
            env = os.environ.copy()
            env['DISPLAY'] = self.display_str
            result = subprocess.run(
                ['xdotool', 'getmouselocation', '--shell'],
                env=env,
                capture_output=True,
                text=True,
                check=True
            )
            # Parse output like "X=123\nY=456\n..."
            coords = {}
            for line in result.stdout.strip().split('\n'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    coords[key] = int(value)
            return (coords.get('X', 0), coords.get('Y', 0))
        except Exception:
            return (0, 0)

    def capture_with_cursor(
        self,
        scale: float = 1.0,
        quality: int = 85,
        draw_crosshair: bool = True
    ) -> Image.Image:
        """
        Capture screen with cursor indicator overlay.

        Args:
            scale: Scale factor for the image.
            quality: JPEG quality (for compatibility).
            draw_crosshair: Whether to draw a crosshair at cursor position.

        Returns:
            PIL Image with cursor indicator.
        """
        img = self.capture(scale=scale, quality=quality)

        if not draw_crosshair:
            return img

        cursor_x, cursor_y = self.get_cursor_position()

        # Scale cursor position if image is scaled
        cursor_x = int(cursor_x * scale)
        cursor_y = int(cursor_y * scale)

        # Draw crosshair
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)

        # Red crosshair with white outline
        size = 20
        thickness = 2

        # White outline
        for offset in [-1, 0, 1]:
            draw.line(
                [(cursor_x - size + offset, cursor_y), (cursor_x + size + offset, cursor_y)],
                fill='white', width=thickness + 2
            )
            draw.line(
                [(cursor_x, cursor_y - size + offset), (cursor_x, cursor_y + size + offset)],
                fill='white', width=thickness + 2
            )

        # Red lines
        draw.line(
            [(cursor_x - size, cursor_y), (cursor_x + size, cursor_y)],
            fill='red', width=thickness
        )
        draw.line(
            [(cursor_x, cursor_y - size), (cursor_x, cursor_y + size)],
            fill='red', width=thickness
        )

        # Center dot
        draw.ellipse(
            [(cursor_x - 3, cursor_y - 3), (cursor_x + 3, cursor_y + 3)],
            fill='red', outline='white'
        )

        return img


# Singleton instance for easy access
_screen_capture: Optional[LinuxScreenCapture] = None


def get_screen_capture() -> LinuxScreenCapture:
    """Get or create the screen capture singleton."""
    global _screen_capture
    if _screen_capture is None:
        _screen_capture = LinuxScreenCapture()
    return _screen_capture
