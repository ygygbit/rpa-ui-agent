"""
Prototype Library — domain-specific prototypes for common UI elements.

Each prototype defines expected properties of a known UI element type.
Matching is done by comparing detected element properties against prototypes.
Prototypes provide a secondary confirmation signal alongside VLM detection.
"""

import logging
from typing import Dict, List, Optional, Tuple

from .detector import UIElement

logger = logging.getLogger("rpa_agent.ui_taxonomy.prototypes")


# Domain-specific prototype definitions
# Each prototype: { position_zone, typical_y_range, typical_size, element_type, description }
PROTOTYPES: Dict[str, Dict[str, Dict]] = {
    "chrome": {
        "three_dot_menu": {
            "position_zone": "top-right",
            "typical_y_range": (0, 80),
            "typical_x_range": (1800, 1920),
            "element_type": "icon",
            "description": "Chrome three-dot menu (vertical ellipsis) at top-right corner",
        },
        "tab": {
            "position_zone": "top",
            "typical_y_range": (0, 40),
            "element_type": "tab",
            "description": "Browser tab at top of window",
        },
        "address_bar": {
            "position_zone": "top",
            "typical_y_range": (40, 80),
            "element_type": "text_field",
            "description": "Browser URL/address bar",
        },
        "back_button": {
            "position_zone": "top-left",
            "typical_y_range": (40, 80),
            "typical_x_range": (0, 80),
            "element_type": "icon",
            "description": "Browser back navigation button",
        },
        "bookmark_bar": {
            "position_zone": "top",
            "typical_y_range": (80, 120),
            "element_type": "toolbar",
            "description": "Bookmarks toolbar below address bar",
        },
        "search_box": {
            "position_zone": "center",
            "typical_y_range": (300, 600),
            "element_type": "text_field",
            "description": "Web page search box (Google, DuckDuckGo, etc.)",
        },
    },
    "libreoffice": {
        "menu_bar_item": {
            "position_zone": "top",
            "typical_y_range": (0, 30),
            "element_type": "menu_item",
            "description": "LibreOffice menu bar item (File, Edit, View, etc.)",
        },
        "toolbar_button": {
            "position_zone": "top",
            "typical_y_range": (30, 80),
            "element_type": "button",
            "description": "LibreOffice toolbar button",
        },
        "sheet_tab": {
            "position_zone": "bottom",
            "typical_y_range": (1000, 1080),
            "element_type": "tab",
            "description": "Spreadsheet sheet tab at bottom",
        },
        "cell": {
            "position_zone": "center",
            "element_type": "text_field",
            "description": "Spreadsheet cell",
        },
        "sidebar_panel": {
            "position_zone": "right",
            "typical_x_range": (1600, 1920),
            "element_type": "panel",
            "description": "LibreOffice sidebar panel",
        },
    },
    "gimp": {
        "toolbox_icon": {
            "position_zone": "left",
            "typical_x_range": (0, 80),
            "element_type": "icon",
            "description": "GIMP toolbox icon (paint, select, etc.)",
        },
        "menu_item": {
            "position_zone": "top",
            "typical_y_range": (0, 30),
            "element_type": "menu_item",
            "description": "GIMP menu bar item",
        },
        "layer_panel": {
            "position_zone": "right",
            "typical_x_range": (1400, 1920),
            "element_type": "panel",
            "description": "GIMP layers/channels panel",
        },
        "canvas": {
            "position_zone": "center",
            "element_type": "panel",
            "description": "GIMP canvas/image area",
        },
    },
    "vs_code": {
        "activity_bar_icon": {
            "position_zone": "left",
            "typical_x_range": (0, 50),
            "element_type": "icon",
            "description": "VS Code activity bar icon (explorer, search, etc.)",
        },
        "editor_tab": {
            "position_zone": "top",
            "typical_y_range": (30, 65),
            "element_type": "tab",
            "description": "VS Code editor tab",
        },
        "command_palette": {
            "position_zone": "top-center",
            "typical_y_range": (0, 50),
            "element_type": "text_field",
            "description": "VS Code command palette",
        },
        "status_bar": {
            "position_zone": "bottom",
            "typical_y_range": (1050, 1080),
            "element_type": "toolbar",
            "description": "VS Code status bar at bottom",
        },
    },
    "thunderbird": {
        "folder_tree_item": {
            "position_zone": "left",
            "typical_x_range": (0, 300),
            "element_type": "link",
            "description": "Thunderbird folder tree item (Inbox, Sent, etc.)",
        },
        "message_list_item": {
            "position_zone": "center",
            "element_type": "link",
            "description": "Thunderbird message list entry",
        },
        "toolbar_button": {
            "position_zone": "top",
            "typical_y_range": (0, 60),
            "element_type": "button",
            "description": "Thunderbird toolbar button",
        },
        "menu_item": {
            "position_zone": "top",
            "typical_y_range": (0, 30),
            "element_type": "menu_item",
            "description": "Thunderbird menu bar item",
        },
    },
    "generic": {
        "close_button": {
            "position_zone": "top-right",
            "typical_y_range": (0, 40),
            "element_type": "button",
            "description": "Window close button (X)",
        },
        "minimize_button": {
            "position_zone": "top-right",
            "typical_y_range": (0, 40),
            "element_type": "button",
            "description": "Window minimize button",
        },
        "dialog_ok": {
            "position_zone": "bottom-right",
            "element_type": "button",
            "description": "Dialog OK/Apply/Save button",
        },
        "dialog_cancel": {
            "position_zone": "bottom-right",
            "element_type": "button",
            "description": "Dialog Cancel/Close button",
        },
        "scrollbar": {
            "position_zone": "right",
            "typical_x_range": (1890, 1920),
            "element_type": "scrollbar",
            "description": "Vertical scrollbar",
        },
    },
}


class PrototypeMatcher:
    """Matches detected UI elements against known prototypes."""

    def __init__(self, domain: Optional[str] = None):
        """
        Args:
            domain: If set, prioritize prototypes from this domain.
                    Prototypes from other domains and 'generic' are still checked.
        """
        self.primary_domain = domain

    def match(self, element: UIElement,
              screen_width: int = 1344, screen_height: int = 756) -> Optional[Tuple[str, float]]:
        """
        Match element against known prototypes.

        Args:
            element: The detected UI element
            screen_width: Screenshot width for position zone calculation
            screen_height: Screenshot height for position zone calculation

        Returns:
            (prototype_name, confidence_score) or None if no match above threshold
        """
        best_match = None
        best_score = 0.0

        # Check primary domain first, then generic, then others
        domain_order = []
        if self.primary_domain and self.primary_domain in PROTOTYPES:
            domain_order.append(self.primary_domain)
        domain_order.append("generic")
        for d in PROTOTYPES:
            if d not in domain_order:
                domain_order.append(d)

        for domain in domain_order:
            if domain not in PROTOTYPES:
                continue
            for proto_name, proto in PROTOTYPES[domain].items():
                score = self._compute_similarity(
                    element, proto, screen_width, screen_height
                )
                # Boost score for primary domain
                if domain == self.primary_domain:
                    score *= 1.2

                if score > best_score and score > 0.4:
                    best_score = min(score, 1.0)
                    best_match = f"{domain}.{proto_name}"

        return (best_match, best_score) if best_match else None

    def _compute_similarity(self, element: UIElement, prototype: Dict,
                            screen_width: int, screen_height: int) -> float:
        """Compute similarity score between element and prototype."""
        score = 0.0
        checks = 0

        cx, cy = element.center
        x1, y1, x2, y2 = element.bbox

        # Position zone match
        if "position_zone" in prototype:
            checks += 1
            elem_zone = self._get_position_zone(cx, cy, screen_width, screen_height)
            if prototype["position_zone"] in elem_zone or elem_zone in prototype["position_zone"]:
                score += 1.0
            elif self._zones_adjacent(elem_zone, prototype["position_zone"]):
                score += 0.3

        # Y-range match
        if "typical_y_range" in prototype:
            checks += 1
            y_lo, y_hi = prototype["typical_y_range"]
            if y_lo <= cy <= y_hi:
                score += 1.0
            elif abs(cy - y_lo) < 30 or abs(cy - y_hi) < 30:
                score += 0.4

        # X-range match
        if "typical_x_range" in prototype:
            checks += 1
            x_lo, x_hi = prototype["typical_x_range"]
            if x_lo <= cx <= x_hi:
                score += 1.0
            elif abs(cx - x_lo) < 30 or abs(cx - x_hi) < 30:
                score += 0.4

        # Element type match
        if "element_type" in prototype:
            checks += 1
            if element.element_type == prototype["element_type"]:
                score += 1.0
            elif self._types_compatible(element.element_type, prototype["element_type"]):
                score += 0.5

        return score / max(checks, 1)

    def _get_position_zone(self, cx: int, cy: int,
                           sw: int, sh: int) -> str:
        """Determine position zone of a point on screen."""
        x_zone = "left" if cx < sw * 0.25 else ("right" if cx > sw * 0.75 else "center")
        y_zone = "top" if cy < sh * 0.2 else ("bottom" if cy > sh * 0.85 else "center")

        if y_zone == "top" and x_zone == "right":
            return "top-right"
        elif y_zone == "top" and x_zone == "left":
            return "top-left"
        elif y_zone == "top" and x_zone == "center":
            return "top-center"
        elif y_zone == "bottom" and x_zone == "right":
            return "bottom-right"
        elif y_zone == "bottom" and x_zone == "left":
            return "bottom-left"
        elif y_zone == "top":
            return "top"
        elif y_zone == "bottom":
            return "bottom"
        elif x_zone == "left":
            return "left"
        elif x_zone == "right":
            return "right"
        return "center"

    def _zones_adjacent(self, z1: str, z2: str) -> bool:
        """Check if two position zones are adjacent."""
        adjacency = {
            "top": {"top-left", "top-right", "top-center"},
            "top-left": {"top", "left"},
            "top-right": {"top", "right"},
            "top-center": {"top"},
            "bottom": {"bottom-left", "bottom-right"},
            "bottom-left": {"bottom", "left"},
            "bottom-right": {"bottom", "right"},
            "left": {"top-left", "bottom-left"},
            "right": {"top-right", "bottom-right"},
            "center": {"top-center"},
        }
        return z2 in adjacency.get(z1, set()) or z1 in adjacency.get(z2, set())

    def _types_compatible(self, t1: str, t2: str) -> bool:
        """Check if two element types are roughly compatible."""
        compat_groups = [
            {"button", "icon"},
            {"menu_item", "link"},
            {"text_field", "dropdown"},
            {"toolbar", "panel"},
        ]
        for group in compat_groups:
            if t1 in group and t2 in group:
                return True
        return False
