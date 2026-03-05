"""
VLM-based UI Element Detector.

Sends a screenshot to the VLM with a specialized prompt that asks it to
identify all interactive UI elements with bounding boxes, types, labels,
and parent-child relationships.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("rpa_agent.ui_taxonomy.detector")


ELEMENT_DETECTION_PROMPT = (
    "List all interactive UI elements visible in this screenshot.\n\n"
    "Return a JSON array. Each element:\n"
    "{\n"
    '  "id": 1,\n'
    '  "type": "button",\n'
    '  "label": "Save",\n'
    '  "bbox": [100, 200, 180, 230],\n'
    '  "parent_id": null,\n'
    '  "visual": "blue rectangular button with white text",\n'
    '  "interactive": true\n'
    "}\n\n"
    "Types: button, icon, menu_item, text_field, dropdown, toolbar, "
    "tab, checkbox, link, label, panel, dialog, slider, scrollbar\n\n"
    "IMPORTANT rules for parent_id:\n"
    "- A menu item inside a menu bar: parent_id = the menu bar element's id\n"
    "- A button inside a toolbar: parent_id = the toolbar element's id\n"
    "- A tab inside a tab bar: parent_id = the tab bar element's id\n"
    "- A field inside a dialog/form: parent_id = the dialog/form element's id\n"
    "- Only top-level containers (menu bars, toolbars, panels) should have parent_id: null\n\n"
    "Rules:\n"
    "- bbox is [x1, y1, x2, y2] in pixel coordinates\n"
    "- Focus on INTERACTIVE elements (clickable, editable, togglable)\n"
    "- Include containers (toolbar, panel) that hold interactive children\n"
    "- Limit to 20 most important elements\n"
    "- Return ONLY the JSON array"
)


@dataclass
class UIElement:
    """A detected UI element on screen."""
    element_id: int
    bbox: Tuple[int, int, int, int]  # (x1, y1, x2, y2)
    center: Tuple[int, int]
    element_type: str
    label: str
    confidence: float = 0.5
    visual_description: str = ""
    interactive: bool = True
    parent_id: Optional[int] = None
    children_ids: List[int] = field(default_factory=list)
    sibling_ids: List[int] = field(default_factory=list)
    prototype_match: Optional[Tuple[str, float]] = None  # (prototype_name, score)


class VLMElementDetector:
    """
    Detects UI elements by sending a screenshot to the VLM with a
    specialized element-detection prompt.
    """

    def __init__(self, vlm_client, vlm_model: str = "claude-opus-4.6-1m",
                 max_tokens: int = 4096, temperature: float = 0.1):
        self.client = vlm_client
        self.vlm_model = vlm_model
        self.max_tokens = max_tokens
        self.temperature = temperature

    def _stream_create(self, **kwargs) -> str:
        """Use streaming API to work around proxy response-size bug."""
        collected = []
        try:
            with self.client.messages.stream(**kwargs) as stream:
                for text in stream.text_stream:
                    collected.append(text)
        except Exception as e:
            if collected:
                logger.warning(f"Stream ended with error ({e}) but collected {len(collected)} chunks, using partial response")
                return "".join(collected)
            logger.warning(f"Streaming failed ({e}), falling back to non-streaming")
            response = self.client.messages.create(**kwargs)
            return response.content[0].text
        return "".join(collected)

    def detect(self, img_b64: str, media_type: str) -> List[UIElement]:
        """
        Send screenshot to VLM and parse detected elements.

        Args:
            img_b64: Base64-encoded screenshot
            media_type: Image media type (e.g. "image/png")

        Returns:
            List of detected UIElement objects
        """
        try:
            response_text = self._stream_create(
                model=self.vlm_model,
                max_tokens=self.max_tokens,
                system="You are a UI element detector. Analyze screenshots and return structured JSON describing all interactive elements.",
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": img_b64,
                            }
                        },
                        {
                            "type": "text",
                            "text": ELEMENT_DETECTION_PROMPT,
                        }
                    ]
                }],
                temperature=self.temperature,
            )

            logger.info(f"Element detection response length: {len(response_text)}")

            elements = self._parse_elements(response_text)
            logger.info(f"Detected {len(elements)} UI elements")

            return elements

        except Exception as e:
            logger.error(f"Element detection failed: {e}", exc_info=True)
            return []

    def _parse_elements(self, response_text: str) -> List[UIElement]:
        """Parse VLM response into UIElement list."""
        # Try to extract JSON array from response
        json_data = self._extract_json_array(response_text)
        if json_data is None:
            logger.warning(f"Could not parse element list from VLM response")
            return []

        elements = []
        for item in json_data:
            try:
                elem = self._item_to_element(item)
                if elem is not None:
                    elements.append(elem)
            except Exception as e:
                logger.warning(f"Failed to parse element {item}: {e}")
                continue

        return elements

    def _extract_json_array(self, text: str) -> Optional[List[Dict]]:
        """Extract a JSON array from text, handling code blocks and bare JSON."""
        # Try code block first
        match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding bare JSON array
        match = re.search(r'(\[\s*\{.*?\}\s*\])', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Try parsing entire text as JSON array
        try:
            result = json.loads(text.strip())
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

        return None

    def _item_to_element(self, item: Dict) -> Optional[UIElement]:
        """Convert a parsed JSON dict to UIElement."""
        if not isinstance(item, dict):
            return None

        bbox = item.get("bbox", [0, 0, 0, 0])
        if not isinstance(bbox, list) or len(bbox) != 4:
            return None

        x1, y1, x2, y2 = [int(v) for v in bbox]
        if x2 <= x1 or y2 <= y1:
            return None

        center = ((x1 + x2) // 2, (y1 + y2) // 2)

        return UIElement(
            element_id=int(item.get("id", 0)),
            bbox=(x1, y1, x2, y2),
            center=center,
            element_type=str(item.get("type", "unknown")),
            label=str(item.get("label", "")),
            confidence=0.7,  # VLM detection has reasonable confidence
            visual_description=str(item.get("visual", "")),
            interactive=bool(item.get("interactive", True)),
            parent_id=item.get("parent_id"),
        )
