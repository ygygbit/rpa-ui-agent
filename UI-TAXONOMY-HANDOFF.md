# UI Taxonomy System — Handoff Document

> **Purpose**: Complete knowledge transfer for the UI Taxonomy feature. Read this to understand the design, architecture, integration points, benchmark results, and known limitations.

---

## Problem Statement

The RPA agent's #1 failure mode on the OSWorld benchmark is **"Clicked Wrong Element"** — accounting for **29 out of 137 failures (21.2%)** at the 62.8% success rate baseline.

The root cause: the VLM receives a raw screenshot and must simultaneously identify UI elements AND decide what action to take. These are two different cognitive tasks that compete for attention. The VLM often clicks near the right element but misses by 10-30 pixels, hitting a neighboring button, menu item, or empty space.

**Example failures**: Clicking the address bar instead of a tab, clicking a toolbar button instead of a menu item, clicking between two tightly-packed icons.

---

## Solution: Two-Pass VLM Architecture

UI Taxonomy separates element identification from action decision into two sequential VLM calls per step:

```
Pass 1 (Detection):  Screenshot → VLM → JSON list of UI elements with bounding boxes
Pass 2 (Decision):   Annotated screenshot + element context → VLM → Action with coordinates
```

### Why Two Passes Work Better

1. **Dedicated attention**: Pass 1 focuses entirely on "what elements exist and where are they?" — no distraction from task planning
2. **Structured context**: Pass 2 receives a numbered element list with exact coordinates, so it can say "click element [7]" instead of guessing pixel positions
3. **Coordinate snapping**: Even if the VLM's click is slightly off, we snap to the nearest detected element center within 30px
4. **Visual anchoring**: Set-of-Marks (SoM) bounding boxes drawn on the screenshot give the VLM visual reference points with numbered IDs

---

## Architecture

### Package Structure

```
rpa_agent/ui_taxonomy/          # Main package (integrated into CLI agent)
├── __init__.py                 # Exports: UITaxonomyPipeline, TaxonomyResult, UIElement, etc.
├── detector.py                 # Pass 1: VLM call to detect elements → List[UIElement]
├── hierarchy.py                # Builds parent/child/sibling relationships from VLM parent_ids
├── prototypes.py               # Domain-specific prototype matching (position + type heuristics)
├── graph.py                    # Knowledge graph: persists elements across steps, coordinate snapping
├── annotator.py                # Draws numbered bounding boxes on screenshots (PIL, no OpenCV)
└── integration.py              # Pipeline orchestrator: detect → hierarchy → prototypes → annotate → context

osworld_adapter/ui_taxonomy/    # Identical copy for OSWorld benchmark adapter (separate deployment)
```

### Data Flow

```
                    ┌──────────────────────────────────────────────────┐
                    │            UITaxonomyPipeline                     │
                    │                                                    │
  base64_img ──────►│  1. VLMElementDetector.detect()                   │
  media_type        │     └─ Streaming VLM call with ELEMENT_DETECTION_PROMPT
  step_number       │     └─ Parse JSON array → List[UIElement]         │
                    │                                                    │
                    │  2. HierarchyBuilder.build()                      │
                    │     └─ Validate parent/child containment          │
                    │     └─ Fill children_ids, sibling_ids             │
                    │                                                    │
                    │  3. PrototypeMatcher.match() per element          │
                    │     └─ Score against domain prototypes            │
                    │     └─ Attach (prototype_name, confidence)        │
                    │                                                    │
                    │  4. UIKnowledgeGraph.update()                     │
                    │     └─ Store elements for this step               │
                    │     └─ Track element occurrences across steps     │
                    │                                                    │
                    │  5. ScreenshotAnnotator.annotate()                │
                    │     └─ Draw colored bounding boxes + [N] labels   │
                    │     └─ Output: base64 PNG                         │
                    │                                                    │
                    │  6. UIKnowledgeGraph.get_context_string()         │
                    │     └─ Structured text listing all elements       │
                    │     └─ Hierarchy summary, click history           │
                    │                                                    │
                    └──────► TaxonomyResult                             │
                              ├─ elements: List[UIElement]              │
                              ├─ annotated_image: str (base64 PNG)      │
                              └─ context_string: str (for VLM prompt)   │
```

### Key Classes

#### `UIElement` (detector.py)
```python
@dataclass
class UIElement:
    element_id: int
    bbox: Tuple[int, int, int, int]     # (x1, y1, x2, y2)
    center: Tuple[int, int]
    element_type: str                    # button, icon, menu_item, text_field, etc.
    label: str
    confidence: float = 0.5
    visual_description: str = ""
    interactive: bool = True
    parent_id: Optional[int] = None
    children_ids: List[int]             # Filled by HierarchyBuilder
    sibling_ids: List[int]              # Filled by HierarchyBuilder
    prototype_match: Optional[Tuple[str, float]] = None  # (name, score)
```

#### `VLMElementDetector` (detector.py)
- Sends screenshot + `ELEMENT_DETECTION_PROMPT` to VLM
- Returns up to 20 interactive elements per screenshot
- Uses streaming API with partial response recovery (proxy "Response too long" workaround)
- Parses JSON from code blocks, bare arrays, or raw text

#### `UIKnowledgeGraph` (graph.py)
- Persists elements across steps within a single task
- `match_target(x, y, max_distance=50)` — finds nearest element for coordinate snapping
- `get_context_string()` — generates structured text for VLM prompt injection
- `record_click_outcome()` — tracks which clicks succeeded/failed
- `find_similar()` — finds same-type elements across steps (few-shot generalization)

#### `ScreenshotAnnotator` (annotator.py)
- Draws Set-of-Marks (SoM) style annotations: colored bounding boxes + `[N]` labels
- Color-coded by element type (blue=button, red=icon, yellow=menu_item, green=text_field, etc.)
- Semi-transparent overlays using PIL RGBA compositing
- Outputs PNG (regardless of input format)

#### `PrototypeMatcher` (prototypes.py)
- Domain-specific prototype definitions for: chrome, libreoffice, gimp, vs_code, thunderbird, generic
- Scores elements by: position zone, y-range, x-range, element type
- Primary domain gets a 1.2x score boost
- Threshold: score > 0.4 to match

---

## Integration Points in GUIAgent

The taxonomy is integrated into `rpa_agent/agent.py` at these locations:

### 1. Configuration (`AgentConfig`)
```python
enable_taxonomy: bool = False       # Two-pass VLM element detection
taxonomy_domain: Optional[str] = None  # Domain hint (chrome, gimp, etc.)
```

### 2. Initialization (`GUIAgent.__init__`)
- Creates `UITaxonomyPipeline` using `self.vlm.client` (raw Anthropic client from VLMClient)
- Appends taxonomy instructions to system prompt

### 3. Run Loop — Three Integration Points

**A. After screenshot capture (agent.py ~line 1251)**
```
_capture_screenshot() → base64_img (JPEG)
                      ↓
taxonomy_pipeline.process_screenshot(base64_img, media_type, step)
                      ↓
Replace base64_img with annotated_image (PNG with bounding boxes)
Store taxonomy_context string
```

**B. Before VLM call (agent.py ~line 1300)**
```
task_for_vlm += taxonomy_context
```
The context string looks like:
```
## Detected UI Elements
The screenshot has numbered bounding boxes marking interactive elements.

[1] toolbar "Navigation" at (150, 55) — child of [None]
[2] icon "Back" at (40, 55) — child of [1]; matches chrome.back_button (0.85)
[3] text_field "Address bar" at (500, 55) — matches chrome.address_bar (0.92)
[4] tab "New Tab" at (200, 20) — matches chrome.tab (0.88)
...

Use these element IDs and coordinates to precisely target your clicks.
```

**C. After action parse, before rescale (agent.py ~line 1315)**
```
parser.parse(vlm_response) → action with x,y in VLM image space
                            ↓
knowledge_graph.match_target(action.x, action.y, max_distance=30)
                            ↓
Snap action.x, action.y to matched element's center
                            ↓
_rescale_action_coords(action)  → screen space coordinates
```

Important: Snapping happens in **VLM image space** (before rescale), because the taxonomy elements were detected from the same resized image the VLM sees. Both coordinate sets match.

### 4. CLI Flags
```
--enable-taxonomy / --taxonomy    Enable two-pass VLM element detection
--taxonomy-domain                 Domain hint (chrome, libreoffice, gimp, vs_code, thunderbird)
```
Available on both `rpa-agent run` and `rpa-agent sandbox run`.

---

## Screen Change Detection

The pipeline caches results based on MD5 hash of the first 10KB of image data:

```python
img_hash = hashlib.md5(img_b64[:10000].encode()).hexdigest()
if img_hash == self._last_img_hash and self._cached_elements:
    return cached_result  # Skip VLM call
```

This avoids redundant detection calls when the screen hasn't changed between steps (e.g., after a keyboard action that doesn't change the UI).

---

## Benchmark Results

### Baseline (without taxonomy): 62.8% on 368 tasks

From `reports/benchmark-results-comprehensive.md`:
- 231/368 tasks successful
- 137 failures, of which 29 were "Clicked Wrong Element"

### Taxonomy v4 Benchmark: 29 "Clicked Wrong Element" tasks

Ran the 29 failed-due-to-wrong-click tasks with taxonomy enabled:
- **Result: 5/29 = 17.2% recovery rate**
- Model: `claude-opus-4.6-1m`, 50 steps, `--no_a11y` flag

#### Tasks recovered:
| # | Domain | Task ID (short) | Description |
|---|--------|-----------------|-------------|
| 3 | chrome | 12086550 | Chrome password settings |
| 4 | chrome | 93eabf48 | Chrome dark mode |
| 10 | gimp | 045bf3ff | GIMP enhance photo |
| 11 | gimp | 04d9aeaf | GIMP CYMK mode |
| 28 | vs_code | 847a96b6 | VS Code open workspaces |

#### Domain breakdown:
- Chrome: 2/7
- GIMP: 2/4
- VS Code: 1/2
- LibreOffice: 0/7
- Thunderbird: 0/5
- OS/Misc: 0/4

### Key Observations

1. **GIMP tasks benefited most** (50% recovery) — GIMP has densely packed toolbox icons where precise clicking matters
2. **Chrome tasks partially recovered** (29%) — address bar vs tab confusion was fixable with element detection
3. **LibreOffice tasks not recovered** (0%) — failures were more about finding the right menu path than clicking precision
4. **Thunderbird tasks not recovered** (0%) — failures were multi-step workflow issues, not click accuracy
5. **Cost tradeoff**: Each step now makes 2 VLM calls instead of 1, roughly doubling per-step token cost

### Estimated impact on full benchmark:
- Baseline: 231/368 = 62.8%
- Recovered: +5 tasks
- New estimate: 236/368 = **64.1%** (a +1.4% improvement on the full benchmark)

---

## Streaming Fix

Both `rpa_agent.py` (OSWorld adapter) and `detector.py` include a critical streaming fix:

```python
def _stream_create(self, **kwargs) -> str:
    collected = []
    try:
        with self.client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                collected.append(text)
    except Exception as e:
        if collected:
            # Proxy sent "Response too long" SSE error, but we already got the content
            logger.warning(f"Stream ended with error but collected {len(collected)} chunks")
            return "".join(collected)
        # No data collected — fall back to non-streaming
        logger.warning(f"Streaming failed, falling back to non-streaming")
        response = self.client.messages.create(**kwargs)
        return response.content[0].text
    return "".join(collected)
```

Without this fix, the proxy endpoint returns a "Response too long" error via SSE that kills the stream, but the full response was already sent in earlier chunks. The fix checks if we already collected text before falling back.

---

## Known Limitations and Future Improvements

### Current Limitations

1. **2x cost per step**: Two VLM calls per step (detection + decision). For 50-step tasks, this is 100 VLM calls.
2. **Detection quality varies**: The general-purpose VLM (Claude) isn't fine-tuned for UI element detection. A dedicated model (like Qwen2.5-VL or UI-TARS) would be more accurate.
3. **Fixed 20-element limit**: The prompt asks for at most 20 elements. Dense UIs (e.g., LibreOffice toolbars) may need more.
4. **No cross-step element tracking**: Elements are re-detected every step (unless screen is unchanged). No persistent ID assignment across screen changes.
5. **Snap distance too conservative**: 30px max_distance means elements more than 30px from the VLM's click target won't snap. Could be more aggressive.
6. **No click outcome feedback**: `record_click_outcome()` is available but not wired up — the agent doesn't report back whether a click succeeded.

### Potential Improvements

1. **Selective detection**: Only run Pass 1 when the task involves clicking (skip for typing, key presses, done/fail).
2. **Larger element limit for dense UIs**: Increase from 20 to 30-40 for LibreOffice/GIMP.
3. **Confidence-weighted snapping**: Snap more aggressively to high-confidence prototype matches.
4. **Click outcome tracking**: After each click, compare before/after screenshots to determine if the intended element was actually clicked. Feed this back via `record_click_outcome()`.
5. **Fine-tuned detection model**: Use a smaller, faster model (Haiku) for Pass 1 detection, reserving the large model for Pass 2 decisions.
6. **Persistent element IDs**: Track elements across screen changes using position + type + label similarity, enabling "last time I clicked element [7] at step 3, now the same element is [12] at step 5".
7. **Adaptive domain detection**: Auto-detect the application domain from the screenshot (Chrome, GIMP, etc.) instead of requiring `--taxonomy-domain`.

---

## How to Run

### Main CLI (free-form commands)
```bash
# Basic usage
uv run rpa-agent run "open apple.com" --enable-taxonomy --max-steps 20

# With domain hint for better prototype matching
uv run rpa-agent sandbox run "change chrome to dark mode" --enable-taxonomy --taxonomy-domain chrome

# Dry run (no execution, see VLM responses)
uv run rpa-agent run "open settings" --enable-taxonomy --dry-run
```

### OSWorld Benchmark
```bash
# From WSL, with taxonomy enabled in osworld_adapter/rpa_agent.py
cd /home/user/OSWorld
python osworld_adapter/run_rpa.py \
    --no_a11y \
    --task_id_file osworld_adapter/task_ids.txt \
    --max_steps 50
```
Note: The OSWorld adapter (`osworld_adapter/rpa_agent.py`) has taxonomy hardcoded and always-on. The main CLI agent (`rpa_agent/agent.py`) uses the `--enable-taxonomy` flag.

---

## File Reference

| File | Key Lines | What it Does |
|------|-----------|-------------|
| `rpa_agent/agent.py:143-145` | `AgentConfig` | `enable_taxonomy`, `taxonomy_domain` fields |
| `rpa_agent/agent.py:230-240` | `__init__` | Creates `UITaxonomyPipeline` |
| `rpa_agent/agent.py:252-261` | `__init__` | Appends taxonomy system prompt |
| `rpa_agent/agent.py:1251-1263` | `run()` | Pass 1: detect elements, annotate image |
| `rpa_agent/agent.py:1269-1271` | `run()` | Media type switch to PNG after annotation |
| `rpa_agent/agent.py:1300-1302` | `run()` | Inject context into task_for_vlm |
| `rpa_agent/agent.py:1315-1328` | `run()` | Snap coordinates before rescale |
| `rpa_agent/cli.py:67-68` | `run` cmd | `--enable-taxonomy`, `--taxonomy-domain` options |
| `rpa_agent/cli.py:102-103` | `run` cmd | Pass to AgentConfig |
| `rpa_agent/cli.py:553-554` | `sandbox run` | Same options for sandbox |
| `rpa_agent/cli.py:613-614` | `sandbox run` | Pass to AgentConfig |
| `rpa_agent/ui_taxonomy/detector.py:18-44` | Prompt | `ELEMENT_DETECTION_PROMPT` |
| `rpa_agent/ui_taxonomy/graph.py:60-93` | Snapping | `match_target()` — coordinate snapping logic |
| `rpa_agent/ui_taxonomy/graph.py:123-190` | Context | `get_context_string()` — VLM prompt injection |
| `rpa_agent/ui_taxonomy/annotator.py:65-112` | Annotate | `annotate()` — draws bounding boxes |
| `rpa_agent/ui_taxonomy/prototypes.py:19-197` | Prototypes | Domain-specific prototype definitions |

---

## Branch and Commit

- **Branch**: `test-ui-taxonomy`
- **Latest commit**: `d84964d` — "Integrate UI taxonomy into main CLI agent with --enable-taxonomy flag"
- **Files changed**: 18 files, +2747 lines
