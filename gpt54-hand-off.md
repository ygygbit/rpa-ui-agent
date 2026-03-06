# GPT-5.4 CUA Integration — Handoff Document

## Status: IMPLEMENTED (untested against live model)

## What Was Done

### New Files Created
1. **`rpa_agent/vlm/cua_client.py`** — CUAClient wrapping OpenAI Responses API
   - `CUAConfig` dataclass: base_url, api_key, model, display_width, display_height, environment
   - `CUAClient.start(task)` — sends initial task, returns response
   - `CUAClient.send_screenshot(prev_id, call_id, base64)` — sends screenshot back
   - `CUAClient.extract_computer_call(response)` — extracts computer_call item
   - `CUAClient.extract_text(response)` — gets final text output

2. **`rpa_agent/vlm/cua_action_mapper.py`** — Maps CUA actions to our Action types
   - `map_cua_action(action)` — single action mapping
   - `map_cua_actions(actions)` — batch mapping
   - Handles: click, double_click, scroll, type, keypress, drag, move, wait, screenshot
   - Key name normalization (SPACE → space, CMD → win, etc.)

### Modified Files
3. **`rpa_agent/vlm/__init__.py`** — Added CUAClient, CUAConfig, CUA_MODELS exports
4. **`rpa_agent/agent.py`** — Core changes:
   - `AgentConfig` now has `provider` ("anthropic"/"openai") and optional `cua_config`
   - `__init__()` creates CUAClient OR VLMClient based on provider
   - `run()` dispatches to `run_cua()` when provider="openai"
   - `run_cua()` — full CUA loop with batched action execution
   - `_capture_screenshot_cua()` — no-resize PNG capture for CUA
5. **`rpa_agent/cli.py`** — Added `--provider`, `--display-width`, `--display-height` flags
6. **`pyproject.toml`** — Added `openai>=2.20.0` dependency

## Architecture

### CUA Loop (in `run_cua()`)
```
1. Send task to CUA model → response
2. While response has computer_call:
   a. Extract actions[] from computer_call
   b. Map each CUA action to our Action dataclass
   c. Execute ALL actions in order (batched!)
   d. Capture screenshot (PNG, no resize)
   e. Send screenshot as computer_call_output → next response
3. Model returns no computer_call → task complete
```

### Key Differences from Anthropic Mode
| Aspect | Anthropic | OpenAI CUA |
|--------|-----------|------------|
| Loop control | Our code | Model-driven |
| Action format | Text → parse | Structured computer_call |
| Image resize | Yes (1568px/1.19M budget) | No (up to 10.24M pixels) |
| Conversation | Manual history management | previous_response_id chaining |
| Stuck detection | Yes (custom) | No (model manages) |
| Coordinate space | VLM image → rescale to screen | Direct display_width/height |
| Batching | 1 action per step | Multiple actions per turn |

## How to Test
```bash
# CUA mode (GPT-5.4)
uv run rpa-agent run "Open Chrome and go to google.com" \
  --provider openai \
  --base-url http://localhost:23333/api/openai/v1 \
  --model gpt-5.4 \
  --api-key dummy \
  --max-steps 50

# Anthropic mode (unchanged)
uv run rpa-agent run "Open Chrome and go to google.com" \
  --base-url http://localhost:23333/api/anthropic \
  --model claude-opus-4.6-fast \
  --api-key dummy
```

## Known Limitations / Future Work
- CUA `scroll` amount conversion: assumes 120 units per scroll click (Windows standard)
- CUA `drag` uses only first/last path points; intermediate waypoints ignored
- No safety mechanisms (stuck detection, coordinate validation) for CUA — model handles its own reasoning
- `--display-width` / `--display-height` defaults to 1600x900; should auto-detect screen resolution
- Not tested against live GPT-5.4 endpoint yet

## If Resuming from a Failed Session
1. Read this doc to understand what was done
2. Check `git diff` to see all changes
3. The core integration is complete — focus on testing and fixing any runtime issues
4. Key files: `cua_client.py`, `cua_action_mapper.py`, `agent.py:run_cua()`
