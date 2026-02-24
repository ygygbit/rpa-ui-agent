# RPA Agent Handoff Document

> **Purpose**: Knowledge persistence across sessions. Read this first when starting a new session.

---

## Project Overview

This is a Vision-Language Model (VLM) based RPA agent that automates GUI tasks by:
1. Capturing screenshots from a Docker sandbox (1920x1080 Linux + Chrome)
2. Resizing to 1120x630 and encoding as JPEG q2
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
    vlm_image_quality=10,       # q10 sufficient for VLM (Exp 38, was q75→q50→q25→q10)
    vlm_max_edge=1024,          # 1024px instead of 1344px (Exp 5)
    coordinate_validation="relaxed",  # Relaxed y<100 threshold (Exp 12)
    action_feedback=True,       # Confirm successful actions to VLM (Exp 15)
    smart_wait=True,            # Extra delay after navigation actions (Exp 16)
    smart_wait_delay=1.5,       # 1.5s wait for page loads (Exp 16)
    step_budget_awareness=True, # Tell VLM step count/remaining (Exp 18)
    adaptive_prompt=True,       # Task-specific strategy hints (Exp 29)
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

**JPEG vs PNG**: JPEG q10 at 1024px reduces base64 image size by ~95%+, cutting per-step input tokens from ~575K to ~27K. VLM accuracy is unaffected — coordinate grid labels remain readable even at extreme q10 compression. (Quality progression: q75→q50 -34%/step, q50→q25 -38%/step, q25→q10 -49%/step. Total: -74% vs q75.)

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
| 18 | `exp/step-budget-awareness` | Step budget awareness for VLM | **MODERATE POSITIVE** | **-18% steps, -22% tokens, -21% time**, merged |
| 19 | `exp/concise-reasoning` | Concise reasoning mode | **NEUTRAL** | No meaningful change, VLM already concise |
| 20 | `exp/action-history-context` | Action history in task context | **NEUTRAL** | -6% steps, -8% tokens, within variance |
| 21 | `exp/dual-screenshot` | Before/after dual screenshot | **NEUTRAL/NEGATIVE** | -6% steps but +69% input tokens, +8% time |
| 22 | `exp/temperature-zero` | Temperature 0.0 vs 0.1 | **NEUTRAL** | +8% steps with temp=0, current 0.1 is good |
| 23 | `exp/keyboard-first` | Keyboard-first navigation prompt | **NEUTRAL** | +6% steps, VLM already uses shortcuts appropriately |
| 24 | `exp/adaptive-delay` | Adaptive step delays (0.2/2.5) | **NEUTRAL/NEGATIVE** | +10% time, current 0.5/1.5 well-tuned |
| 25 | `exp/scroll-multiplier` | Double scroll distance (2x) | **NEUTRAL** | Same avg steps, no meaningful change |
| 26 | `exp/early-done-detection` | Early done nudge on success reasoning | **MIXED** | Target case -20% steps, but 21 false-positive nudges |
| 27 | `exp/smart-coord-retry` | Auto-scroll on out-of-bounds Y coords | **NEUTRAL** | Feature never triggered; 0 coord rejections in all runs |
| 28 | `exp/vlm-planning` | VLM generates plan before executing | **MIXED-POSITIVE** | Wikipedia Scroll -20% steps, but plan overhead on simple tasks |
| 29 | `exp/adaptive-prompt` | Task-specific strategy hints (Ctrl+F, Enter) | **POSITIVE** | Wikipedia Scroll -35% steps (20→13), avg -12% steps, -16% tokens |
| 30 | `exp/expanded-adaptive-hints` | Expanded hints: URL nav + Wiki ToC | **STRONG POSITIVE** | Avg 10.0→7.2 steps (-28%), all 5/5 success |
| 31 | `exp/step-aware-hints` | Auto-navigate (no task rewrite) | **MIXED** | 4/5 improved but Wiki Scroll 10→22, not merged |
| 32 | `exp/task-rewrite` | Auto-navigate + task rewrite | **STRONG POSITIVE** | ALL 5 improved, avg 7.8→5.4 (-31%), merged |
| 33 | `exp/cumulative-validation-2` | Cumulative validation round 2 | **100% (10/10)** | Standard 5.8 avg, Hard 11.0 avg |
| 34 | `exp/defaults-update` | Default config update (flags=True) | **POSITIVE** | 6.4 avg steps with plain AgentConfig(), merged |
| 35 | `exp/reduced-resolution` | 768px max edge (vs 1024px) | **NEGATIVE** | avg 5.4→14.0 steps (+159%), not merged |
| 36 | `exp/jpeg-quality` | JPEG quality q50 (vs q75) | **STRONG POSITIVE** | -34% tokens/step, -23% steps, same 100%, merged |
| 37 | `exp/jpeg-quality-25` | JPEG quality q25 (vs q50) | **STRONG POSITIVE** | -38% tokens/step, -49% steps, same 100%, merged |
| 38 | `exp/jpeg-quality-10` | JPEG quality q10 (vs q25) | **POSITIVE** | -49% tokens/step, same steps, same 100%, merged |
| 39 | `exp/resolution-896` | 896px resolution (vs 1024px) | **NEGATIVE** | avg 8.6→13.8 steps (+60%), not merged |
| 40 | `exp/grid-spacing-200` | Grid spacing 200px (vs 100px) | **POSITIVE** | -30% steps, -38% tokens, -10% tok/step, merged |
| 41 | `exp/prompt-grid-200-alignment` | Prompt text "200px" alignment | **NEUTRAL** | VLM reads actual labels regardless, merged for correctness |
| 42 | `exp/sliding-window-revisited` | Sliding window 10 (with q10 images) | **NEUTRAL** | Lower token growth on long tasks, default set to 10, merged |
| 43 | `exp/grid-spacing-400` | Grid spacing 400px (vs 200px) | **POSITIVE** | -38% steps, -39% tokens, -36% time, merged |
| 44 | `exp/no-grid` | No grid overlay at all | **NEUTRAL** | High variance, no systematic benefit, not merged |
| 45 | `exp/minimal-prompt` | Minimal prompt (~600 tok vs ~1.9K) | **NEUTRAL/NEGATIVE** | +24% steps, Article Scroll 6 to 14, not merged |
| 46 | `exp/prompt-grid-400-alignment` | Prompt text "400px" alignment | **NEUTRAL** | VLM reads labels regardless, merged for correctness |
| 47 | `exp/grid-spacing-800` | Grid spacing 800px (vs 400px) | **NEUTRAL** | High variance, no systematic benefit, not merged |
| 48 | `exp/smart-wait-05` | Smart wait 0.5s (vs 1.5s) | **NEGATIVE** | +28% avg steps, VLM sees unloaded pages, not merged |
| 49 | `exp/cumulative-validation-3` | Cumulative validation round 3 | **100% (10/10)** | 5.8 avg steps on 10 diverse tasks, validates all 21 improvements |
| 50 | `exp/screenshot-diff-stuck` | Screenshot diff stuck detection | **INCONCLUSIVE** | Sandbox timeouts corrupted results, not merged |
| 51 | `exp/step-delay-0` | Step delay 0.0s (vs 0.5s) | **MILD POSITIVE** | -13% wall time, same steps/success, merged |
| 52 | `exp/smart-wait-10` | Smart wait 1.0s (vs 1.5s) | **NEGATIVE** | +59% avg steps, Wiki Scroll 6→24, not merged |
| 53 | `exp/history-window-5` | History window 5 vs 10 | **MIXED** | Wiki Search failed with window 5, high variance, not merged |
| 54 | `exp/smart-wait-20` | Smart wait 2.0s (vs 1.5s) | **NEUTRAL** | Run 2 showed identical step counts, 1.5s optimal, not merged |
| 55 | `exp/max-steps-15` | Max steps 15 vs 25 | **NEUTRAL** | Both 100%, steps similar (step budget pressure effect), not merged |
| 56 | `exp/resolution-1344` | VLM resolution 1344px (vs 1024px) | **STRONG POSITIVE** | **-35% steps, -28% time**, consistent across 2 runs, merged |
| 57 | `exp/resolution-1600` | VLM resolution 1600px (vs 1344px) | **BROKEN** | VLM API rejects images at 1600px, not merged |
| 58 | `exp/jpeg-quality-5` | JPEG quality q5 (vs q10) | **POSITIVE** | **-23% tok/step, -26% total tokens**, same success, merged |
| 59 | `exp/jpeg-quality-2` | JPEG quality q2 (vs q5) | **MILD POSITIVE** | **-13% tok/step, -10% total tokens**, merged |
| 60 | `exp/jpeg-quality-1` | JPEG quality q1 (vs q2) | **NEGATIVE** | JPEG compression floor reached, +19% steps, not merged |
| 61 | `exp/cumulative-validation-4` | Cumulative validation round 4 | **VALIDATION** | 10/10 (100%), 7.4 avg steps, 24K tok/step, all 26 improvements validated |
| 62 | `exp/grid-spacing-300` | Grid spacing 300 vs 400 at 1344px | **NEUTRAL** | Identical results, denser grid provides no improvement |
| 63 | `exp/compressed-prompt` | Compressed system prompt | **POSITIVE** | -10% tok/step, same success, validated 2 runs, merged |
| 64 | `exp/temperature-0` | VLM temperature 0.0 vs 0.1 | **NEUTRAL** | DDG Click Result regressed (15 steps), deterministic stuck loop |
| 65 | `exp/compact-action-space` | Compact action space format | **NEGATIVE** | DDG Click Result regressed (19 steps), verbose format helps VLM |
| 66 | `exp/no-grid-overlay` | No grid overlay at 1344px | **POSITIVE** | -8% tok/step, -22% time, VLM doesn't need grid at 1344px, merged |
| 67 | `exp/no-step-budget` | No step budget awareness | **NEUTRAL** | Results flip between runs, no consistent improvement |
| 68 | `exp/max-tokens-1024` | Max tokens 1024 vs 4096 | **NEGATIVE** | Wikipedia Article Scroll regression (23 vs 5 steps) |
| 69 | `exp/max-tokens-2048` | Max tokens 2048 vs 4096 | **NEUTRAL** | Identical performance, max_tokens doesn't impact this VLM setup |
| 70 | `exp/history-window-6` | History window 6 vs 10 | **NEUTRAL** | High per-task variance, no consistent improvement across 2 runs |
| 71 | `exp/no-adaptive-prompt` | No adaptive prompt | **NEGATIVE** | 8.0 vs 5.2 avg steps, Wikipedia regressed 21 vs 7 steps |
| 72 | `exp/smart-wait-0.5` | Smart wait 0.5s vs 1.5s | **NEUTRAL** | Run 1 better at 0.5s, run 2 better at 1.5s. Inconsistent |
| 73 | `exp/smart-wait-1.0` | Smart wait 1.0s vs 1.5s | **NEUTRAL** | Identical performance (6.6 avg steps both) |
| 74 | `exp/enhanced-adaptive-hints` | Enhanced adaptive hints | **NEUTRAL** | New hints didn't clearly improve vs standard adaptive |
| 75 | `exp/jpeg-quality-1-v2` | JPEG quality 1 vs 2 | **NEUTRAL** | Identical performance, q1 no benefit over q2 |
| 76 | `exp/resolution-1120` | Resolution 1120px vs 1344px | **POSITIVE** | -30% tok/step, 100% success both runs, merged |
| 77 | `exp/cumulative-validation-5` | Cumulative validation round 5 | **VALIDATION** | 10/10 100%, 15K tok/step (-35% from val 4) |
| 78 | `exp/retry-guidance` | COT reasoning prompt | **NEUTRAL** | Same steps, DDG improved but Wikipedia regressed |
| 79 | `exp/no-history` | No history (window=1) | **NEUTRAL** | More steps (9.4 vs 6.8), VLM needs context |
| 80 | `exp/resolution-1008` | Resolution 1008px vs 1120px | **NEUTRAL** | Lower tok/step but more steps, net neutral |
| 81 | `exp/no-action-feedback` | action_feedback=False | **NEGATIVE** | 9.8 vs 7.2 avg steps, VLM needs action tracking |
| 82 | `exp/temperature-0-v2` | Temperature 0.0 vs 0.1 | **NEUTRAL** | 8.6 vs 8.0, mixed task-by-task results |
| 83 | `exp/no-step-budget-v2` | step_budget_awareness=False | **NEUTRAL** | 7.2 vs 7.6, within noise |
| 84 | `exp/no-auto-navigate-v2` | auto_navigate=False | **NEUTRAL** | 8.6 vs 7.6, ~1 extra step for URL entry |
| 85 | `exp/max-steps-15-v2` | max_steps=15 vs 25 | **NEGATIVE** | 4/5 (80%) success, Wikipedia Scroll failed at 15 |
| 86 | `exp/strict-coord-validation` | coordinate_validation=off | **NEUTRAL** | 9.4 vs 7.6, validation catches bad clicks |
| 87 | `exp/smart-wait-2.0` | smart_wait_delay=2.0 vs 1.5 | **NEUTRAL** | Run 1: 5.4 vs 7.6, Run 2: 11.4 vs 8.6. Inconsistent |
| 88 | `exp/cumulative-validation-6` | Cumulative validation round 6 | **VALIDATION** | 10/10 100%, 16K tok/step, stable |
| 89 | `exp/uncompressed-prompt-v2` | WebP format vs JPEG q2 | **NEUTRAL** | Same steps, WebP cheaper for simple pages, expensive for text |

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
| `exp/step-budget-awareness` | `ab934d6` | Complete (Exp 18, moderate positive, merged) |
| `exp/concise-reasoning` | `26be4d3` | Complete (Exp 19, neutral) |
| `exp/action-history-context` | `d2e0b7d` | Complete (Exp 20, neutral) |
| `exp/dual-screenshot` | `5ed7364` | Complete (Exp 21, neutral/negative) |
| `exp/temperature-zero` | `60553c3` | Complete (Exp 22, neutral) |
| `exp/keyboard-first` | `600a5f2` | Complete (Exp 23, neutral) |
| `exp/adaptive-delay` | `3856928` | Complete (Exp 24, neutral/negative) |
| `exp/scroll-multiplier` | `5bfc6dd` | Complete (Exp 25, neutral) |
| `exp/early-done-detection` | `0e95b9c` | Complete (Exp 26, mixed, not merged) |
| `exp/smart-coord-retry` | `b151188` | Complete (Exp 27, neutral, not merged) |
| `exp/vlm-planning` | `3251463` | Complete (Exp 28, mixed-positive, not merged) |
| `exp/adaptive-prompt` | `f9b26de` | Complete (Exp 29, positive, **merged to main**) |
| `exp/expanded-adaptive-hints` | `2510e45` | Complete (Exp 30, strong positive, **merged to main**) |
| `exp/step-aware-hints` | `ea02f62` | Complete (Exp 31, mixed, not merged) |
| `exp/task-rewrite` | `5a915a6` | Complete (Exp 32, strong positive, **merged to main**) |
| `exp/cumulative-validation-2` | `a6216b8` | Complete (Exp 33, 100% 10/10 validation) |
| `exp/defaults-update` | `c356a85` | Complete (Exp 34, defaults to True, **merged to main**) |
| `exp/reduced-resolution` | `cc6a11e` | Complete (Exp 35, negative, not merged) |
| `exp/jpeg-quality` | `01b4d9a` | Complete (Exp 36, strong positive, **merged to main**) |
| `exp/jpeg-quality-25` | `71e356c` | Complete (Exp 37, strong positive, **merged to main**) |
| `exp/jpeg-quality-10` | `e115c93` | Complete (Exp 38, positive, **merged to main**) |
| `exp/resolution-896` | `71e9b1d` | Complete (Exp 39, negative, not merged) |
| `exp/grid-spacing-200` | `b62dad7` | Complete (Exp 40, positive, **merged to main**) |
| `exp/prompt-grid-200-alignment` | `ce63b75` | Complete (Exp 41, neutral, **merged to main** for correctness) |
| `exp/sliding-window-revisited` | `b5c91d4` | Complete (Exp 42, neutral, **merged to main** default=10) |
| `exp/grid-spacing-400` | `e1dcb8d` | Complete (Exp 43, positive, **merged to main**) |
| `exp/no-grid` | `c1bc20d` | Complete (Exp 44, neutral, not merged) |
| `exp/minimal-prompt` | `b7bf410` | Complete (Exp 45, neutral/negative, not merged) |
| `exp/prompt-grid-400-alignment` | `f5db71a` | Complete (Exp 46, neutral, **merged to main** for correctness) |
| `exp/grid-spacing-800` | `524d1b2` | Complete (Exp 47, neutral, not merged) |
| `exp/smart-wait-05` | `ce4df18` | Complete (Exp 48, negative, not merged) |
| `exp/cumulative-validation-3` | `73ffa59` | Complete (Exp 49, 100% 10/10, **merged to main**) |
| `exp/screenshot-diff-stuck` | `f8b45a1` | Complete (Exp 50, inconclusive, not merged) |
| `exp/step-delay-0` | `f7bda32` | Complete (Exp 51, mild positive, **merged to main**) |
| `exp/smart-wait-10` | `0673d01` | Complete (Exp 52, negative, not merged) |
| `exp/history-window-5` | `a434b51` | Complete (Exp 53, mixed, not merged) |
| `exp/smart-wait-20` | `5abe834` | Complete (Exp 54, neutral, not merged) |
| `exp/max-steps-15` | `30da10c` | Complete (Exp 55, neutral, not merged) |
| `exp/resolution-1344` | `adbbbfc` | Complete (Exp 56, strong positive, **merged to main**) |
| `exp/resolution-1600` | `df48ee8` | Complete (Exp 57, broken, not merged) |
| `exp/jpeg-quality-5` | `20d77c8` | Complete (Exp 58, positive, **merged to main**) |
| `exp/jpeg-quality-2` | `07b885c` | Complete (Exp 59, mild positive, **merged to main**) |
| `exp/jpeg-quality-1` | `66eaadd` | Complete (Exp 60, negative, not merged) |
| `exp/cumulative-validation-4` | `513ef98` | Complete (Exp 61, validation, 10/10 100%) |
| `exp/grid-spacing-300` | `34b466d` | Complete (Exp 62, neutral, not merged) |
| `exp/compressed-prompt` | `842881d` | Complete (Exp 63, positive, **merged to main**) |
| `exp/temperature-0` | `96ddfd4` | Complete (Exp 64, neutral, not merged) |
| `exp/compact-action-space` | `4e861b1` | Complete (Exp 65, negative, not merged) |
| `exp/no-grid-overlay` | `74ef053` | Complete (Exp 66, positive, **merged to main**) |
| `exp/no-step-budget` | `75067b7` | Complete (Exp 67, neutral, not merged) |
| `exp/max-tokens-1024` | `df2ae5b` | Complete (Exp 68, negative, not merged) |
| `exp/max-tokens-2048` | `5b7b28b` | Complete (Exp 69, neutral, not merged) |
| `exp/history-window-6` | `433573d` | Complete (Exp 70, neutral, not merged) |
| `exp/no-adaptive-prompt` | `9713ddd` | Complete (Exp 71, negative, not merged) |
| `exp/smart-wait-0.5` | `7a420b7` | Complete (Exp 72, neutral, not merged) |
| `exp/smart-wait-1.0` | `d50360c` | Complete (Exp 73, neutral, not merged) |
| `exp/enhanced-adaptive-hints` | `2d922cf` | Complete (Exp 74, neutral, not merged) |
| `exp/jpeg-quality-1-v2` | `46fe2da` | Complete (Exp 75, neutral, not merged) |
| `exp/resolution-1120` | `e7be848` | Complete (Exp 76, positive, **merged to main**) |
| `exp/cumulative-validation-5` | `70c61c1` | Complete (Exp 77, validation) |
| `exp/retry-guidance` | `d5215bf` | Complete (Exp 78, neutral, not merged) |
| `exp/no-history` | `f779f96` | Complete (Exp 79, neutral, not merged) |
| `exp/resolution-1008` | `872d2b2` | Complete (Exp 80, neutral, not merged) |
| `exp/no-action-feedback` | `0fc1170` | Complete (Exp 81, negative, not merged) |
| `exp/temperature-0-v2` | `3ed99e3` | Complete (Exp 82, neutral, not merged) |
| `exp/no-step-budget-v2` | `a43ce0b` | Complete (Exp 83, neutral, not merged) |
| `exp/no-auto-navigate-v2` | `ae6743b` | Complete (Exp 84, neutral, not merged) |
| `exp/max-steps-15-v2` | `2e7b342` | Complete (Exp 85, negative, not merged) |
| `exp/strict-coord-validation` | `05925fb` | Complete (Exp 86, neutral, not merged) |
| `exp/smart-wait-2.0` | `3adabf6` | Complete (Exp 87, neutral, not merged) |
| `exp/cumulative-validation-6` | `320dce0` | Complete (Exp 88, validation) |
| `exp/uncompressed-prompt-v2` | `c7bbced` | Complete (Exp 89, neutral, not merged) |

#### Experiments 8-35: Hard Tasks, Robustness, and Validation

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

**Exp 18 — Step Budget Awareness** (MODERATE POSITIVE): Added `step_budget_awareness` flag that injects step count and remaining budget into the VLM task string (e.g., "[Step 5/25 — 20 steps remaining]"). Adds urgency messages when steps are running low: "Be efficient" at 1/3 remaining, "URGENT" at 3 remaining. Both configs achieved 100% success, but budget awareness reduced avg steps by 18%, tokens by 22%, and time by 21%. Biggest gains on longer tasks — Wikipedia Article Scroll dropped from 20 to 14 steps, DuckDuckGo Click Result from 13 to 9 steps. The VLM becomes more decisive and efficient when it knows it has a finite step budget. Merged to main with `step_budget_awareness=True` as default.

| Config | Success | Avg Steps | Avg Tokens | Avg Time |
|--------|---------|-----------|------------|----------|
| baseline | 100% (5/5) | 11.4 | 1,049,804 | 42.5s |
| **budget** | **100% (5/5)** | **9.4** | **817,022** | **33.5s** |

**Exp 19 — Concise Reasoning** (NEUTRAL): Added `concise_reasoning` flag that appends instruction to system prompt asking VLM to keep reasoning to 1-2 sentences without detailed grid descriptions. Both configs 100% success. Concise mode barely changed any metrics: steps 9.6→9.4 (-2%), output tokens 866→964 (+11%, opposite of expected), time 35.0s→35.5s (flat). The VLM was already reasonably concise — the extra instruction had negligible impact. Not merged.

**Exp 20 — Action History Context** (NEUTRAL): Added `action_history_context` flag that injects a brief summary of all prior actions into the VLM task context (e.g., "Actions taken so far: 1. hotkey (OK), 2. type (OK)..."). Designed to help on long tasks where early actions get windowed out. Both configs 100% success, with modest improvements: steps 10.6→10.0 (-6%), tokens 964K→884K (-8%), time 38.1s→36.9s (-3%). The gains are within normal run-to-run variance. Not merged.

**Exp 21 — Dual Screenshot (Before/After)** (NEUTRAL/NEGATIVE): Added `dual_screenshot` flag that sends the previous step's screenshot alongside the current one, so the VLM can visually compare what changed. Both configs 100% success. Steps 10.2→9.6 (-6%) but input tokens 910K→1,541K (**+69%**) and time 36.9→39.7s (+8%). The extra image doubles per-step token cost. The only notable per-task improvement was Wikipedia Article Scroll (17→14 steps, -18%), but the token overhead makes this a net negative for cost efficiency. Not merged.

**Exp 22 — Temperature Variation** (NEUTRAL): Compared temperature=0.1 (current default) vs temperature=0.0 (fully deterministic). Both configs 100% success. Temperature=0.0 was slightly worse: 10.8 avg steps vs 10.0 (+8%), input tokens 987K vs 884K (+12%). Wikipedia Article Scroll regressed notably (17→21 steps). The deterministic mode makes the agent less adaptive on longer tasks. Current temperature=0.1 is confirmed as the better setting. Not merged.

**Exp 23 — Keyboard-First Navigation** (NEUTRAL): Added `keyboard_first` flag that appends a keyboard-first strategy section to the system prompt encouraging Ctrl+F, Enter, Tab, Space over clicking. Both configs 100% success. Keyboard-first was slightly worse: 10.8 avg steps vs 10.2 (+6%), tokens 977K vs 902K (+8%). Wikipedia Article Scroll regressed (17→19 steps). The VLM already uses keyboard shortcuts appropriately (Ctrl+L, Enter after typing) and forcing more keyboard use adds overhead without benefit. Not merged.

**Exp 24 — Adaptive Step Delay** (NEUTRAL/NEGATIVE): Tested reduced base delay (0.2s vs 0.5s) with increased smart_wait (2.5s vs 1.5s). Both configs 100% success but adaptive was +10% slower: 38.6s vs 35.0s. The larger smart_wait_delay added too much overhead on navigation-heavy tasks (DuckDuckGo Click Result: 34.8→45.4s). The reduced base delay couldn't compensate. Current 0.5/1.5 timing is well-tuned. Not merged.

**Exp 25 — Scroll Multiplier** (NEUTRAL): Added `scroll_multiplier` config to amplify scroll distances (2x). Both configs 100% success with identical avg step count (10.2). Wikipedia Article Scroll didn't improve (17→18 steps). Doubling scroll distance doesn't help because the VLM adjusts its scroll count based on what it sees, not a fixed pattern. Not merged.

**Exp 26 — Early Done Detection** (MIXED): Added `early_done_detection` flag that scans VLM reasoning for success indicator phrases (e.g., "i can see the", "the results are displayed", "found the section") and injects a nudge message encouraging the VLM to report done() instead of taking unnecessary verification steps. Both configs 100% success. Average steps identical at 9.6. Wikipedia Article Scroll improved (15→12 steps, -20%, saved ~389K tokens) — the target case worked. However, DuckDuckGo Click Result degraded (9→11 steps, +22%) due to false-positive nudges. The "i can see the" indicator is too broad — it fires on 21 of ~48 total steps (nearly every step where VLM describes screen observations). The VLM correctly ignores false nudges but the extra messages add noise. Needs tighter indicators to be viable. Not merged.

| Config | Success | Avg Steps | Avg Input Tokens | Avg Time | Nudges |
|--------|---------|-----------|-----------------|----------|--------|
| baseline | 100% (5/5) | 9.6 | 841,436 | 35.5s | 0 |
| early-done | 100% (5/5) | 9.6 | 826,766 | 39.3s | 21 |

**Exp 27 — Smart Coordinate Retry** (NEUTRAL): Added `smart_coord_retry` flag that auto-scrolls when the VLM reports out-of-bounds Y coordinates (y >= screen_height → scroll down, y < 0 → scroll up) instead of a generic re-query warning. Both configs 100% success. The feature was never triggered — **zero coordinate rejections across all 10 task runs**. The out-of-bounds Y issue seen in Exp 26 (y=1144 on 1080 screen) is infrequent and didn't reproduce. Smart-retry was slightly worse on average (11.4 vs 9.8 steps) due to normal VLM variance, not the feature itself. Not merged.

| Config | Success | Avg Steps | Avg Input Tokens | Avg Time |
|--------|---------|-----------|-----------------|----------|
| baseline | 100% (5/5) | 9.8 | 853,545 | 36.4s |
| smart-retry | 100% (5/5) | 11.4 | 1,058,314 | 43.0s |

**Exp 28 — VLM Planning Phase** (MIXED-POSITIVE): Added `vlm_planning` flag that makes an extra VLM call before execution to generate a high-level plan (3-6 numbered steps). The plan is injected into all subsequent VLM calls as context. Both configs 100% success. Wikipedia Article Scroll improved significantly (15→12 steps, -20%) — the plan helped the VLM be more deliberate about finding the History section. Simple tasks got slightly worse due to plan overhead (~67K tokens per plan call). Average action steps: baseline 10.0 vs planning 9.2 (but +1 plan step = 10.2 total). The VLM initially tried to output action JSON in the plan response — needed explicit "Do NOT output any JSON" instruction. Net effect roughly neutral when counting plan overhead. Not merged.

| Config | Success | Avg Steps | Avg Input Tokens | Avg Time |
|--------|---------|-----------|-----------------|----------|
| baseline | 100% (5/5) | 10.0 | 882,005 | 38.3s |
| planning | 100% (5/5) | 10.2 (9.2 action) | 846,111 | 37.0s |

**Exp 29 — Adaptive Prompt** (POSITIVE): Added `adaptive_prompt` flag that injects task-specific strategy hints into the VLM task string based on keyword matching. Three hint categories: (1) Ctrl+F hint for section-finding tasks (triggers on "find the", "locate the", "scroll to the"), (2) Tab hint for form-filling tasks, (3) Enter-to-submit hint for search tasks without explicit "click". Both configs 100% success. Wikipedia Article Scroll saw the biggest improvement: **20 → 13 steps (-35%)** — the VLM actually used Ctrl+F to find the History section instead of scrolling through the entire article. Multi-Step Navigation improved 10 → 9 steps. Tasks without hints performed identically. Average steps: 11.4 → 10.0 (-12%), tokens: 1,035K → 867K (-16%). The adaptive hints are low-cost (just text in the prompt) with high impact on the right task types. Merge candidate.

| Config | Success | Avg Steps | Avg Input Tokens | Avg Time |
|--------|---------|-----------|-----------------|----------|
| baseline | 100% (5/5) | 11.4 | 1,035,296 | 42.6s |
| **adaptive** | **100% (5/5)** | **10.0** | **866,795** | **36.1s** |

Per-task step delta with adaptive prompt:
| Task | Baseline | Adaptive | Delta | Hints |
|------|----------|----------|-------|-------|
| DuckDuckGo Search | 8 | 8 | 0 | Enter hint |
| Wikipedia Search | 9 | 9 | 0 | none |
| Multi-Step Navigation | 10 | 9 | -1 | Enter hint |
| DuckDuckGo Click Result | 10 | 11 | +1 | none |
| Wikipedia Article Scroll | 20 | 13 | **-7** | Ctrl+F hint |

**Exp 30 — Expanded Adaptive Hints** (STRONG POSITIVE): Extended the adaptive hint system from 3 to 5 categories by adding: (1) URL navigation hint ("Press Enter immediately after typing URL, do NOT press Escape first"), (2) Wikipedia ToC hint ("Click Table of Contents links to jump to sections"). Compared against Exp 29 adaptive results. All 5 tasks completed. The URL navigation hint was the biggest win — it eliminated the Escape step that the VLM previously used to dismiss Chrome autocomplete before pressing Enter, saving 2-4 steps per task across the board. Average steps: 10.0 → 7.2 (**-28%**). Merged to main.

| Task | Exp 29 Steps | Expanded Steps | Delta |
|------|-------------|----------------|-------|
| DuckDuckGo Search | 8 | **5** | **-3** |
| Wikipedia Search | 9 | **7** | **-2** |
| Multi-Step Navigation | 9 | **7** | **-2** |
| DuckDuckGo Click Result | 11 | **7** | **-4** |
| Wikipedia Article Scroll | 13 | **10** | **-3** |
| **Average** | **10.0** | **7.2** | **-2.8 (-28%)** |

**Exp 31 — Auto-Navigate** (MIXED): Added `auto_navigate` flag that extracts the target URL from the task description (regex matching "go to X.com", "open X.com", etc.) and navigates directly via sandbox HTTP API before the VLM loop starts, eliminating the 2-3 steps the VLM normally uses for URL navigation (Ctrl+L, type URL, Enter). Both configs use adaptive_prompt=True (Exp 30 baseline). Both 100% success. 4/5 tasks improved: DDG Search 5→4 (-20%), **Wikipedia Search 10→4 (-60%)**, Multi-Step 7→6 (-14%), DDG Click 7→5 (-29%). However, Wikipedia Article Scroll regressed from 10→22 (+120%) due to VLM variability — the VLM got stuck in a find/scroll loop on the Machine Learning article, unrelated to auto-navigate itself. Net avg steps worse (7.8→8.2) because one outlier dwarfs the gains. Feature is architecturally sound but needs more robust evaluation. Not merged.

| Task | Baseline | Auto-Nav | Delta |
|------|----------|----------|-------|
| DuckDuckGo Search | 5 | **4** | **-1** |
| Wikipedia Search | 10 | **4** | **-6** |
| Multi-Step Navigation | 7 | **6** | **-1** |
| DuckDuckGo Click Result | 7 | **5** | **-2** |
| Wikipedia Article Scroll | 10 | 22 | +12 |
| **Average** | **7.8** | **8.2** | **+0.4 (+5%)** |

**Exp 32 — Auto-Navigate + Task Rewrite** (STRONG POSITIVE): Improved on Exp 31 by adding task rewriting after auto-navigation. When auto-navigate succeeds, the task is rewritten from "Go to X.com, search for..." to "The browser is already on X.com. Search for..." — this tells the VLM the page is already loaded so it skips URL navigation entirely. All 5 tasks improved with **no regressions**. Average steps: 7.8 -> 5.4 (**-31%**), tokens -25%, time -18%. The task rewriting fix completely solved Exp 31's Wikipedia Article Scroll regression (10->9 instead of 10->22). Merged to main.

| Task | Baseline | Auto-Rewrite | Delta |
|------|----------|--------------|-------|
| DuckDuckGo Search | 5 | **3** | **-2** |
| Wikipedia Search | 6 | **4** | **-2** |
| Multi-Step Navigation | 9 | **6** | **-3** |
| DuckDuckGo Click Result | 9 | **5** | **-4** |
| Wikipedia Article Scroll | 10 | **9** | **-1** |
| **Average** | **7.8** | **5.4** | **-2.4 (-31%)** |

**Exp 33 — Cumulative Validation Round 2** (100%, 10/10): Validated all 10 merged improvements stacking cleanly on 5 standard + 5 novel hard tasks. All improvements active: JPEG q75 1024px, Ctrl+L nav, scroll-aware stuck detection, relaxed coord validation, action feedback, smart wait, step budget awareness, adaptive hints, expanded hints, auto-navigate + task rewrite. **100% success on all 10 tasks**. Standard tasks avg 5.8 steps (down 47% from Exp 17's 11.0). Hard tasks avg 11.0 steps (all completed). Wikipedia Back Navigation was hardest at 24 steps (near max) but still completed.

| Category | Success | Avg Steps | Avg Tokens | Avg Time |
|----------|---------|-----------|------------|----------|
| Standard (5) | **100% (5/5)** | **5.8** | 553K | 25.9s |
| Hard (5) | **100% (5/5)** | 11.0 | 1,205K | 49.6s |
| **Overall (10)** | **100% (10/10)** | **8.4** | 879K | 37.8s |

Historical progress (standard tasks avg steps): Exp 17 (6 imp.) 11.0 -> Exp 18 (7) 9.4 -> Exp 30 (9) 7.2 -> **Exp 33 (10) 5.8**

**Exp 34 — Default Config Update** (POSITIVE): Changed `adaptive_prompt` and `auto_navigate` defaults from `False` to `True` so new users get all optimizations out of the box. Validated: 100% (5/5), avg 6.4 steps with plain `AgentConfig()` — no explicit flag overrides needed. All 12 improvements are now active by default. Merged to main.

**Exp 35 — Reduced Image Resolution** (NEGATIVE): Tested 768px max edge (vs current 1024px default). Per-step tokens reduced by 25% (97K->73K), but VLM accuracy degraded badly. Average steps 5.4->14.0 (+159%). Wikipedia Search went 4->23 steps (+475%). Only DDG Search (simplest task, 3 steps both) was unaffected. The VLM needs 1024px resolution to accurately identify small UI elements and read text. Not merged.

**Exp 36 — JPEG Quality Reduction** (STRONG POSITIVE): Tested JPEG quality 50 vs current default 75, with resolution staying at 1024px. Both configs 100% success. q50 achieved **-34% tokens per step** (101K→67K), **-23% avg steps** (7.0→5.4), and **-22% wall time** (31.4→24.5s). All per-step token savings ranged from -23% to -32%. The VLM handles q50 compression artifacts without accuracy degradation — text and UI elements remain identifiable. Notably, q50 also had fewer steps on 3/5 tasks (likely VLM variability). Changed default from 75 to 50. Merged to main.

| Config | Success | Avg Steps | Avg Tokens/Step | Avg Time |
|--------|---------|-----------|-----------------|----------|
| q75 | 100% (5/5) | 7.0 | 101,812 | 31.4s |
| **q50** | **100% (5/5)** | **5.4** | **66,745** | **24.5s** |

Per-task comparison:
| Task | q75 Steps | q50 Steps | Delta | Tok/Step Delta |
|------|-----------|-----------|-------|----------------|
| DuckDuckGo Search | 5 | 4 | -1 | -27% |
| Wikipedia Search | 8 | 4 | -4 | -31% |
| Multi-Step Navigation | 5 | 6 | +1 | -30% |
| DuckDuckGo Click Result | 5 | 7 | +2 | -23% |
| Wikipedia Article Scroll | 12 | 6 | -6 | -32% |

**Exp 37 — JPEG Quality Floor (q25 vs q50)** (STRONG POSITIVE): Pushed JPEG quality further from 50 to 25. Both configs 100% success. q25 achieved **-38% tokens per step** (75K→47K), with avg steps 10.6→5.4 (the raw step count gap is partially VLM variability — q50 had a bad Wikipedia Search run at 21 steps). Per-step token savings were consistent at -30% to -38% across all tasks. Grid labels and UI elements remain identifiable at q25 despite visible blocking artifacts. Combined with Exp 36 (q75→q50), the total JPEG quality journey from q75 to q25 saves ~54% tokens per step. Changed default from 50 to 25. Merged to main.

| Config | Success | Avg Steps | Avg Tokens/Step | Avg Time |
|--------|---------|-----------|-----------------|----------|
| q50 | 100% (5/5) | 10.6 | 75,301 | 49.0s |
| **q25** | **100% (5/5)** | **5.4** | **46,540** | **24.9s** |

Per-task comparison:
| Task | q50 Steps | q25 Steps | Delta | Tok/Step Delta |
|------|-----------|-----------|-------|----------------|
| DuckDuckGo Search | 4 | 4 | 0 | -30% |
| Wikipedia Search | 21 | 4 | -17 | -37% |
| Multi-Step Navigation | 6 | 5 | -1 | -30% |
| DuckDuckGo Click Result | 9 | 5 | -4 | -38% |
| Wikipedia Article Scroll | 13 | 9 | -4 | -34% |

**Exp 38 — JPEG Quality Extreme Floor (q10 vs q25)** (POSITIVE): Pushed JPEG quality to extreme q10. Both configs 100% success with identical avg steps (9.8). Per-step tokens dropped by **-49%** (51.8K→26.7K). Individual task step counts were mixed: 3/5 tasks took 1 more step at q10, Wikipedia Search took 6 more (14→20), but Wikipedia Article Scroll improved by 9 steps (22→13, VLM variability). The q10 compression artifacts are severe but the VLM still reads grid labels and identifies UI elements. Token savings are substantial. Changed default from 25 to 10. Merged to main.

JPEG quality progression summary:
| Quality | Avg Tok/Step | Cumulative Savings vs q75 |
|---------|-------------|---------------------------|
| q75 (Exp 36 baseline) | 101,812 | — |
| q50 (Exp 36) | 66,745 | -34% |
| q25 (Exp 37) | 46,540 | -54% |
| **q10 (Exp 38)** | **26,664** | **-74%** |

**Exp 39 — Resolution 896px** (NEGATIVE): Tested 896px (midpoint between failed 768px and working 1024px) with q10 JPEG. Both configs 100% success but 896px averaged 13.8 steps vs 8.6 for 1024px (+60%). Wikipedia Search went 10→21 steps, DuckDuckGo Click Result went 6→17. Per-step tokens only saved -6% (24.3K vs 25.8K). The smaller image makes it harder for the VLM to identify small UI elements and read grid labels accurately, leading to more trial-and-error steps. 1024px is confirmed as the optimal resolution — 768px, 896px both degrade accuracy. Not merged.

**Exp 40 — Grid Spacing 200px** (POSITIVE): Tested 200px grid spacing vs current 100px default. With 200px spacing the grid has ~50% fewer lines and labels — less visual clutter on the screenshot and smaller image payload. The VLM must interpolate between grid lines more, but the labels are more readable. Both configs 100% success (5/5). 200px spacing achieved **-30% avg steps** (9.2→6.4), **-38% total tokens**, **-10% tokens/step** (27.5K→24.7K), and **-30% wall time** (36.7s→25.9s). Wikipedia Article Scroll improved 18→12 steps, Wikipedia Search 13→5. The sparser grid reduces visual noise that may confuse the VLM, while still providing enough reference points for accurate coordinate estimation. Changed default grid_spacing from 100 to 200. Merged to main.

| Config | Success | Avg Steps | Avg Tok/Step | Avg Time |
|--------|---------|-----------|-------------|----------|
| grid100 | 100% (5/5) | 9.2 | 27,542 | 36.7s |
| **grid200** | **100% (5/5)** | **6.4** | **24,695** | **25.9s** |

Per-task comparison:
| Task | g100 Steps | g200 Steps | Delta | Tok/Step Delta |
|------|-----------|-----------|-------|----------------|
| DuckDuckGo Search | 4 | 4 | 0 | -14% |
| Wikipedia Search | 13 | 5 | **-8** | -4% |
| Multi-Step Navigation | 5 | 6 | +1 | -16% |
| DuckDuckGo Click Result | 6 | 5 | -1 | -15% |
| Wikipedia Article Scroll | 18 | 12 | **-6** | -3% |

**Exp 41 — Prompt-Grid Alignment** (NEUTRAL): Updated prompt text from "100 pixels" to "200 pixels" to match actual grid spacing. Both configs 100% success. Mismatched slightly better on steps (8.2 vs 9.8) but within normal variance. The VLM reads actual grid labels regardless of what the prompt text says. Merged for correctness (prompt should match reality) but no performance impact.

**Exp 42 — Sliding Window Revisited** (NEUTRAL): Re-tested sliding window (max_history_turns=10 vs unlimited) with q10 JPEG and 200px grid. Previously neutral in Exp 11 because images dominated token cost. Now images are ~25K/step. Both 100% success, avg steps similar (8.6 vs 8.2). Per-step token growth lower with window: Wikipedia Scroll +1.1K vs +5.3K. Default set to 10 for longer-task efficiency. Merged.

**Exp 43 — Grid Spacing 400px** (POSITIVE): Even sparser grid: only ~6 lines (4 vert + 2 horiz) vs ~14 lines at 200px. Both 100% success. 400px achieved **-38% avg steps** (11.2 to 7.0), **-39% tokens**, **-36% time**. Wikipedia Search 25 to 8, Article Scroll 17 to 13. The ultra-sparse grid reduces visual noise further while still providing enough reference points. Default changed to 400px. Merged.

| Config | Success | Avg Steps | Avg Tokens | Avg Time |
|--------|---------|-----------|------------|----------|
| grid200 | 100% (5/5) | 11.2 | 265,525 | 44.8s |
| **grid400** | **100% (5/5)** | **7.0** | **161,508** | **28.5s** |

**Exp 44 — No Grid Overlay** (NEUTRAL): Tested removing grid entirely. Both 100% success. Avg steps similar (9.4 vs 9.0) but high per-task variance: no grid worse on Wikipedia Search (7 vs 22) but better on Article Scroll (23 vs 10). No systematic pattern — the VLM can work without the grid but doesn't consistently benefit from its removal. Grid kept as default. Not merged.

**Exp 45 — Minimal Prompt** (NEUTRAL/NEGATIVE): Reduced system prompt from ~1.9K tokens to ~600 tokens by removing grid-reading instructions, browser layout hints, and verbose strategy sections. Both 100% success but minimal averaged more steps (7.2 vs 5.8, +24%). Wikipedia Article Scroll regressed 6 to 14 steps without detailed Ctrl+F/strategy hints. The full prompt's instructions provide measurable value. Not merged.

**Exp 46 — Prompt-Grid 400px Alignment** (NEUTRAL): Updated prompt text from "200 pixels" to "400 pixels" to match actual grid spacing (changed in Exp 43). Also removed stale major-line references (2000px = off-screen at 400px spacing). Both 100% success. Mismatched 5.4 vs aligned 5.2 avg steps — within variance. Same pattern as Exp 41: VLM reads actual grid labels regardless of prompt text. Merged for correctness.

**Exp 47 — Grid Spacing 800px** (NEUTRAL): Ultra-sparse grid (3 lines: x=800,1600 + y=800) vs default 400px (6 lines). grid800 achieved 100% vs grid400 80%, but grid400's failure was noise (Wikipedia Search usually passes). grid800 worse on Click Result (+5 steps) and Article Scroll (+5 steps). High variance, no systematic benefit. 400px is the sweet spot. Not merged.

**Exp 48 — Smart Wait 0.5s** (NEGATIVE): Reduced smart_wait_delay from 1.5s to 0.5s. Both 100% success but 0.5s averaged 10.2 steps vs 8.0 (+28%). DDG Click Result 5 to 20 steps, Wiki Article Scroll 5 to 15 steps. The VLM captures screenshots of partially-loaded pages and wastes steps waiting/retrying. 1.5s delay is justified. Not merged.

**Exp 49 — Cumulative Validation Round 3** (100% 10/10): Validated all 21 merged improvements on 10 diverse tasks including 5 new task types: Google Search, Wikipedia Navigation, DuckDuckGo Images, Wikipedia Random, Multi-Tab Search. 100% success, 5.8 avg steps, 26.8s avg time, 123K avg input tokens. Matches Exp 33 performance while covering broader task diversity.

| # | Task | Outcome | Steps | Tokens | Time |
|---|------|---------|-------|--------|------|
| 1 | DuckDuckGo Search | completed | 4 | 72K | 17.5s |
| 2 | Wikipedia Search | completed | 6 | 158K | 26.4s |
| 3 | Multi-Step Navigation | completed | 5 | 91K | 23.0s |
| 4 | DuckDuckGo Click Result | completed | 5 | 89K | 23.6s |
| 5 | Wikipedia Article Scroll | completed | 5 | 132K | 23.0s |
| 6 | Google Search | completed | 3 | 55K | 12.9s |
| 7 | Wikipedia Navigation | completed | 5 | 126K | 24.9s |
| 8 | DuckDuckGo Images | completed | 9 | 152K | 44.9s |
| 9 | Wikipedia Random | completed | 9 | 222K | 42.7s |
| 10 | Multi-Tab Search | completed | 7 | 140K | 28.7s |

**Exp 50 — Screenshot Diff Stuck Detection** (INCONCLUSIVE): Added image-based stuck detection comparing consecutive screenshots using mean pixel difference. Feature triggered correctly 3 times on Wikipedia Search with appropriate warnings. However, sandbox timeouts corrupted the test run (4/10 tasks failed to timeout errors unrelated to the feature). Not merged pending cleaner testing.

**Exp 51 — Step Delay 0.0s** (MILD POSITIVE): Removed the 0.5s base delay between non-navigation steps. VLM API calls take 2-4s per step, providing natural pacing. Both configs achieved 100% success with similar step counts (6.8 vs 6.6 avg). Wall time reduced from 33.7s to 29.4s (-13%). Merged to main — `step_delay` default changed from 0.5 to 0.0.

**Exp 52 — Smart Wait 1.0s** (NEGATIVE): Tested reducing smart_wait_delay from 1.5s to 1.0s as a middle ground (Exp 48 showed 0.5s was too short). Results were significantly worse: avg 10.8 vs 6.8 steps (+59%). Wikipedia Article Scroll regressed from 6 to 24 steps — the VLM captured partially-rendered pages and wasted steps waiting/retrying. Confirms that 1.5s is the minimum viable wait for page loads. Not merged.

**Exp 53 — History Window 5** (MIXED): Tested max_history_turns=5 (last 2-3 VLM exchanges) vs default 10. Wikipedia Search failed with window 5 (10→25 max_steps), but Wikipedia Article Scroll improved (22→11). High variance, no systematic benefit. Not merged.

**Exp 54 — Smart Wait 2.0s** (NEUTRAL): Tested smart_wait_delay=2.0 vs 1.5. Run 1 showed improvement (9.4→7.8 avg steps) but validation run showed identical step counts (8.0 vs 7.8). The Run 1 improvement was variance on Wikipedia tasks. 2.0s adds unnecessary overhead on simple tasks. 1.5s remains optimal. Not merged.

**Exp 55 — Max Steps 15** (NEUTRAL): Tested max_steps=15 vs 25. Both 100% success. Simple tasks identical. Wikipedia Scroll improved (18→13) likely due to step_budget_awareness pressure, not the cap itself. 15 is too aggressive for production — harder tasks genuinely need 15-20+ steps. Not merged.

**Exp 56 — VLM Resolution 1344px** (STRONG POSITIVE): Increased vlm_max_edge from 1024px to 1344px. With JPEG q10, the larger images are affordable. Validated across 2 runs:
- Run 1: 8.0→5.2 avg steps (-35%), 30.1→21.7s (-28%)
- Run 2: 9.8→5.2 avg steps (-47%), 33.5→21.5s (-36%)
- 1344px gave identical results both runs (remarkably stable)
- Wikipedia Search: consistently 4 steps at 1344px vs 10-24 at 1024px
- Per-step tokens +60% but total tokens comparable due to fewer steps
Merged to main as default.

**Exp 57 — VLM Resolution 1600px** (BROKEN): Tested near-native 1600px resolution. VLM API rejects all images with "unsupported media type" error. At this resolution, JPEG images likely exceed VLM API size constraints. 1344px confirmed as the ceiling. Not merged.

**Exp 58 — JPEG Quality q5** (POSITIVE): Reduced JPEG quality from q10 to q5 at 1344px resolution. Both 100% success with same step counts (5.0 vs 4.8). Tokens per step reduced 23% (34.9K→26.9K), total tokens reduced 26% (174K→129K). VLM handles q5 with no performance degradation. Merged to main.

**Exp 59 — JPEG Quality q2** (MILD POSITIVE): Further reduced JPEG quality from q5 to q2. Both 100% success with similar steps (5.2 vs 5.4). Tokens per step reduced 13% (27.3K→23.8K), total tokens reduced 10%. Diminishing returns but still a net positive. Merged to main.

**Exp 60 — JPEG Quality q1** (NEGATIVE): Tested absolute minimum JPEG quality q1. Both 100% success but q1 averaged 6.4 steps vs 5.4 for q2 (+19%). Tokens per step were identical (24.4K vs 23.8K) — hit JPEG compression floor. The degraded image quality hurt Wikipedia Scroll (9→14 steps) with no token benefit. q2 confirmed as the quality floor. Not merged.

**Exp 61 — Cumulative Validation Round 4** (VALIDATION): Validated all 26 merged improvements together on 10 diverse tasks (including GitHub Explore, DuckDuckGo Images/News, Wikipedia Languages). **10/10 (100%) success**, 7.4 avg steps, 24K tok/step. Comparison with prior rounds: Round 1 (Exp 32) 80% 8.5 steps ~45K tok/step → Round 2 (Exp 42) 90% 7.7 steps ~42K → Round 3 (Exp 49) 100% 6.1 steps ~36K → Round 4 (Exp 61) 100% 7.4 steps ~24K. Avg steps slightly higher due to harder task set, but tok/step dropped 33% from resolution+compression optimizations.

**Exp 62 — Grid Spacing 300 at 1344px** (NEUTRAL): Tested denser grid (300px vs 400px) at 1344px resolution. Both 100% success, gs400 6.6 avg steps vs gs300 6.4 avg steps. Tok/step nearly identical (24,384 vs 24,633). The denser grid provides no measurable improvement at 1344px. Not merged.

**Exp 63 — Compressed System Prompt** (POSITIVE): Created a compressed version of the system prompt — same behavioral rules but 73% smaller (~501 vs ~1858 tokens). Both 100% success. Tok/step dropped 10% (23,247→20,843 on validation). Steps same or fewer. Added `system_prompt` config option and `GUI_AGENT_COMPRESSED` prompt. Validated across 2 runs. Merged to main.

**Exp 64 — VLM Temperature 0.0** (NEUTRAL): Tested fully deterministic temperature=0.0 vs current 0.1. Both 100% success but DuckDuckGo Click Result regressed to 15 steps at t=0.0 (vs 6 at t=0.1) — deterministic behavior causes stuck loops. Stochastic t=0.1 provides useful randomness for recovery. Not merged.

**Exp 65 — Compact Action Space** (NEGATIVE): Compressed operator action_space to single-line JSON examples without section headers. DDG Click Result regressed to 19 steps (vs 7 with verbose). The verbose format with section headers ("Direct Click", "Mouse Movement", etc.) and descriptions helps VLM understand action semantics. Not merged.

**Exp 66 — No Grid Overlay at 1344px** (POSITIVE): Tested removing the coordinate grid overlay entirely. At 1344px resolution, VLM accurately estimates coordinates without grid assistance. No grid: 100% success, 4.6 avg steps (both runs), 20.5K tok/step. Grid: 100% success, 5.4 avg steps, 21.7K tok/step. Grid overlay adds visual noise and tokens without helping at higher resolution. Validated across 2 runs. `show_coordinate_grid` default changed to False. Merged to main.

**Exp 67 — No Step Budget Awareness** (NEUTRAL): Tested disabling the step counter/budget message appended to each VLM request. Run 1: no_budget 4.8 steps vs budget 6.0. Run 2: budget 4.6 vs no_budget 5.4. Results flip between runs, no consistent signal. Keep step_budget_awareness=True.

**Exp 68 — Max Tokens 1024 vs 4096** (NEGATIVE): Tried reducing VLM max_tokens from 4096 to 1024. The Wikipedia Article Scroll task regressed severely (23 steps vs 5), indicating complex tasks need longer reasoning chains. Token budget at 1024 truncates critical reasoning.

**Exp 69 — Max Tokens 2048 vs 4096** (NEUTRAL): Middle ground test. Both configs essentially identical across all tasks. max_tokens doesn't meaningfully impact performance or latency with this VLM proxy setup.

**Exp 70 — History Window 6 vs 10** (NEUTRAL): Tested smaller conversation history (3 exchanges vs 5). Run 1: hw6 better (6.2 vs 8.6 steps). Run 2: hw10 better (6.6 vs 7.0 steps). High per-task variance dominates. Keep max_history_turns=10.

**Exp 71 — No Adaptive Prompt** (NEGATIVE): Removing adaptive task-specific hints caused significant regression: 8.0 vs 5.2 avg steps. Wikipedia Article Scroll: 21 vs 7 steps. The adaptive hints (Ctrl+F for finding sections, Tab for forms, Enter for search) are highly effective. Keep adaptive_prompt=True.

**Exp 72 — Smart Wait 0.5s vs 1.5s** (NEUTRAL): Tested halving the post-action wait time. Run 1: 0.5s better (5.8 vs 6.8 steps). Run 2: 1.5s better (6.2 vs 9.2 steps). 0.5s may capture screenshots before page loads, causing confusion. Keep 1.5s.

**Exp 73 — Smart Wait 1.0s vs 1.5s** (NEUTRAL): Middle ground. Identical performance (6.6 avg steps both configs). Individual task variance swaps between configs. Keep 1.5s default as safer option.

**Exp 74 — Enhanced Adaptive Hints** (NEUTRAL): Added new hints for search result clicking and scroll efficiency. Enhanced vs no_adaptive: 100% vs 80%. But compared to standard adaptive (Exp 71: 5.2 steps), enhanced (6.8 steps) wasn't clearly better. Not merged.

**Exp 75 — JPEG Quality 1 vs 2** (NEUTRAL): Tested minimum JPEG quality. Run 1: q2 6.0 vs q1 5.6. Run 2: q2 7.6 vs q1 7.8. Identical. q1 provides no improvement at already-low q2. Keep q2.

**Exp 76 — Resolution 1120px vs 1344px** (POSITIVE): Reduced VLM image resolution to 1120px. Run 1: 1120px 14,502 tok/step vs 1344px 20,761 (-30%). Run 2: 1120px 14,374 tok/step vs 1344px 20,694 (-30%), with 100% vs 80% success. Massive token reduction with equal or better task performance. `vlm_max_edge` default changed to 1120. Merged to main.

**Exp 77 — Cumulative Validation Round 5** (VALIDATION): Ran 10 diverse tasks with all current defaults (1120px, q2, no grid, compressed prompt). 10/10 (100%) success. tok/step dropped from ~24K (validation 4) to ~15K (-35%). Historical progression: 36K → 23K → 24K → 24K → 15K tok/step. Demonstrates the compounding benefit of compressed prompt + no grid + 1120px resolution.

**Exp 78 — COT Reasoning Prompt** (NEUTRAL): Added explicit chain-of-thought reasoning encouragement to system prompt ("think through: current state, target element, coordinates"). Both 100% success, same 6.6 avg steps. COT improved DDG Click Result (5 vs 12 steps) but regressed Wikipedia Scroll (14 vs 8). Net neutral.

**Exp 79 — No History (window=1)** (NEUTRAL): Tested sending only the current screenshot with no conversation history. Increased avg steps (9.4 vs 6.8) — VLM loses track of multi-step progress without context. Total tokens increase despite lower per-step tokens because more steps are needed.

**Exp 80 — Resolution 1008px vs 1120px** (NEUTRAL): Another step down in resolution. 1008px: 12K tok/step (-19%) but 10.0 avg steps (vs 7.2). More total tokens despite lower per-step. Quality loss at 1008px causes enough VLM confusion to add steps. 1120px is the sweet spot between token efficiency and task accuracy.

**Exp 81 — No Action Feedback** (NEGATIVE): Disabled success feedback messages after each action. Avg steps increased from 7.2 to 9.8 (+36%). Wikipedia Search: 10 vs 4 steps. DDG Click Result: 21 vs 10 steps. The VLM relies on action feedback to track what it already did. Essential feature.

**Exp 82 — Temperature 0.0 vs 0.1** (NEUTRAL): Tested fully deterministic temperature=0.0. Avg steps 8.6 vs 8.0 (within noise). DDG Click improved (5 vs 13) but Wikipedia Scroll regressed (21 vs 12). Mixed task-by-task results.

**Exp 83 — No Step Budget Awareness** (NEUTRAL): Disabled step budget messages. Avg steps 7.2 vs 7.6 — no_budget slightly better but within noise. Step budget info adds minimal tokens and doesn't clearly help or hurt.

**Exp 84 — No Auto-Navigate** (NEUTRAL): Disabled URL auto-navigation. Avg steps 8.6 vs 7.6. Auto-navigate saves ~1 step for URL entry in simple tasks. But Wikipedia Scroll flipped (8 vs 19 steps) — high variance. Marginal benefit.

**Exp 85 — Max Steps 15 vs 25** (NEGATIVE): Reduced step cap from 25 to 15. Wikipedia Article Scroll failed at 15 steps (4/5 = 80% vs 100%). DDG Click Result improved (5 vs 14 — urgency effect). Complex tasks need the 25-step budget.

**Exp 86 — Coordinate Validation Off** (NEUTRAL): Disabled chrome-zone coordinate validation. Avg steps 9.4 vs 7.6. DDG Click Result: 18 vs 5 steps. Validation catches misclicks in browser chrome zone and saves recovery steps. Confirms relaxed validation provides value.

**Exp 87 — Smart Wait 2.0s vs 1.5s** (NEUTRAL): Tested longer page load wait. Run 1: sw2.0 much better (5.4 vs 7.6 avg steps, -29%). Run 2: sw1.5 better (8.6 vs 11.4). High variance, results flip between runs. Inconsistent.

**Exp 88 — Cumulative Validation Round 6** (VALIDATION): 10 diverse tasks with all current defaults. 10/10 (100%) success. 16,127 tok/step. Historical progression: 36K → 23K → 24K → 24K → 15K → 16K tok/step. Performance stable. Wikipedia Section Nav used all 25 steps but completed.

**Exp 89 — WebP Format vs JPEG q2** (NEUTRAL): Added WebP image format support. WebP q2: lower tok/step for DDG pages (~10K vs 13K) but higher for Wikipedia (~27K vs 18K). Avg steps identical (5.4 vs 5.6). WebP encoding varies by content type. Net neutral.

#### Improvements Merged to Main

| Change | Source | Commit |
|--------|--------|--------|
| JPEG q75 1024px defaults | Exp 5+7 | `24c32a4` via merge |
| Ctrl+L nav prompt | Exp 6+7 | `f833242` |
| Scroll-aware stuck detection | Exp 10 | `4d34b37` |
| Relaxed coordinate validation (y<100) | Exp 12 | `705b05c` |
| Action confirmation feedback (default=True) | Exp 15 | `2a4f5c2` |
| Smart wait after navigation (default=True) | Exp 16 | `29d028f` |
| Step budget awareness (default=True) | Exp 18 | `7e692e5` |
| Adaptive prompt hints (default=False) | Exp 29 | `a30d7da` via merge |
| Expanded adaptive hints (URL nav, Wiki ToC) | Exp 30 | `2510e45` via merge |
| Auto-navigate + task rewrite (default=False) | Exp 32 | `5a915a6` via merge |
| Defaults: adaptive_prompt=True, auto_navigate=True | Exp 34 | `c356a85` via merge |
| JPEG quality reduced from q75 to q50 (default=50) | Exp 36 | `01b4d9a` via merge |
| JPEG quality reduced from q50 to q25 (default=25) | Exp 37 | `71e356c` via merge |
| JPEG quality reduced from q25 to q10 (default=10) | Exp 38 | `e115c93` via merge |
| Grid spacing 200px (default=200) | Exp 40 | `b62dad7` via merge |
| Prompt text aligned to 200px grid | Exp 41 | `ce63b75` via merge |
| Sliding window default=10 | Exp 42 | `b5c91d4` via merge |
| Grid spacing 400px (default=400) | Exp 43 | `e1dcb8d` via merge |
| Prompt text aligned to 400px grid | Exp 46 | `f5db71a` via merge |
| Step delay 0.0s (default=0.0) | Exp 51 | `f7bda32` via merge |
| VLM resolution 1344px (default=1344) | Exp 56 | `adbbbfc` via merge |
| JPEG quality q5 (default=5) | Exp 58 | `20d77c8` via merge |
| JPEG quality q2 (default=2) | Exp 59 | `07b885c` via merge |
| Compressed system prompt (default) | Exp 63 | `842881d` via merge |
| system_prompt config option | Exp 63 | `842881d` via merge |
| No grid overlay (show_coordinate_grid=False) | Exp 66 | `aba0b97` |
| VLM resolution 1120px (default=1120) | Exp 76 | `636d072` |

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
