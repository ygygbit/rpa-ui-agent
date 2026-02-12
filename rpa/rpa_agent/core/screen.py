"""
Screen capture module using mss for fast, cross-platform screenshots.
"""

import base64
import io
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import mss
from PIL import Image


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
        scale: float = 1.0
    ) -> Image.Image:
        """
        Capture the screen or a region.

        Args:
            region: Optional (left, top, width, height) tuple for region capture
            scale: Scale factor for the output image (0.5 = half size)

        Returns:
            PIL Image of the captured screen
        """
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

        return img

    def capture_to_base64(
        self,
        region: Optional[Tuple[int, int, int, int]] = None,
        scale: float = 1.0,
        format: str = "PNG",
        quality: int = 85
    ) -> Tuple[str, ScreenInfo]:
        """
        Capture screen and encode as base64 for VLM API.

        Args:
            region: Optional region to capture
            scale: Scale factor
            format: Image format (PNG or JPEG)
            quality: JPEG quality (1-100)

        Returns:
            Tuple of (base64 encoded string, ScreenInfo)
        """
        img = self.capture(region, scale)

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
