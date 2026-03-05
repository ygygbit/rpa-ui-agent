"""
Integration module — orchestrates the full UI taxonomy pipeline.

Connects detector, hierarchy builder, prototype matcher, knowledge graph,
and annotator into a single process_screenshot() call.

Includes screen change detection to skip redundant element detection
when the screenshot hasn't changed significantly.
"""

import hashlib
import logging
from dataclasses import dataclass
from typing import List, Optional

from .detector import UIElement, VLMElementDetector
from .hierarchy import HierarchyBuilder
from .prototypes import PrototypeMatcher
from .graph import UIKnowledgeGraph
from .annotator import ScreenshotAnnotator

logger = logging.getLogger("rpa_agent.ui_taxonomy.integration")


@dataclass
class TaxonomyResult:
    """Result of processing a screenshot through the taxonomy pipeline."""
    elements: List[UIElement]
    annotated_image: Optional[str]  # Base64-encoded annotated screenshot
    context_string: str             # Structured text for VLM prompt


class UITaxonomyPipeline:
    """
    Orchestrates UI element detection, feature extraction, hierarchy building,
    prototype matching, and context generation.
    """

    def __init__(
        self,
        vlm_client,
        vlm_model: str = "claude-opus-4.6-1m",
        domain: Optional[str] = None,
        enable_annotation: bool = True,
        max_elements: int = 20,
        max_tokens: int = 4096,
        temperature: float = 0.1,
    ):
        self.detector = VLMElementDetector(
            vlm_client=vlm_client,
            vlm_model=vlm_model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        self.hierarchy_builder = HierarchyBuilder()
        self.prototype_matcher = PrototypeMatcher(domain=domain)
        self.knowledge_graph = UIKnowledgeGraph()
        self.annotator = ScreenshotAnnotator(max_elements=max_elements) if enable_annotation else None
        self.max_elements = max_elements
        self.domain = domain

        # Screen change detection cache
        self._last_img_hash: Optional[str] = None
        self._cached_elements: List[UIElement] = []
        self._cached_annotated: Optional[str] = None
        self._cached_context: str = ""
        self._cache_hits: int = 0

    def process_screenshot(self, img_b64: str, media_type: str,
                           step: int) -> TaxonomyResult:
        """
        Full pipeline: detect elements -> build hierarchy -> match prototypes
        -> update graph -> annotate -> generate context.

        Uses screen change detection to skip VLM call if screenshot is unchanged.

        Args:
            img_b64: Base64-encoded screenshot
            media_type: Image media type (e.g. "image/png")
            step: Current step number

        Returns:
            TaxonomyResult with elements, annotated image, and context string
        """
        # Screen change detection: hash the image data
        img_hash = hashlib.md5(img_b64[:10000].encode()).hexdigest()

        if img_hash == self._last_img_hash and self._cached_elements:
            self._cache_hits += 1
            logger.info(
                f"Step {step}: screen unchanged (cache hit #{self._cache_hits}), "
                f"reusing {len(self._cached_elements)} elements"
            )
            return TaxonomyResult(
                elements=self._cached_elements,
                annotated_image=self._cached_annotated,
                context_string=self._cached_context,
            )

        self._last_img_hash = img_hash

        # 1. VLM call to detect elements
        elements = self.detector.detect(img_b64, media_type)

        if not elements:
            logger.warning(f"No elements detected at step {step}")
            return TaxonomyResult(
                elements=[],
                annotated_image=None,
                context_string="",
            )

        # 2. Build hierarchy from VLM-provided parent_ids
        elements = self.hierarchy_builder.build(elements)

        # 3. Match prototypes (secondary confirmation signal)
        for elem in elements:
            elem.prototype_match = self.prototype_matcher.match(elem)

        # 4. Update knowledge graph
        self.knowledge_graph.update(step, elements)

        # 5. Annotate screenshot with bounding boxes
        annotated_b64 = None
        if self.annotator:
            annotated_b64 = self.annotator.annotate(img_b64, elements, media_type)

        # 6. Generate context string for VLM prompt
        context = self.knowledge_graph.get_context_string(
            max_elements=self.max_elements
        )

        logger.info(
            f"Step {step}: {len(elements)} elements detected, "
            f"context length: {len(context)} chars"
        )

        result = TaxonomyResult(
            elements=elements,
            annotated_image=annotated_b64,
            context_string=context,
        )

        # Cache for screen change detection
        self._cached_elements = elements
        self._cached_annotated = annotated_b64
        self._cached_context = context

        return result

    def reset(self):
        """Reset between tasks."""
        self.knowledge_graph.reset()
        self._last_img_hash = None
        self._cached_elements = []
        self._cached_annotated = None
        self._cached_context = ""
        self._cache_hits = 0
        logger.info("UI Taxonomy pipeline reset")

    def set_domain(self, domain: Optional[str]):
        """Update the domain for prototype matching."""
        self.domain = domain
        self.prototype_matcher = PrototypeMatcher(domain=domain)
