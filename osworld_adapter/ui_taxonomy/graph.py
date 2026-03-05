"""
Semantic Network / Knowledge Graph for UI elements.

Persists element information across steps within a single task.
Tracks click history and provides structured context strings for the VLM.
Supports finding similar elements across steps (few-shot generalization).
"""

import logging
import math
from typing import Dict, List, Optional, Tuple

from .detector import UIElement

logger = logging.getLogger("desktopenv.ui_taxonomy.graph")


class UIKnowledgeGraph:
    """
    Semantic network of UI elements that persists across agent steps.

    Stores detected elements per step, tracks click outcomes,
    and generates structured context for the VLM prompt.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        """Reset graph between tasks."""
        # Current step's elements
        self._current_elements: List[UIElement] = []
        self._current_step: int = 0

        # History across steps
        self._step_elements: Dict[int, List[UIElement]] = {}  # step -> elements

        # Click history: (step, x, y, element_id or None, success or None)
        self._click_history: List[Tuple[int, int, int, Optional[int], Optional[bool]]] = []

        # Element occurrence tracking for few-shot
        # Maps (element_type, label) -> list of (step, element_id, center)
        self._element_occurrences: Dict[Tuple[str, str], List[Tuple[int, int, Tuple[int, int]]]] = {}

    def update(self, step: int, elements: List[UIElement]):
        """Update graph with elements from current step."""
        self._current_step = step
        self._current_elements = elements
        self._step_elements[step] = elements

        # Track occurrences for few-shot generalization
        for elem in elements:
            key = (elem.element_type, elem.label)
            if key not in self._element_occurrences:
                self._element_occurrences[key] = []
            self._element_occurrences[key].append(
                (step, elem.element_id, elem.center)
            )

    def match_target(self, x: int, y: int, max_distance: int = 50) -> Optional[UIElement]:
        """
        Find the nearest element to the given coordinates.

        Args:
            x, y: Target coordinates (in VLM image space)
            max_distance: Maximum distance to consider a match

        Returns:
            Nearest UIElement within max_distance, or None
        """
        if not self._current_elements:
            return None

        best = None
        best_dist = float('inf')

        for elem in self._current_elements:
            # Check if point is inside bounding box
            x1, y1, x2, y2 = elem.bbox
            if x1 <= x <= x2 and y1 <= y <= y2:
                # Point is inside — use distance to center as tiebreaker
                dist = math.dist((x, y), elem.center)
                if dist < best_dist:
                    best_dist = dist
                    best = elem
            else:
                # Point is outside — use distance to center
                dist = math.dist((x, y), elem.center)
                if dist < max_distance and dist < best_dist:
                    best_dist = dist
                    best = elem

        return best

    def record_click_outcome(self, x: int, y: int, element_id: Optional[int],
                             success: Optional[bool] = None):
        """Record a click action and its outcome."""
        self._click_history.append(
            (self._current_step, x, y, element_id, success)
        )

    def find_similar(self, element: UIElement) -> List[Tuple[int, UIElement]]:
        """
        Find elements with the same type and label across previous steps.

        Returns list of (step, UIElement) tuples for similar elements.
        """
        key = (element.element_type, element.label)
        occurrences = self._element_occurrences.get(key, [])

        results = []
        for step, eid, center in occurrences:
            if step == self._current_step and eid == element.element_id:
                continue  # Skip self
            if step in self._step_elements:
                for elem in self._step_elements[step]:
                    if elem.element_id == eid:
                        results.append((step, elem))
                        break

        return results

    def get_context_string(self, max_elements: int = 20) -> str:
        """
        Generate structured text summary of detected elements for VLM context.

        Args:
            max_elements: Maximum number of elements to include

        Returns:
            Formatted string to inject into VLM prompt
        """
        if not self._current_elements:
            return ""

        lines = []
        lines.append("## Detected UI Elements")
        lines.append("The screenshot has numbered bounding boxes marking interactive elements.\n")

        # Sort elements: interactive first, then by position (top-left to bottom-right)
        sorted_elems = sorted(
            self._current_elements[:max_elements],
            key=lambda e: (not e.interactive, e.center[1], e.center[0])
        )

        # Element list
        for elem in sorted_elems:
            desc = f"[{elem.element_id}] {elem.element_type}"
            if elem.label:
                desc += f' "{elem.label}"'
            desc += f" at ({elem.center[0]}, {elem.center[1]})"

            # Add relationship info
            extras = []
            if elem.parent_id is not None:
                extras.append(f"child of [{elem.parent_id}]")
            if elem.sibling_ids:
                sibling_str = ", ".join(f"[{s}]" for s in elem.sibling_ids[:3])
                extras.append(f"siblings: {sibling_str}")
            if elem.prototype_match:
                proto_name, proto_score = elem.prototype_match
                extras.append(f"matches {proto_name} ({proto_score:.2f})")
            if elem.visual_description:
                extras.append(elem.visual_description)

            if extras:
                desc += " — " + "; ".join(extras)

            lines.append(desc)

        # Build hierarchy summary
        hierarchy = self._build_hierarchy_summary(sorted_elems)
        if hierarchy:
            lines.append("\nHierarchy:")
            lines.extend(hierarchy)

        # Click history warning (if we clicked something that didn't work)
        recent_failures = [
            (s, x, y, eid) for s, x, y, eid, success in self._click_history
            if success is False and s >= self._current_step - 2
        ]
        if recent_failures:
            lines.append("\nRecent failed clicks (avoid these):")
            for step, x, y, eid in recent_failures[-3:]:
                label = f"[{eid}]" if eid else f"({x},{y})"
                lines.append(f"  - Step {step}: {label}")

        lines.append("\nUse these element IDs and coordinates to precisely target your clicks.")

        return "\n".join(lines)

    def _build_hierarchy_summary(self, elements: List[UIElement]) -> List[str]:
        """Build a compact hierarchy summary."""
        # Group children by parent
        parent_groups: Dict[Optional[int], List[UIElement]] = {}
        for elem in elements:
            pid = elem.parent_id
            if pid not in parent_groups:
                parent_groups[pid] = []
            parent_groups[pid].append(elem)

        lines = []
        # Show parents that have children
        for elem in elements:
            if elem.element_id in parent_groups:
                children = parent_groups[elem.element_id]
                child_strs = []
                for child in children[:5]:
                    label = child.label if child.label else child.element_type
                    child_strs.append(f"[{child.element_id}] {label}")
                children_str = ", ".join(child_strs)
                if len(children) > 5:
                    children_str += f" (+{len(children)-5} more)"
                lines.append(f"- [{elem.element_id}] {elem.label or elem.element_type}: {children_str}")

        return lines[:10]  # Cap at 10 hierarchy lines
