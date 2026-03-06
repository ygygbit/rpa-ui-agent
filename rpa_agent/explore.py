"""
App Explorer — builds a guidebook by systematically navigating an application.

The explorer uses the same CUA-VLM loop as the regular agent, but with a
different goal: instead of completing a task, it discovers and documents:
1. All pages/screens in the app
2. Navigation paths between pages
3. Interactable elements on each page
4. Recurring UI patterns (e.g., video → quiz → next)

Output: a structured Markdown guidebook that can be loaded via --guidebook
for future task execution.
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel


EXPLORE_SYSTEM_PROMPT = """You are an app exploration agent. Your goal is to systematically explore an application and document its structure.

IMPORTANT: You must respond with ONLY a JSON object. No markdown, no explanation outside the JSON.

## Your Mission

You are exploring an application to build a complete map of:
1. All pages/screens and their content
2. Navigation paths (how to get from one page to another)
3. All interactable elements (buttons, links, inputs, videos, etc.)
4. Recurring patterns (e.g., every section has video → quiz → next button)

## Response Format

Return a JSON object with:
- "reasoning": What you observe on this page and your exploration strategy
- "actions": Array of action objects to execute
- "status": "continue" (more to explore) or "done" (fully explored)
- "page_report": (REQUIRED every turn) A report of what you see on the current page

### page_report format:
{
    "page_id": "short_identifier_for_this_page",
    "page_title": "Human-readable title visible on screen",
    "page_description": "What this page is about / its purpose",
    "elements": [
        {
            "type": "button|link|video|input|checkbox|tab|menu|text|image|progress|other",
            "label": "Text on/near the element",
            "x": approximate_x_coordinate,
            "y": approximate_y_coordinate,
            "state": "enabled|disabled|active|completed|locked|playing|paused",
            "navigates_to": "page_id it leads to, if known, or null",
            "notes": "Any additional info (e.g., 'must complete video first')"
        }
    ],
    "patterns_observed": ["List of patterns you notice, e.g., 'video must finish before Next enables'"],
    "navigation_from": ["page_ids that link TO this page"],
    "navigation_to": ["page_ids reachable FROM this page"]
}

## Exploration Strategy

1. First, take a screenshot to see the current state
2. Document ALL visible elements on the current page
3. Systematically click through sections/tabs to discover pages
4. For each new page, document elements before moving on
5. Track which pages you've visited using page_id
6. Navigate back and try unexplored paths
7. Note any state changes (e.g., sections becoming unlocked)
8. When you've visited all discoverable pages, set status="done"

## Rules

1. Be THOROUGH — document every interactable element you can see
2. Use unique, consistent page_ids (e.g., "main_menu", "section_1", "quiz_section_2")
3. Note which elements are disabled/locked and what might unlock them
4. Pay attention to progress indicators, completion states
5. Don't try to actually COMPLETE tasks (like watch full videos) — just document them
6. For videos, note their existence and approximate duration if visible
7. If a section is locked, note what's needed to unlock it
8. Scroll down on each page to find elements below the fold
"""


@dataclass
class PageInfo:
    """Information about a discovered page."""
    page_id: str
    page_title: str
    page_description: str
    elements: List[Dict[str, Any]] = field(default_factory=list)
    patterns_observed: List[str] = field(default_factory=list)
    navigation_from: List[str] = field(default_factory=list)
    navigation_to: List[str] = field(default_factory=list)
    visit_count: int = 0
    screenshots: List[str] = field(default_factory=list)  # paths to screenshots


@dataclass
class AppMap:
    """Complete map of an explored application."""
    app_name: str
    explored_at: str
    pages: Dict[str, PageInfo] = field(default_factory=dict)
    patterns: List[str] = field(default_factory=list)
    navigation_graph: Dict[str, List[str]] = field(default_factory=dict)

    def add_page(self, report: Dict[str, Any]) -> None:
        """Add or update a page from an exploration report."""
        page_id = report.get("page_id", "unknown")
        if page_id in self.pages:
            page = self.pages[page_id]
            page.visit_count += 1
            # Merge new elements (avoid exact dupes)
            existing_labels = {e.get("label", "") for e in page.elements}
            for elem in report.get("elements", []):
                if elem.get("label", "") not in existing_labels:
                    page.elements.append(elem)
                    existing_labels.add(elem.get("label", ""))
            # Merge patterns
            for p in report.get("patterns_observed", []):
                if p not in page.patterns_observed:
                    page.patterns_observed.append(p)
            # Merge navigation
            for nav in report.get("navigation_from", []):
                if nav not in page.navigation_from:
                    page.navigation_from.append(nav)
            for nav in report.get("navigation_to", []):
                if nav not in page.navigation_to:
                    page.navigation_to.append(nav)
        else:
            self.pages[page_id] = PageInfo(
                page_id=page_id,
                page_title=report.get("page_title", ""),
                page_description=report.get("page_description", ""),
                elements=report.get("elements", []),
                patterns_observed=report.get("patterns_observed", []),
                navigation_from=report.get("navigation_from", []),
                navigation_to=report.get("navigation_to", []),
                visit_count=1,
            )

        # Update navigation graph
        if page_id not in self.navigation_graph:
            self.navigation_graph[page_id] = []
        for nav_to in report.get("navigation_to", []):
            if nav_to not in self.navigation_graph[page_id]:
                self.navigation_graph[page_id].append(nav_to)

    def merge_patterns(self, new_patterns: List[str]) -> None:
        """Merge global patterns."""
        for p in new_patterns:
            if p not in self.patterns:
                self.patterns.append(p)

    def to_guidebook_markdown(self) -> str:
        """Generate a structured markdown guidebook from the app map."""
        lines = []
        lines.append(f"# App Guidebook: {self.app_name}")
        lines.append(f"\n*Explored: {self.explored_at}*")
        lines.append(f"\n*Pages discovered: {len(self.pages)}*")

        # High-Level Map
        lines.append("\n---\n")
        lines.append("## High-Level Map")
        lines.append("\n### Pages Overview\n")
        for pid, page in self.pages.items():
            lines.append(f"- **{pid}**: {page.page_title}")
            if page.page_description:
                lines.append(f"  - {page.page_description}")

        lines.append("\n### Navigation Graph\n")
        lines.append("```")
        for src, dests in self.navigation_graph.items():
            for dst in dests:
                lines.append(f"  {src} --> {dst}")
        lines.append("```")

        # Patterns
        if self.patterns:
            lines.append("\n### General Patterns\n")
            for p in self.patterns:
                lines.append(f"- {p}")

        # Low-Level Map
        lines.append("\n---\n")
        lines.append("## Low-Level Map (Per-Page Details)")

        for pid, page in self.pages.items():
            lines.append(f"\n### Page: {pid}")
            lines.append(f"\n**Title:** {page.page_title}")
            if page.page_description:
                lines.append(f"\n**Description:** {page.page_description}")
            lines.append(f"\n**Visited:** {page.visit_count} time(s)")

            if page.navigation_from:
                lines.append(f"\n**Reachable from:** {', '.join(page.navigation_from)}")
            if page.navigation_to:
                lines.append(f"\n**Leads to:** {', '.join(page.navigation_to)}")

            if page.elements:
                lines.append("\n**Elements:**\n")
                lines.append("| Type | Label | Position | State | Navigates To | Notes |")
                lines.append("|------|-------|----------|-------|-------------|-------|")
                for elem in page.elements:
                    etype = elem.get("type", "?")
                    label = elem.get("label", "?")
                    x = elem.get("x", "?")
                    y = elem.get("y", "?")
                    state = elem.get("state", "?")
                    nav = elem.get("navigates_to", "")
                    notes = elem.get("notes", "")
                    lines.append(f"| {etype} | {label} | ({x}, {y}) | {state} | {nav} | {notes} |")

            if page.patterns_observed:
                lines.append("\n**Page-Level Patterns:**\n")
                for p in page.patterns_observed:
                    lines.append(f"- {p}")

        # Workflow Guide
        lines.append("\n---\n")
        lines.append("## Workflow Guide")
        lines.append("\n### How to Complete This App\n")
        lines.append("*(Auto-generated from navigation graph and patterns)*\n")

        # Generate a simple sequential walkthrough based on nav graph
        visited = set()
        queue = []
        # Find entry page (page with no navigation_from, or first page)
        entry = None
        for pid, page in self.pages.items():
            if not page.navigation_from:
                entry = pid
                break
        if not entry and self.pages:
            entry = list(self.pages.keys())[0]

        if entry:
            queue.append(entry)
            step = 1
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                page = self.pages.get(current)
                if page:
                    lines.append(f"{step}. Go to **{current}** ({page.page_title})")
                    # List key actions
                    for elem in page.elements:
                        if elem.get("type") in ("button", "link", "video", "checkbox", "input"):
                            state = elem.get("state", "")
                            if state != "disabled" and state != "locked":
                                lines.append(f"   - {elem.get('type')}: {elem.get('label', '?')} at ({elem.get('x', '?')}, {elem.get('y', '?')})")
                    step += 1
                    # Add next pages to queue
                    for nav_to in self.navigation_graph.get(current, []):
                        if nav_to not in visited:
                            queue.append(nav_to)

        return "\n".join(lines)


def generate_guidebook(app_map: AppMap, output_path: Path) -> Path:
    """Write the guidebook markdown file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = app_map.to_guidebook_markdown()
    output_path.write_text(content, encoding="utf-8")
    return output_path


def load_guidebook(path: Path) -> str:
    """Load a guidebook markdown file and return its content."""
    return path.read_text(encoding="utf-8")


def summarize_guidebook_for_prompt(guidebook_content: str, max_chars: int = 6000) -> str:
    """Summarize a guidebook for inclusion in the system prompt.

    If the guidebook is short enough, include it as-is.
    Otherwise, include the high-level map and patterns, truncating low-level details.
    """
    if len(guidebook_content) <= max_chars:
        return guidebook_content

    # Try to include everything up to low-level map
    parts = guidebook_content.split("## Low-Level Map")
    if len(parts) >= 2:
        high_level = parts[0]
        # Include workflow guide if present
        workflow_parts = guidebook_content.split("## Workflow Guide")
        workflow = ""
        if len(workflow_parts) >= 2:
            workflow = "\n## Workflow Guide" + workflow_parts[1]

        result = high_level
        if len(result) + len(workflow) <= max_chars:
            result += workflow
        elif len(result) <= max_chars:
            # Truncate workflow to fit
            remaining = max_chars - len(result) - 50
            if remaining > 200:
                result += workflow[:remaining] + "\n\n*(truncated)*"

        if len(result) <= max_chars:
            return result

    # Last resort: truncate
    return guidebook_content[:max_chars] + "\n\n*(truncated — full guidebook available in file)*"
