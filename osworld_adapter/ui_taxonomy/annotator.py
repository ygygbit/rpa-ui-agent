"""
Screenshot Annotator — draws bounding boxes with numbered labels on screenshots.

Uses PIL (Pillow) only, no OpenCV dependency.
Produces Set-of-Marks (SoM) style annotations where each detected element
gets a numbered bounding box overlay on the screenshot.
"""

import base64
import io
import logging
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from .detector import UIElement

logger = logging.getLogger("desktopenv.ui_taxonomy.annotator")

# Color palette for element types
TYPE_COLORS = {
    "button": (66, 133, 244, 180),       # Blue
    "icon": (234, 67, 53, 180),           # Red
    "menu_item": (251, 188, 4, 180),      # Yellow
    "text_field": (52, 168, 83, 180),     # Green
    "dropdown": (52, 168, 83, 180),       # Green
    "toolbar": (150, 150, 150, 120),      # Gray
    "tab": (171, 71, 188, 180),           # Purple
    "checkbox": (0, 172, 193, 180),       # Teal
    "link": (66, 133, 244, 180),          # Blue
    "label": (158, 158, 158, 100),        # Light gray
    "panel": (120, 120, 120, 80),         # Dark gray
    "dialog": (120, 120, 120, 100),       # Dark gray
    "slider": (255, 152, 0, 180),         # Orange
    "scrollbar": (158, 158, 158, 100),    # Light gray
}

DEFAULT_COLOR = (100, 100, 100, 150)

# Label background colors (opaque for readability)
LABEL_BG_COLOR = (0, 0, 0, 200)     # Dark background
LABEL_TEXT_COLOR = (255, 255, 255)    # White text


class ScreenshotAnnotator:
    """Draws element bounding boxes and IDs on screenshots."""

    def __init__(self, max_elements: int = 20, border_width: int = 2):
        self.max_elements = max_elements
        self.border_width = border_width
        self._font = None

    def _get_font(self, size: int = 12) -> ImageFont.FreeTypeFont:
        """Get a font for labels, falling back to default if needed."""
        if self._font is None:
            try:
                self._font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
            except (OSError, IOError):
                try:
                    self._font = ImageFont.truetype("arial.ttf", size)
                except (OSError, IOError):
                    self._font = ImageFont.load_default()
        return self._font

    def annotate(self, img_b64: str, elements: List[UIElement],
                 media_type: str = "image/png") -> str:
        """
        Draw numbered bounding boxes on screenshot.

        Args:
            img_b64: Base64-encoded screenshot
            elements: List of detected UIElements
            media_type: Image media type

        Returns:
            Base64-encoded annotated screenshot (PNG)
        """
        if not elements:
            return img_b64

        try:
            # Decode image
            img_bytes = base64.standard_b64decode(img_b64)
            img = Image.open(io.BytesIO(img_bytes))
            if img.mode != "RGBA":
                img = img.convert("RGBA")

            # Create overlay for semi-transparent drawing
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            font = self._get_font()

            # Sort elements: interactive first, then by visual importance
            sorted_elems = sorted(
                elements,
                key=lambda e: (not e.interactive, -self._importance_score(e))
            )[:self.max_elements]

            for elem in sorted_elems:
                self._draw_element(draw, elem, font)

            # Composite overlay onto image
            img = Image.alpha_composite(img, overlay)
            img = img.convert("RGB")

            # Re-encode as PNG
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            annotated_b64 = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")

            logger.info(f"Annotated screenshot with {len(sorted_elems)} elements")
            return annotated_b64

        except Exception as e:
            logger.error(f"Annotation failed: {e}", exc_info=True)
            return img_b64  # Return original on failure

    def _draw_element(self, draw: ImageDraw.Draw, elem: UIElement,
                      font: ImageFont.FreeTypeFont):
        """Draw a single element's bounding box and label."""
        x1, y1, x2, y2 = elem.bbox
        color = TYPE_COLORS.get(elem.element_type, DEFAULT_COLOR)

        # Draw bounding box
        for i in range(self.border_width):
            draw.rectangle(
                [x1 - i, y1 - i, x2 + i, y2 + i],
                outline=color
            )

        # Draw label tag at top-left corner
        label_text = f"[{elem.element_id}]"
        bbox = font.getbbox(label_text)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        padding = 2

        label_x = x1
        label_y = max(0, y1 - text_h - padding * 2 - 2)

        # Label background
        draw.rectangle(
            [label_x, label_y, label_x + text_w + padding * 2, label_y + text_h + padding * 2],
            fill=LABEL_BG_COLOR
        )

        # Label text
        draw.text(
            (label_x + padding, label_y + padding),
            label_text,
            fill=LABEL_TEXT_COLOR + (255,),
            font=font
        )

    def _importance_score(self, elem: UIElement) -> float:
        """Score element importance for annotation priority."""
        score = 0.0
        if elem.interactive:
            score += 10.0
        if elem.label:
            score += 5.0
        if elem.element_type in ("button", "icon", "menu_item", "text_field"):
            score += 3.0
        if elem.prototype_match:
            score += elem.prototype_match[1] * 5.0
        # Penalize very large elements (likely panels/containers)
        bbox_area = (elem.bbox[2] - elem.bbox[0]) * (elem.bbox[3] - elem.bbox[1])
        if bbox_area > 200000:  # Large area
            score -= 5.0
        return score
