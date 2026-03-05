"""
UI Taxonomy system for element detection, classification, and hierarchy building.

Uses the VLM endpoint for element detection (no OpenCV dependency).
Provides structured context to the action-decision VLM call to reduce
"Clicked Wrong Element" failures.
"""

from .detector import UIElement, VLMElementDetector
from .hierarchy import HierarchyBuilder
from .prototypes import PrototypeMatcher
from .graph import UIKnowledgeGraph
from .annotator import ScreenshotAnnotator
from .integration import UITaxonomyPipeline, TaxonomyResult

__all__ = [
    "UIElement",
    "VLMElementDetector",
    "HierarchyBuilder",
    "PrototypeMatcher",
    "UIKnowledgeGraph",
    "ScreenshotAnnotator",
    "UITaxonomyPipeline",
    "TaxonomyResult",
]
