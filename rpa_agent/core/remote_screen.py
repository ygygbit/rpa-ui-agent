"""
Remote Screen Capture for sandbox API.

Fetches screenshots from the sandbox server via HTTP instead of
capturing the local Windows screen.
"""

import io
import httpx
from typing import Optional, Tuple
from PIL import Image


class RemoteScreenCapture:
    """
    Screen capture that fetches from sandbox API.

    Has the same interface as ScreenCapture but uses HTTP to get
    screenshots from the Docker sandbox.
    """

    def __init__(self, base_url: str = "http://localhost:8000"):
        """
        Initialize remote screen capture.

        Args:
            base_url: Base URL of the sandbox API server.
        """
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=30.0)
        self._screen_size: Optional[Tuple[int, int]] = None

    def _get(self, endpoint: str, **kwargs) -> httpx.Response:
        """Make GET request to sandbox API."""
        return self._client.get(f"{self.base_url}{endpoint}", **kwargs)

    @property
    def screen_size(self) -> Tuple[int, int]:
        """Get screen dimensions from sandbox."""
        if self._screen_size is None:
            response = self._get("/status")
            if response.status_code == 200:
                data = response.json()
                self._screen_size = (
                    data["screen_size"]["width"],
                    data["screen_size"]["height"]
                )
            else:
                self._screen_size = (1920, 1080)
        return self._screen_size

    def capture(
        self,
        region: Optional[Tuple[int, int, int, int]] = None,
        scale: float = 1.0,
        quality: int = 85
    ) -> Image.Image:
        """
        Capture screenshot from sandbox.

        Args:
            region: Optional (left, top, width, height) - not supported remotely.
            scale: Scale factor for the image.
            quality: Not used (sandbox returns PNG).

        Returns:
            PIL Image of the captured screen.
        """
        response = self._get(
            "/screenshot",
            params={"scale": scale, "draw_cursor": True}
        )

        if response.status_code != 200:
            raise RuntimeError(f"Failed to capture screenshot: {response.status_code}")

        img = Image.open(io.BytesIO(response.content))

        # Crop if region specified
        if region:
            left, top, width, height = region
            img = img.crop((left, top, left + width, top + height))

        return img

    def capture_with_cursor(
        self,
        scale: float = 1.0,
        quality: int = 85
    ) -> Image.Image:
        """Capture screenshot with cursor indicator."""
        return self.capture(scale=scale, quality=quality)

    def get_cursor_position(self) -> Tuple[int, int]:
        """Get current cursor position from sandbox."""
        response = self._get("/status")
        if response.status_code == 200:
            data = response.json()
            return (
                data["cursor_position"]["x"],
                data["cursor_position"]["y"]
            )
        return (0, 0)

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()
