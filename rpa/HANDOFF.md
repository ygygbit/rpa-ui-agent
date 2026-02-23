# RPA Agent Handoff Document

> **Purpose**: Knowledge persistence across sessions. Read this first when starting a new session.

---

## Project Overview

This is a Vision-Language Model (VLM) based RPA agent that automates GUI tasks by:
1. Capturing screenshots from a Docker sandbox (1920x1080 Linux + Chrome)
2. Resizing to 1344x756, drawing a coordinate grid with original-pixel labels
3. Sending to VLM for analysis (Claude via Anthropic API or custom endpoint)
4. Parsing JSON actions from VLM response
5. Executing mouse/keyboard actions via XTEST (python-xlib)
6. Verifying results and self-correcting (stuck-loop detection, coordinate validation)

**Key Goal**: Achieve accurate mouse navigation in 1-2 moves (VLM decides target -> agent navigates there reliably).

**GitHub Repo**: `git@github.com:layoffhuman/rpa-ui-agent.git` (private)

---

## Architecture

```
rpa_agent/
├── cli.py              # Entry point, includes sandbox commands
├── agent.py            # GUIAgent orchestrator (observe-think-act loop)
│                       #   - _capture_screenshot: resize to 1344px, draw grid, encode
│                       #   - _rescale_action_coords: VLM image space -> screen space
│                       #   - _draw_coordinate_grid: 100px grid with original-coord labels
│                       #   - _check_stuck_loop: 2-warn, 3-block, 5-override detection
│                       #   - _validate_coordinates: reject y<140 for web elements
├── core/
│   ├── screen.py       # Windows GDI screen capture + overlays
│   ├── remote_screen.py  # HTTP-based screenshot from sandbox
│   ├── remote_controller.py # HTTP-based action execution in sandbox
│   ├── controller.py   # Windows SendInput for mouse/keyboard
│   ├── window.py       # Window management
│   ├── cursor_overlay.py  # Visual cursor indicator
│   ├── action_notifier.py # Action display UI
│   └── hotkey.py       # Ctrl+Alt stop hotkey
├── actions/
│   ├── definitions.py  # 24 action types (ClickAction, TypeAction, etc.)
│   └── parser.py       # Parse VLM JSON output -> action objects
├── vlm/
│   ├── __init__.py     # Exports VLMClient, VLMConfig, SystemPrompts
│   ├── client.py       # Anthropic API client (custom endpoint + official)
│   └── prompts.py      # System prompts (GUI_AGENT, GROUNDING, etc.)
├── benchmark/          # MiniWoB++ benchmark system
│   ├── __init__.py
│   └── miniwob_runner.py  # VLM-based benchmark runner
├── sandbox/            # Docker sandbox for Linux (1080p)
│   ├── screen_linux.py
│   ├── controller_linux.py  # XTEST-based input (Session 6 rewrite)
│   │                        #   - XTestInput class: all mouse/keyboard via python-xlib
│   │                        #   - LinuxController: wraps XTestInput + window ops via xdotool
│   ├── server.py       # FastAPI for remote control (click, type, screenshot, etc.)
│   └── test_xtest_input.py  # XTEST diagnostic tests
└── tests/              # Testing framework
    ├── mouse_accuracy.py     # Accuracy metrics & targets
    ├── run_mouse_test.py     # Automated test runner
    ├── quick_test.py         # Quick 5-target test
    └── mouse_test_ground.html # Visual test page
```

### Sandbox Architecture
```
Windows Host                          Docker Container (rpa-sandbox)
┌─────────────────┐                  ┌────────────────────────────────┐
│ Python agent     │◄── HTTP API ──►│ FastAPI server (port 8000)     │
│ (cli.py)         │                 │ ├─ /screenshot                 │
│                  │                 │ ├─ /mouse/click                │
│ VLM Client ──────►Custom Endpoint │ ├─ /keyboard/type              │
│ (client.py)      │ or Anthropic   │ ├─ /keyboard/press             │
│                  │ API            │ ├─ /keyboard/hotkey             │
└─────────────────┘                 │ └─ /chrome/start               │
                                     │                                │
                                     │ Xvfb :99 (1920x1080)          │
                                     │ Chrome (--remote-debugging)    │
                                     │ XTEST input (python-xlib)     │
                                     │ noVNC (port 6080 for preview)  │
                                     └────────────────────────────────┘
```

---

## Current State (Session 10 - 2026-02-23)

### Latest Working State

The agent successfully completes real-world tasks with **optimized settings**:
- **100% success rate** on DuckDuckGo search, Google search, multi-step search+scroll tasks
- **Optimized config (recommended)**: JPEG q75, max_edge=1024, Ctrl+L navigation hints
  - **-86% input tokens** vs baseline
  - **-31% fewer steps** vs baseline
  - **-45% wall time** vs baseline

### Recommended Agent Configuration

```python
config = AgentConfig(
    vlm_config=VLMConfig(base_url="...", model="claude-opus-4.6-fast"),
    max_steps=20,
    step_delay=0.5,
    max_history_turns=10,       # Sliding window (Session 9)
    vlm_image_format="jpeg",    # JPEG instead of PNG (Exp 5)
    vlm_image_quality=75,       # q75 sufficient for VLM (Exp 5)
    vlm_max_edge=1024,          # 1024px instead of 1344px (Exp 5)
    coordinate_validation="relaxed",  # Relaxed y<100 threshold (Exp 12)
    action_feedback=True,       # Confirm successful actions to VLM (Exp 15)
    smart_wait=True,            # Extra delay after navigation actions (Exp 16)
    smart_wait_delay=1.5,       # 1.5s wait for page loads (Exp 16)
)
# Use build_enhanced_prompt() from test_exp7_combined.py for Ctrl+L nav hints (Exp 6)
```

### VLM Coordinate Pipeline (Critical to understand)

This is the most important subsystem and the one that received the most iteration:

```
1. Capture 1920x1080 screenshot from sandbox
2. Resize to max_edge (default 1344, optimized 1024) maintaining aspect ratio
   scale_factor = max_edge / max(1920, 1080)
3. Draw coordinate grid on resized image:
   - Grid lines every 100 original-pixels
   - Labels show ORIGINAL coordinates (100, 200, 300, ...)
   - Pixel positions = original_coord * scale_factor
   - Major lines at 500px, crosshairs at intersections
4. Encode image (PNG default, JPEG q75 optimized — 76% smaller)
5. Send to VLM with media_type="image/jpeg" or "image/png"
6. VLM returns coordinates in ORIGINAL screen space (reads grid labels)
7. Agent rescales: action.x *= (1/scale_factor)
   (This is the _vlm_scale_factor stored in agent)
8. Execute action at rescaled coordinates
```

**Why pre-resize**: Anthropic's API internally resizes images > 1568px. If we sent a 1920px image with grid labels at pixel positions, the API downscales it but the labels still say "1920" while the VLM sees a ~1200px image. Grid label positions no longer match visual positions, causing ~30% systematic offset. By pre-resizing to 1344px (or 1024px), we guarantee no further API resizing occurs.

**JPEG vs PNG**: JPEG q75 at 1024px reduces base64 image size by ~76%, cutting per-step input tokens from ~575K to ~120K. VLM accuracy is unaffected — coordinate grid labels remain readable at this quality level.

### VLM Configuration

The VLM client supports two modes:
1. **Custom endpoint** (default for development): `http://localhost:23333/api/anthropic` with model `claude-opus-4.6-fast`
2. **Official Anthropic API**: Set `ANTHROPIC_API_KEY` env var, uses `claude-opus-4-20250514`

Environment variables:
- `RPA_VLM_BASE_URL`: Custom API endpoint URL
- `RPA_VLM_API_KEY`: API key for custom endpoint
- `RPA_VLM_MODEL`: Model name override
- `ANTHROPIC_API_KEY`: Official Anthropic API key

### Stuck-Loop Detection System

Multi-tier detection in `agent.py:_check_stuck_loop()`:

| Consecutive Same Actions | Severity | Behavior |
|--------------------------|----------|----------|
| 2 | warn | Soft warning injected into conversation |
| 3-4 | block | Action NOT executed, VLM re-queried with alternatives list |
| 5+ | override | Force keyboard fallback (Enter key), clear action history |
| 3+ (after type) | override | If typed text then kept clicking, auto-press Enter to submit |
| 3+ clicks same area | block | Detected via coordinate clustering (80x40px), force "type" action |
| 6+ actions same area | block/override | Coordinate-based (60x60px box), force different strategy |
| ABAB oscillation | block | Alternating between 2 actions detected |

### Coordinate Validation

`agent.py:_validate_coordinates()` catches common VLM mistakes:
- Coordinates outside screen bounds (always active)
- Web page elements (search, input, button, etc.) at y < threshold → rejected as browser chrome confusion
- Any element with "search" in name at y < 100 → rejected as address bar misidentification

**Configurable via `coordinate_validation`**: `"strict"` (y<140), `"relaxed"` (y<100, default), `"off"` (bounds only). Changed from strict to relaxed in Exp 12 because y<140 blocked Wikipedia search icon at y~122.

### UI-TARS-desktop Deep Analysis (Session 8-9)

Comprehensive analysis of ByteDance's UI-TARS-desktop repo (28.1k stars, Apache 2.0, TypeScript monorepo). Dual project: **Agent TARS** (AI browser agent) + **UI-TARS Desktop** (desktop GUI agent).

#### Architecture Comparison

| Aspect | Our RPA Agent | UI-TARS-desktop |
|--------|--------------|-----------------|
| Language | Python | TypeScript (pnpm monorepo) |
| Agent Loop | While-loop in `GUIAgent.run()` | While-loop with `async-retry` per phase |
| State Machine | `AgentState` (5 states) | `StatusEnum` (7 states: INIT, RUNNING, PAUSE, END, CALL_USER, USER_STOPPED, ERROR) |
| Input Method | XTEST via python-xlib | NutJS (desktop), Puppeteer (browser), ADB (mobile) |
| VLM Model | Claude (general-purpose + grid overlay) | Qwen2.5-VL / UI-TARS (fine-tuned for grounding) |
| Coordinate System | Grid overlay labels → rescale by 1.4286x | Normalized [0,1] via `/factors` → scale to screen |
| Screenshot Resize | Max-edge 1344, simple ratio | `smart_resize()` with factor-28 divisibility (Qwen2.5-VL requirement) |
| Conversation History | Full history sent each step | Sliding window: last 5 screenshots max |
| Retry | Basic try/catch | `async-retry` per phase (screenshot, model, execute) |
| Stuck Detection | Multi-tier (warn→block→override, ABAB, clustering) | Basic `MAX_LOOP_COUNT=100` |

#### Key Design Patterns Worth Incorporating

**1. Operator Abstraction** — Clean abstract base class:
```
Operator:
  screenshot() → base64 image
  execute(params) → perform action
  static MANUAL.ACTION_SPACES → auto-generate prompt action list
```
Four implementations: NutJSOperator (desktop), BrowserOperator (Puppeteer), AdbOperator (mobile), BrowserbaseOperator (remote). Each defines its own action space as a static string.

**2. Per-Phase Retry** — Each step has independent retry:
- Screenshot capture: retries up to `MAX_SNAPSHOT_ERR_CNT=10`
- VLM model invoke: retries ~3 times
- Action execute: retries ~3 times
A transient error in one phase doesn't fail the whole step.

**3. Pause/Resume/Stop** — Via `AbortController.signal`:
- `pause()`: sets PAUSE status, awaits a Promise
- `resume()`: resolves the Promise, back to RUNNING
- Signal checked at each loop iteration
- Valuable for debugging: pause, inspect state, resume

**4. Conversation History Sliding Window** — `MAX_IMAGE_LENGTH = 5`:
- Only last N screenshots kept in conversation history
- Reduces token cost as step count grows
- Keeps VLM focused on recent state

**5. DPI-Aware Screenshots** (NutJS):
- Captures at native DPI via `screen.pixelDensity()`
- Downscales by `scaleX/Y` before sending to VLM
- Coordinate results divided by `deviceScaleFactor`

**6. Clipboard Paste for Typing** (Windows):
- NutJS uses `clipboard.setContent(text)` + `Ctrl+V` on Windows
- Better Unicode support than character-by-character typing

**7. UIHelper Visual Feedback** (BrowserOperator):
- SoM-style clickable element highlighting: buttons=pink, links=purple, inputs=green
- Click pulse indicators, drag gradient paths
- Action info panel overlay
- Could improve VLM accuracy if used on screenshots before sending

**8. Action Space Auto-Generation**:
- System prompt template: `"... {{action_spaces_holder}} ..."`
- Replaced at runtime with `operator.MANUAL.ACTION_SPACES`
- Keeps prompt in sync with available actions automatically

#### What We Have That They Don't
- Coordinate grid overlay (model-agnostic approach)
- Multi-tier stuck-loop detection (warn→block→override, ABAB, clustering)
- Coordinate validation (y<140 browser chrome detection)

#### Recommended Improvements (Priority Order)
1. **Conversation history sliding window** — Low effort, high impact on token cost/quality
2. **Operator abstraction** — Medium effort, improves architecture & extensibility
3. **Per-phase retry** — Low effort, improves reliability
4. **Pause/Resume** — Medium effort, better debugging experience
5. **SoM-style element highlighting** — High effort, potentially high VLM accuracy impact
6. **Auto-generated action space in prompt** — Low effort after operator abstraction
7. **Clipboard paste for Windows typing** — Only for non-sandbox use

---

## Commit History (Recent)

| Commit | Date | Summary |
|--------|------|---------|
| `50c3206` | 2026-02-20 | Coordinate rescaling fix: pre-resize then draw grid with original-coord labels, `_rescale_action_coords()`, `_vlm_scale_factor` |
| `29c705c` | 2026-02-19 | Fix VLM address bar confusion: y<140 validation for web elements, enhanced prompt |
| `34ef7ad` | 2026-02-19 | Denser grid overlay (100px), dual-edge labels, crosshair markers, diagnostic test scripts |
| `b56a58e` | 2026-02-19 | Unified XTEST controller replacing CDP+xdotool, `XTestInput` class |
| `1169471` | 2026-02-16 | CDP-based typing for Chrome web content (later replaced by XTEST) |
| `c7d101d` | 2026-02-17 | Configurable VLM endpoints and documentation |
| `9485672` | 2026-02-17 | Pre-push version |
| `4a11667` | 2026-02-17 | HANDOFF.md with MiniWoB++ benchmark details |
| `9df2c0d` | 2026-02-17 | MiniWoB++ benchmark working |
| `da2045b` | 2026-02-16 | Remote API working, can open google and type |

---

## Session History

### Session 1 (2026-02-14)
- Initial project setup
- Basic VLM integration
- Mouse control implementation

### Session 2 (2026-02-15)
- Docker sandbox mode
- Mouse accuracy testing framework
- Achieved 100% mouse accuracy

### Session 3 (2026-02-16)
- MiniWoB++ benchmark integration
- Iterative improvement over 13 runs
- **Final result: 91.7% (110/120) - TARGET ACHIEVED!**
- Key improvements: 4x scaling, Y-clamping, stuck detection, task hints

### Session 4 (2026-02-16) - Real-World Iteration
- Pushed code to GitHub (`layoffhuman/rpa-ui-agent`, private)
- Created ITERATION_PLAN.md with 40+ real-world tasks and 格物致知 methodology
- Installed additional apps in sandbox: gedit, mousepad, gnome-calculator, libreoffice-writer, libreoffice-calc
- **First real-world test: Google search FAILED** — agent stuck in typing loop
- Root cause: no stuck-loop detection in main agent, prompt too rigid

### Session 5 (2026-02-16) - CDP Integration
- Discovered xdotool type fails for Chrome web page content (X11 vs Blink input pipeline)
- Implemented CDP-based typing with `Input.insertText`
- **Google search test: SUCCESS** — typed in search bar via CDP, hit CAPTCHA (environmental)
- **DuckDuckGo test: FAIL** — VLM coordinate accuracy issue (17px off target)

### Session 6 (2026-02-19) - Unified XTEST Input Controller
- Discovered the REAL root cause: `xdotool type --window <wid>` forces **XSendEvent** (not XTEST) — Chrome ignores synthetic events
- **Replaced entire CDP+xdotool hybrid with unified XTEST controller** via python-xlib `fake_input()`
- Added `XTestInput` class (~250 lines) — all mouse/keyboard operations via XTEST
- Eliminated ALL CDP code from controller (~200 lines removed)
- Kept xdotool only for window search operations (focus, geometry, active window)
- **All diagnostic tests PASS**: mouse accuracy (0 drift), address bar, web content, special chars, URLs
- **Agent integration test**: Controller works perfectly but VLM gives coords ~170px off target
- Technical notes: `display.flush()` not `display.sync()` (avoids BadRRModeError on Xvfb); XTEST typing interval set to 30ms for Chrome autocomplete resilience

#### XTEST Controller Architecture
```
type_text(text) → _xtest.type_string(text)
  - Maps each char to X11 keysym → keycode
  - Handles Shift for uppercase/special chars

click(x, y) → _xtest.move_to(x,y) → _xtest.button_press(1) → _xtest.button_release(1)

press_key(key) → _xtest.press_named_key(key)

hotkey(*keys) → _xtest.hotkey(*keys)
  - Press modifiers down, press key, release in reverse order

scroll(amount) → _xtest.button_press(4/5) → _xtest.button_release(4/5)
```

#### Performance Improvement
| Operation | Old (xdotool subprocess) | New (python-xlib XTEST) |
|-----------|--------------------------|------------------------|
| Mouse move | ~50ms | ~1ms |
| Click | ~100ms | ~2ms |
| Type 10 chars | ~500ms | ~20ms |
| Get cursor | ~50ms | ~1ms |

### Session 7 (2026-02-19 to 2026-02-20) - VLM Coordinate Accuracy Fix

**Root Cause Discovery**: VLM coordinate errors (~170px off) were caused by the Anthropic API internally resizing images > 1568px. The agent sent a 1920x1080 screenshot with grid labels at 1920-pixel-space positions. The API downscaled it to ~1200px, but the grid labels still showed "1920" coordinates while the VLM saw the image at a different size. Grid line visual positions no longer matched their labeled values.

**Solution (commit 50c3206)**: Pre-resize to 1344x756, then draw grid with original-coordinate labels:
1. Resize screenshot from 1920x1080 → 1344x756 (below API's 1568px limit)
2. Draw grid lines at pixel positions = `original_coord * (1344/1920)`
3. Label each line with its ORIGINAL coordinate value (e.g., line at pixel 140 labeled "200")
4. VLM reads labels and returns coordinates in original screen space
5. Agent rescales: `screen_coord = vlm_coord * (1920/1344)`

**Additional improvements**:
- Grid spacing changed from 200px to 100px with major lines at 500px
- Dual-edge labels (top+bottom for X, left+right for Y)
- Yellow crosshair markers at all grid intersections
- VLM prompt updated with explicit grid-reading instructions
- Coordinate validation: reject web page elements at y < 140 (browser chrome zone)
- Enhanced address bar vs search box distinction in prompts

**Files changed**: `agent.py` (major: rescaling, grid drawing, validation), `prompts.py` (grid instructions), `controller_linux.py` (typing interval 20ms→30ms)

### Session 8 (2026-02-21) - Real-World Testing & UI-TARS Research

**YouTube Playlist Test — SUCCESS**:
- Task: "Open YouTube, find Liked videos playlist, play a video"
- Model: `claude-opus-4.6-fast` via custom endpoint
- Result: Completed in 7/7 steps
- Steps: clicked YouTube tab → waited for load → clicked "Liked videos" → clicked video → done

**UI-TARS Initial Analysis**: Researched ByteDance's UI-TARS project coordinate handling.
- UI-TARS uses `smart_resize()` with factor-28 divisibility (Qwen2.5-VL requirement)
- Normalizes coordinates to [0,1] as intermediate step: `coord / resized_dim * original_dim`
- Does NOT use grid overlays — relies on fine-tuned VLM grounding ability
- Our approach is more model-agnostic; theirs is tighter with purpose-built grounding model

### Session 9 (2026-02-21) - UI-TARS-desktop Deep Dive

**Deep analysis of UI-TARS-desktop monorepo** (github.com/bytedance/UI-TARS-desktop):
- Analyzed all 4 operators (NutJS, Browser, ADB, Browserbase)
- Analyzed SDK GUIAgent, Model, action-parser, shared types
- Analyzed newer multimodal/gui-agent ToolCallEngine implementation
- Identified 7 concrete design patterns to incorporate (see "UI-TARS-desktop Deep Analysis" section above)
- Updated HANDOFF.md with comprehensive findings and priority-ordered improvement recommendations
- Top 3 improvements: conversation history sliding window, operator abstraction, per-phase retry

### Session 10 (2026-02-23) - UI-TARS A/B Experiments

Ran 7 systematic A/B experiments to test UI-TARS-inspired improvements against baseline. Each experiment isolated a single variable with identical tasks, VLM, and sandbox state. All tests used 3 browser tasks (DuckDuckGo search, Google search, multi-step search+scroll).

#### Experiment Results Summary

| # | Branch | Experiment | Result | Key Metric |
|---|--------|-----------|--------|------------|
| 1 | `exp/thought-action-format` | Thought-Action prompt format | **NEUTRAL** | +22% steps, same success |
| 2 | `exp/reflection-mechanism` | Reflection after each step | **NEGATIVE** | 67% vs 100% success rate |
| 3 | `exp/clipboard-typing` | Clipboard paste (xclip+Ctrl+V) | **NEGATIVE** | 0% vs 100% success rate |
| 4 | `exp/simplified-action-space` | Minimal action space (7 vs 15 actions) | **NEUTRAL** | Identical performance |
| 5 | `exp/screenshot-optimization` | JPEG q75, max_edge=1024 | **POSITIVE** | **-76% tokens**, same success |
| 6 | `exp/navigation-hints` | Ctrl+L address bar workflow | **POSITIVE** | **-24% steps, -27% time** |
| 7 | `exp/combined-improvements` | JPEG + Ctrl+L combined | **STRONG POSITIVE** | **-86% tokens, -31% steps, -45% time** |
| 8 | `exp/harder-tasks` | 5 harder multi-step tasks | **GOOD** | 80% (4/5) with optimized config |
| 9 | `exp/task-decomposition` | Flat vs numbered sub-steps | **NEUTRAL** | 75% both ways, task-dependent |
| 10 | `exp/scroll-fix-maxsteps` | Scroll fix + max_steps=35 | **MIXED** | 60% hard tasks, scroll fix merged |
| 11 | `exp/window-size` | Sliding window 5 vs 10 vs 20 | **NEUTRAL** | Images dominate token cost |
| 12 | `exp/coordinate-validation` | Coord validation strict/relaxed/off | **POSITIVE** | relaxed 100% vs strict 80%, merged |
| 13 | `exp/per-phase-retry` | Per-phase retry for screenshot/VLM | **NEUTRAL** | 100% both, no transient errors in lab |
| 14 | `exp/screen-change-detection` | Screen change detection after actions | **NEUTRAL/NEGATIVE** | 34 false positives, +22% overhead |
| 15 | `exp/action-feedback` | Action confirmation feedback | **STRONG POSITIVE** | **100% vs 80%, -24% steps, -37% time**, merged |
| 16 | `exp/smart-wait` | Smart wait after navigation actions | **MODERATE POSITIVE** | **-13% steps, -18% tokens**, merged |
| 17 | `exp/cumulative-validation` | All improvements on 10 tasks | **100% (10/10)** | All improvements stack, no interference |

#### Detailed Experiment Findings

**Exp 1 — Thought-Action Prompt Format**: Added UI-TARS-style `Thought: ... Action: ...` format requiring VLM to reason before acting. Added 22% more steps (VLM occasionally emitted thought-only responses). No success rate impact. Not worth the overhead.

**Exp 2 — Reflection Mechanism**: Injected "Reflection:" section asking VLM to evaluate last action's success. **Degraded success rate from 100% to 67%** — the VLM second-guessed correct actions and retried unnecessarily. Counter-productive with general-purpose Claude (may work with fine-tuned models).

**Exp 3 — Clipboard Typing**: Used `xclip` + `Ctrl+V` paste instead of keystroke-by-keystroke typing. **Total failure (0% success)** — xclip/Ctrl+V doesn't reliably deliver text to Chrome address bar in Xvfb Docker environment. All tasks hit max_steps. Infrastructure limitation, not a conceptual flaw.

**Exp 4 — Simplified Action Space**: Reduced from 15 to 7 action types (merged `press_key` into `hotkey`, removed `move_*`, `drag`, `right_click`, `double_click`). Identical success rate, step count, and timing. The VLM already only uses a small subset of actions for web tasks.

**Exp 5 — Screenshot Optimization** (POSITIVE): JPEG q75 at 1024px max_edge vs PNG at 1344px. Per-step input tokens dropped from ~575K to ~120K (**-76%**). Success rate unchanged at 100%. JPEG q50 at 768px was too aggressive — VLM reported coordinates outside screen bounds due to image being too small for spatial reasoning.

**Exp 6 — Ctrl+L Navigation Hints** (POSITIVE): Replaced generic "click address bar or use Ctrl+L" with strict "ALWAYS use Ctrl+L, NEVER click address bar" workflow. Eliminated the common failure where VLM clicks address bar without selecting existing text, causing appended URLs (`about:blankgoogle.com`). Saved 2-3 steps per URL navigation. **-24% steps, -27% wall time**.

**Exp 7 — Combined Improvements** (STRONG POSITIVE): Stacked Exp 5 (JPEG) + Exp 6 (Ctrl+L). Effects are **multiplicative** — JPEG saves tokens per step, Ctrl+L saves steps.

| Metric | Baseline | Combined | Delta |
|--------|----------|----------|-------|
| Success Rate | 100% | 100% | 0% |
| Avg Steps | 10.7 | 7.3 | **-31%** |
| Avg Input Tokens | 6,311,382 | 905,866 | **-86%** |
| Avg Output Tokens | 3,449 | 2,453 | **-29%** |
| Avg Wall Time (s) | 49.1 | 27.0 | **-45%** |

#### Git Branches

| Branch | Commit | Status |
|--------|--------|--------|
| `main` | `ececd1c` | Base (sliding window + operator abstraction) |
| `exp/thought-action-format` | `4527fa1` | Complete (Exp 1, neutral) |
| `exp/reflection-mechanism` | `a884da9` | Complete (Exp 2, negative) |
| `exp/clipboard-typing` | `8c852a1` | Complete (Exp 3, negative) |
| `exp/simplified-action-space` | `4fbbb99` | Complete (Exp 4, neutral) |
| `exp/screenshot-optimization` | `6df99e8` | Complete (Exp 5, positive) |
| `exp/navigation-hints` | `9ab0aff` | Complete (Exp 6, positive) |
| `exp/combined-improvements` | `3cbbb27` | Complete (Exp 7, strong positive) |
| `exp/harder-tasks` | `857cded` | Complete (Exp 8, 80% on hard tasks) |
| `exp/task-decomposition` | `96b5d4d` | Complete (Exp 9, neutral) |
| `exp/scroll-fix-maxsteps` | `f8b6771` | Complete (Exp 10, scroll fix merged to main) |
| `exp/window-size` | `a881ee3` | Complete (Exp 11, neutral) |
| `exp/coordinate-validation` | `af8624b` | Complete (Exp 12, relaxed validation merged) |
| `exp/per-phase-retry` | `742aa81` | Complete (Exp 13, neutral) |
| `exp/screen-change-detection` | `05d6f5a` | Complete (Exp 14, neutral/negative) |
| `exp/action-feedback` | `a4ff589` | Complete (Exp 15, strong positive, merged) |
| `exp/smart-wait` | `22aab8f` | Complete (Exp 16, moderate positive, merged) |
| `exp/cumulative-validation` | `79a54f1` | Complete (Exp 17, 100% on 10 tasks) |

#### Experiments 8-17: Hard Tasks, Robustness, and Validation

**Exp 8 — Harder Tasks** (80% success, 4/5): Tested optimized config on harder multi-step tasks (Wikipedia lookup, DuckDuckGo click result, multi-tab workflow, scroll+back nav, text selection). Wikipedia and multi-tab tasks completed well. "Page Scroll + Back Navigation" failed at 25 max steps.

**Exp 9 — Task Decomposition Hint** (NEUTRAL): Tested flat vs numbered sub-step task descriptions on 4 hard tasks. Same 75% success rate both ways. Decomposition fixed one failing task but broke another — it's task-dependent, not a general win. VLM follows rigid step plans too literally when tasks require visual search.

**Exp 10 — Scroll Fix + Higher Max Steps** (60% on 5 hard tasks): Found and fixed a bug in stuck-loop detection where scroll actions were being blocked at 3 consecutive repeats. Added scroll direction/amount to action signature, raised scroll block threshold from 3 to 6. The scroll fix was merged to main. Higher max_steps (35 vs 25) was not beneficial — the agent wastes more time on unproductive attempts.

**Exp 11 — Sliding Window Size** (NEUTRAL): Compared window=5, 10, 20 on 4 tasks. All three window sizes performed similarly. Key finding: **images dominate per-step token cost** (~66-130K tokens/step regardless of window size), so text in conversation history barely matters. Wikipedia Lookup failed across all window sizes due to y<140 coordinate validation false positive.

**Exp 12 — Coordinate Validation Threshold** (POSITIVE): Compared strict (y<140), relaxed (y<100), off (bounds-only) on 5 tasks including 2 Wikipedia tasks. **Relaxed wins**: 100% success, 0 false rejections. Strict only 80% — Wikipedia History Section failed due to 4 false-positive rejections of Wikipedia search icon at y~122. Relaxed mode merged to main as default.

| Mode | Success | Avg Steps | Coord Rejections |
|------|---------|-----------|------------------|
| strict | 80% (4/5) | 13.6 | 5 |
| relaxed | **100% (5/5)** | 13.8 | **0** |
| off | 100% (5/5) | 13.6 | 0 |

**Exp 13 — Per-Phase Retry** (NEUTRAL): Added configurable `phase_retries` that wraps screenshot capture and VLM API calls with independent retry loops. Tested `phase_retries=0` (baseline) vs `phase_retries=3` on 5 tasks. Both achieved 100% success with 0 retries triggered — the sandbox lab environment is stable with no transient errors. The feature provides production reliability insurance but shows no benefit in controlled testing.

**Exp 14 — Screen Change Detection** (NEUTRAL/NEGATIVE): Added `screen_change_detection` flag that captures pre/post action screenshots, compares them with numpy pixel diff (>0.5% threshold), and warns VLM when the screen didn't change. Result: same 80% success rate both configs, but detection config had **higher avg steps** (16.2 vs 15.0) and **+22% wall time** (65.9s vs 53.8s). 34 screen-change warnings triggered, many being false positives — the 0.3s wait after action execution is insufficient for page loads to render. The warnings confused the VLM rather than helping it. Not merged.

| Config | Success | Avg Steps | Avg Tokens | Avg Time | Warnings |
|--------|---------|-----------|------------|----------|----------|
| baseline | 80% (4/5) | 15.0 | 1,208,973 | 53.8s | 0 |
| screen_change | 80% (4/5) | 16.2 | 1,322,193 | 65.9s | 34 |

**Exp 15 — Action Confirmation Feedback** (STRONG POSITIVE): Added `action_feedback` flag that injects brief confirmation messages into conversation history after successful actions (e.g., "Action 'click' executed successfully. Clicked at (500, 300)."). Previously, the VLM only received feedback on failed actions — successful actions had no confirmation. Result: **100% vs 80% success rate**, **-24% avg steps** (13.6 vs 18.0), **-37% avg wall time** (46.3s vs 73.5s), **-21% avg tokens**. The Wikipedia Search task that failed baseline (hit 25 max_steps) completed in just 13 steps with feedback. Merged to main with `action_feedback=True` as default.

| Config | Success | Avg Steps | Avg Tokens | Avg Time |
|--------|---------|-----------|------------|----------|
| baseline | 80% (4/5) | 18.0 | 1,479,588 | 73.5s |
| **feedback** | **100% (5/5)** | **13.6** | **1,163,331** | **46.3s** |

**Exp 16 — Smart Wait After Navigation** (MODERATE POSITIVE): Added `smart_wait` flag that adds extra delay (1.5s) after actions likely to trigger page loads (clicks, Enter key presses). This gives pages time to fully render before the next screenshot. Both configs achieved 100% success, but smart wait reduced avg steps by 13% and tokens by 18%. Wikipedia Article Scroll improved from 22 to 15 steps. One task (Multi-Step Nav) got slightly worse (12 -> 15 steps) due to unnecessary waits on in-page clicks that don't cause navigation. Merged to main with `smart_wait=True` as default.

| Config | Success | Avg Steps | Avg Tokens | Avg Time |
|--------|---------|-----------|------------|----------|
| baseline | 100% (5/5) | 12.6 | 1,133,102 | 44.7s |
| **smart_wait** | **100% (5/5)** | **11.0** | **931,024** | **40.8s** |

**Exp 17 — Cumulative Improvements Validation** (100%, 10/10): Validated all 6 merged improvements stacking cleanly by running the same 5 standard tasks from Exp 12-16 plus 5 new harder tasks never used during optimization. Standard tasks: DuckDuckGo Search, Wikipedia Search, Multi-Step Navigation, DuckDuckGo Click Result, Wikipedia Article Scroll. Hard tasks: Wikipedia + Back Nav, DuckDuckGo Image Search, Multi-Tab Workflow, Form Interaction, Deep Scroll + Find. All 10 tasks completed successfully with no interference between improvements. Average 11.1 steps, 988K input tokens, 41.0s wall time across all tasks.

| Category | Success | Avg Steps | Avg Tokens | Avg Time |
|----------|---------|-----------|------------|----------|
| Standard (5 tasks) | **100% (5/5)** | 11.0 | 988,953 | 41.3s |
| Hard (5 tasks) | **100% (5/5)** | 11.2 | 987,052 | 40.7s |
| **Overall (10 tasks)** | **100% (10/10)** | **11.1** | **987,902** | **41.0s** |

Historical comparison: Exp 8 original hard tasks 80% (4/5), Exp 12 baseline 80% (4/5), Exp 15 baseline 80% (4/5) → Exp 17 all improvements 100% (10/10). The cumulative effect of all 6 improvements is a robust agent that handles both standard and novel hard tasks at 100% success.

#### Improvements Merged to Main

| Change | Source | Commit |
|--------|--------|--------|
| JPEG q75 1024px defaults | Exp 5+7 | `24c32a4` via merge |
| Ctrl+L nav prompt | Exp 6+7 | `f833242` |
| Scroll-aware stuck detection | Exp 10 | `4d34b37` |
| Relaxed coordinate validation (y<100) | Exp 12 | `705b05c` |
| Action confirmation feedback (default=True) | Exp 15 | `2a4f5c2` |
| Smart wait after navigation (default=True) | Exp 16 | `29d028f` |

---

## Previous Milestone: MiniWoB++ BENCHMARK 91.7% ACHIEVED!

**Best Result: Run #13 - 91.7% (110/120 episodes)**

| Task | Score | Status |
|------|-------|--------|
| click-button-v1 | 100% (10/10) | EXCELLENT |
| click-checkboxes-v1 | 100% (7/7) | EXCELLENT |
| click-collapsible-v1 | 78% (7/9) | GOOD |
| click-dialog-v1 | 100% (10/10) | EXCELLENT |
| click-link-v1 | 100% (9/9) | EXCELLENT |
| click-option-v1 | 100% (9/9) | EXCELLENT |
| click-tab-v1 | 100% (10/10) | EXCELLENT |
| click-test-v1 | 100% (10/10) | EXCELLENT |
| enter-password-v1 | 100% (10/10) | EXCELLENT |
| enter-text-v1 | 90% (9/10) | EXCELLENT |
| focus-text-v1 | 100% (9/9) | EXCELLENT |
| login-user-v1 | 100% (10/10) | EXCELLENT |

### Score Progression Over All Runs
| Run | Score | Passes | Timeouts | Notes |
|-----|-------|--------|----------|-------|
| 1 | 55.8% | 67/120 | Many | Initial baseline |
| 2 | 73.3% | 88/120 | - | Added coordinate hints |
| 3 | 79.2% | 95/120 | - | Improved prompts |
| 4 | 85.8% | 103/120 | - | Added stuck detection |
| 5 | 82.5% | 99/120 | - | Variance |
| 6 | 87.5% | 105/120 | 0 | Good run |
| 7 | 84.2% | 101/120 | 16 | High variance |
| 8 | 88.3% | 106/120 | 9 | Previous best |
| 9 | 84.2% | 101/120 | 16 | Variance |
| 10 | 85.8% | 103/120 | 13 | Stable |
| 11 | 87.5% | 105/120 | 10 | Good |
| 12 | 80.0% | 96/120 | 20 | Low variance |
| **13** | **91.7%** | **110/120** | **7** | **TARGET ACHIEVED!** |

---

## MiniWoB++ Benchmark System

### Overview
The benchmark runner (`rpa_agent/benchmark/miniwob_runner.py`) tests the VLM agent on MiniWoB++ tasks using visual-only interaction. No DOM access or HTML parsing - just like a human user.

### Key Components

#### 1. MiniWoBBenchmarkRunner Class
```python
runner = MiniWoBBenchmarkRunner(
    model="claude-opus-4-20250514",  # VLM model
    max_steps=10,                     # Max actions per episode
    headless=True                     # Run without display
)

summary = runner.run_benchmark(
    task_list=["click-button-v1", "enter-text-v1", ...],
    num_episodes=10
)
```

#### 2. Image Processing
- **4x scaling**: Screenshots are scaled 4x for better VLM coordinate estimation
- **Y-coordinate clamping**: Max y=168 (MiniWoB++ clickable area limit)
- Screenshots converted to base64 PNG for VLM input

#### 3. Stuck Detection
Triggers after 2 identical consecutive actions:
- Detects clicks on text fields (should type instead)
- Detects checkbox repetition (should move to next checkbox)
- Detects collapsible content clicking (should click Submit)
- Provides specific guidance to break out of loops

### Running the Benchmark

```bash
cd C:/Users/guangyang/Documents/rpa

# Run full benchmark (12 tasks x 10 episodes)
uv run python -c "
from rpa_agent.benchmark.miniwob_runner import MiniWoBBenchmarkRunner

runner = MiniWoBBenchmarkRunner()
tasks = [
    'click-button-v1', 'click-checkboxes-v1', 'click-collapsible-v1',
    'click-dialog-v1', 'click-link-v1', 'click-option-v1',
    'click-tab-v1', 'click-test-v1', 'enter-password-v1',
    'enter-text-v1', 'focus-text-v1', 'login-user-v1'
]
summary = runner.run_benchmark(task_list=tasks, num_episodes=10)
"
```

---

## Running the Agent

### Sandbox Mode (primary mode)

```bash
# Start sandbox
python -m rpa_agent.cli sandbox up

# Run a task
python -m rpa_agent.cli sandbox run "Go to YouTube and search for cats" --max-steps 25 --model claude-opus-4.6-fast

# Check status
python -m rpa_agent.cli sandbox status

# View live (noVNC)
python -m rpa_agent.cli sandbox preview

# Stop sandbox
python -m rpa_agent.cli sandbox down
```

### CLI Options
- `--max-steps N`: Maximum VLM steps (default 50)
- `--model MODEL`: VLM model name
- `--base-url URL`: VLM API endpoint (default `http://localhost:23333/api/anthropic`)
- `--sandbox-url URL`: Sandbox API (default `http://localhost:8000`)
- `--delay SECS`: Delay between steps (default 0.5)
- `--no-screenshots`: Disable screenshot saving

---

## Files to Read First (in order)

1. This file (`HANDOFF.md`)
2. `rpa_agent/agent.py` - Core orchestration: screenshot pipeline, coordinate rescaling, stuck detection, validation
3. `rpa_agent/vlm/prompts.py` - VLM prompts (most impactful for accuracy)
4. `rpa_agent/vlm/client.py` - VLM API client configuration
5. `rpa_agent/sandbox/controller_linux.py` - XTEST-based input controller
6. `rpa_agent/cli.py` - CLI entry points and sandbox commands
7. `rpa_agent/benchmark/miniwob_runner.py` - MiniWoB++ benchmark runner

---

## Troubleshooting

### Sandbox Issues
- **Cannot connect**: Ensure Docker is running, `docker compose up -d rpa-sandbox`
- **Chrome not starting**: Check `http://localhost:8000/status` — if `chrome_running: false`, POST to `/chrome/start?url=about:blank`
- **Screen blank**: VNC at http://localhost:6080, check Xvfb process inside container

### VLM Issues
- **Coordinates off by ~30%**: Check if grid labels match visual positions. If image > 1568px was sent without pre-resize, the API silently downscales it.
- **VLM not responding**: Check API key / endpoint. Test with `python -m rpa_agent.cli test-vlm`
- **Address bar confusion**: VLM sometimes clicks y~60 for search boxes. The coordinate validation at y<140 catches this.

### XTEST Input Issues
- **Typing fails**: Check XTEST typing interval (currently 30ms). Chrome autocomplete can intercept fast typing.
- **BadRRModeError**: Use `display.flush()` instead of `display.sync()` in XTEST code.
- **Mouse drift**: Should be 0 drift. If nonzero, check Xvfb resolution matches 1920x1080.

### MiniWoB++ Issues
- **Environment not found**: `pip install miniwob` or `uv add miniwob`
- **Timeout issues**: Ensure `core.EPISODE_MAX_TIME = 120000` runs after reset
- **High variance**: Normal range 80-92%, run multiple times

---

## Known Issues

1. **Google CAPTCHA**: Google triggers CAPTCHA in the sandbox environment. Use DuckDuckGo or YouTube for search tests.
2. **Address bar confusion**: VLM occasionally misidentifies the Chrome address bar as a web page search box. The y<140 coordinate validation mitigates this but not perfectly (e.g., YouTube search bar is at y~114 which is legitimately in browser chrome area).
3. **VLM coordinate variance**: Even with the grid overlay, the VLM can be off by 20-50px on average. Larger elements are more reliably hit.

---

## Next Steps

### Immediate — Merge & Ship
1. **Merge winning experiments to main**: JPEG q75 1024px (Exp 5) + Ctrl+L prompt (Exp 6) should be merged to main branch
2. **Bake Ctrl+L prompt into default prompt**: Currently requires `build_enhanced_prompt()` — should be the default in `SystemPrompts.GUI_AGENT`

### Immediate — More Experiments
3. **Larger test suite**: Add harder tasks (multi-tab, form filling, file download) to validate improvements generalize
4. **Per-phase retry** (from UI-TARS): Independent retry for screenshot/VLM/execute — low effort, high reliability
5. **Dual screenshot (before + after)**: Send VLM both pre-action and post-action screenshots so it can verify its last action worked
6. **Smarter stuck detection**: Use VLM's assessment of "did my action work?" instead of just coordinate clustering

### Medium-Term
7. **OSWorld / WebArena benchmarks**: Standardized evaluation beyond MiniWoB++
8. **SoM (Set of Marks) element highlighting**: Overlay clickable element bounding boxes on screenshots before sending to VLM
9. **Multi-step planning**: VLM generates a plan before execution, executes step by step
10. **Adaptive image quality**: Use higher quality JPEG only when VLM reports uncertainty about coordinates

### Long-Term
11. **Fine-tuned grounding model**: Like UI-TARS, train a model specifically for GUI coordinate grounding
12. **DOM-assisted grounding**: Optionally use CDP to get element positions and augment VLM context
13. **Continuous iteration following 格物致知 principles**

---

## Performance Summary

### Optimized vs Baseline (Session 10, Exp 7)
| Metric | Baseline (PNG 1344) | Optimized (JPEG 1024 + Ctrl+L) | Improvement |
|--------|--------------------|---------------------------------|-------------|
| Success Rate | 100% (3/3) | 100% (3/3) | — |
| Avg Steps | 10.7 | 7.3 | **-31%** |
| Avg Input Tokens | 6,311,382 | 905,866 | **-86%** |
| Avg Wall Time | 49.1s | 27.0s | **-45%** |

### Real-World Tasks (Session 8-10)
| Task | Steps | Result |
|------|-------|--------|
| YouTube - play liked video | 7/7 | SUCCESS |
| DuckDuckGo search | 7/20 (optimized) | SUCCESS |
| Google search | 8/20 (optimized) | SUCCESS |
| Multi-step search + scroll | 7/20 (optimized) | SUCCESS |

### MiniWoB++ Benchmark (12 tasks)
| Metric | Value |
|--------|-------|
| Best Score | 91.7% (110/120) |
| Average Score | ~85% |
| Tasks at 100% | 10/12 |
| Main Bottleneck | click-collapsible (78%) |

### Mouse Accuracy (XTEST controller)
| Metric | Value |
|--------|-------|
| Hit Rate | 100% |
| Drift | 0px on 10 test points |
| Latency | ~1ms per move |

---

## Important Notes

1. **Coordinate System**: (0,0) is top-left, X increases right, Y increases down
2. **Screenshot resize**: 1920x1080 → 1344x756 (scale 0.7), grid labels in original coords
3. **Rescale factor**: `_vlm_scale_factor = 1920/1344 ≈ 1.4286` applied to all VLM coordinates
4. **Browser chrome height**: ~140px (tabs + address bar + bookmarks)
5. **VLM Model**: `claude-opus-4.6-fast` (custom endpoint) or `claude-opus-4-20250514` (Anthropic API)
6. **XTEST typing interval**: 30ms between keystrokes (Chrome autocomplete resilience)
7. **MiniWoB++ Screen Size**: 160x210 pixels (original), 640x840 (4x scaled for MiniWoB benchmark)
8. **MiniWoB++ Episode Timeout**: 120 seconds (increased from default 10s)
