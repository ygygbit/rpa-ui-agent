"""
Hierarchy Builder — constructs parent/child/sibling relationships
between detected UI elements.

The VLM already provides parent_id for each element. This module:
1. Validates containment (children should be within parent bbox)
2. Fills in children_ids and sibling_ids
3. Builds the tree structure
"""

import logging
from typing import Dict, List

from .detector import UIElement

logger = logging.getLogger("rpa_agent.ui_taxonomy.hierarchy")


class HierarchyBuilder:
    """Builds parent/child/sibling relationships between UI elements."""

    def build(self, elements: List[UIElement]) -> List[UIElement]:
        """
        Assign children_ids and sibling_ids based on parent_id relationships.

        Args:
            elements: List of UIElements with parent_id set by VLM

        Returns:
            Same elements with children_ids and sibling_ids populated
        """
        if not elements:
            return elements

        # Build lookup by element_id
        by_id: Dict[int, UIElement] = {}
        for elem in elements:
            by_id[elem.element_id] = elem
            # Reset relationship lists
            elem.children_ids = []
            elem.sibling_ids = []

        # Populate children_ids from parent_id
        for elem in elements:
            if elem.parent_id is not None and elem.parent_id in by_id:
                parent = by_id[elem.parent_id]
                # Validate containment
                if self._is_roughly_contained(elem, parent):
                    parent.children_ids.append(elem.element_id)
                else:
                    # Parent doesn't contain child — VLM may have been wrong
                    logger.debug(
                        f"Element [{elem.element_id}] not contained in parent [{elem.parent_id}], "
                        f"removing parent link"
                    )
                    elem.parent_id = None

        # Populate sibling_ids (elements sharing the same parent)
        parent_to_children: Dict[int, List[int]] = {}
        for elem in elements:
            pid = elem.parent_id if elem.parent_id is not None else -1
            if pid not in parent_to_children:
                parent_to_children[pid] = []
            parent_to_children[pid].append(elem.element_id)

        for children_ids in parent_to_children.values():
            for eid in children_ids:
                if eid in by_id:
                    by_id[eid].sibling_ids = [
                        sid for sid in children_ids if sid != eid
                    ]

        # Log hierarchy stats
        roots = sum(1 for e in elements if e.parent_id is None)
        parents = sum(1 for e in elements if len(e.children_ids) > 0)
        logger.info(
            f"Hierarchy: {len(elements)} elements, {roots} roots, "
            f"{parents} parents with children"
        )

        return elements

    def _is_roughly_contained(self, inner: UIElement, outer: UIElement,
                               threshold: float = 0.6) -> bool:
        """
        Check if inner element is mostly contained within outer element.

        Uses overlap ratio — at least `threshold` of inner's area should
        be within outer's bbox.
        """
        ix1, iy1, ix2, iy2 = inner.bbox
        ox1, oy1, ox2, oy2 = outer.bbox

        # Intersection
        inter_x1 = max(ix1, ox1)
        inter_y1 = max(iy1, oy1)
        inter_x2 = min(ix2, ox2)
        inter_y2 = min(iy2, oy2)

        if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
            return False

        inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
        inner_area = (ix2 - ix1) * (iy2 - iy1)

        if inner_area == 0:
            return False

        return (inter_area / inner_area) >= threshold
