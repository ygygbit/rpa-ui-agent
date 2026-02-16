# RPA UI Agent

A Vision-Language Model (VLM) based Robotic Process Automation (RPA) agent that can understand screenshots and perform GUI automation tasks through natural language instructions.

## Overview

This project implements a multimodal AI agent that combines:
- **Screen capture and analysis** using Vision-Language Models
- **GUI element grounding** for precise coordinate detection
- **Action orchestration** with observe-think-act loop
- **Self-correction** through visual feedback

The agent can understand arbitrary GUI interfaces without requiring pre-defined selectors, element IDs, or accessibility APIs—making it universally applicable to any application.

## Quick Start

### Prerequisites
- Python 3.10+
- Windows (for win32 window management) or Docker (for sandbox mode)
- VLM API access (custom endpoint or Anthropic API key)

### Installation

```bash
# Clone the repository
git clone https://github.com/layoffhuman/rpa-ui-agent.git
cd rpa-ui-agent

# Install with uv (recommended)
uv sync

# Or with pip
pip install -e .
```

### Configuration

The agent supports two API configuration modes:

#### Option 1: Official Anthropic API (Recommended for most users)

Set your Anthropic API key as an environment variable:

```bash
# Windows (PowerShell)
$env:ANTHROPIC_API_KEY = "sk-ant-your-api-key"

# Windows (Command Prompt)
set ANTHROPIC_API_KEY=sk-ant-your-api-key

# Linux/macOS
export ANTHROPIC_API_KEY="sk-ant-your-api-key"
```

**Recommended models:**
- `claude-opus-4-20250514` - Best visual understanding (recommended)
- `claude-sonnet-4-20250514` - Fast and capable

#### Option 2: Custom Endpoint (For self-hosted or proxy servers)

If you have a custom Anthropic-compatible API endpoint:

```bash
# Windows (PowerShell)
$env:RPA_VLM_BASE_URL = "http://localhost:23333/api/anthropic"
$env:RPA_VLM_API_KEY = "your-api-key"
$env:RPA_VLM_MODEL = "claude-opus-4.6-fast"

# Linux/macOS
export RPA_VLM_BASE_URL="http://localhost:23333/api/anthropic"
export RPA_VLM_API_KEY="your-api-key"
export RPA_VLM_MODEL="claude-opus-4.6-fast"
```

**Recommended models for custom endpoints:**
- `claude-opus-4.6-fast` - Fast inference (recommended)
- `claude-opus-4.6` - Standard model
- `claude-opus-4.6-1m` - Extended context

#### Using a .env file

Create a `.env` file in the project root:

```env
# Option 1: Official Anthropic API
ANTHROPIC_API_KEY=sk-ant-your-api-key

# Option 2: Custom endpoint (takes priority if set)
# RPA_VLM_BASE_URL=http://localhost:23333/api/anthropic
# RPA_VLM_API_KEY=your-api-key
# RPA_VLM_MODEL=claude-opus-4.6-fast
```

### Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes* | Official Anthropic API key |
| `RPA_VLM_BASE_URL` | No | Custom API endpoint URL (overrides Anthropic) |
| `RPA_VLM_API_KEY` | No | API key for custom endpoint |
| `RPA_VLM_MODEL` | No | Model name to use (auto-selected if not set) |

*Required if not using a custom endpoint

### Verify Installation

```bash
# Test VLM connection
rpa-agent test-vlm

# Take a screenshot
rpa-agent screenshot

# Run a simple task
rpa-agent run "Click the Windows Start button"
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         GUI Agent                                │
├─────────────────────────────────────────────────────────────────┤
│  ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌────────┐ │
│  │   Screen  │───▶│    VLM    │───▶│  Action   │───▶│   UI   │ │
│  │  Capture  │    │  Client   │    │  Parser   │    │ Control│ │
│  └───────────┘    └───────────┘    └───────────┘    └────────┘ │
│        │                                                   │     │
│        └───────────────── Feedback Loop ──────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

### Core Components

1. **Screen Capture** (`rpa_agent/core/screen.py`)
   - Fast screenshot using `mss` library
   - Multi-monitor support
   - Base64 encoding for VLM API

2. **UI Controller** (`rpa_agent/core/controller.py`)
   - Mouse actions (click, drag, scroll)
   - Keyboard input (type, hotkeys)
   - Safety boundaries

3. **Window Manager** (`rpa_agent/core/window.py`)
   - Window enumeration and focus
   - Position and resize control
   - Win32 API integration

4. **VLM Client** (`rpa_agent/vlm/client.py`)
   - Anthropic API compatible client
   - Screenshot analysis
   - Element grounding

5. **Action System** (`rpa_agent/actions/`)
   - Structured action definitions
   - Multi-format parser (JSON, natural language)

6. **Agent Orchestrator** (`rpa_agent/agent.py`)
   - Main observe-think-act loop
   - Step history and logging
   - Error recovery

## Research Background

### GUI Agents and Vision-Language Models

Recent advances in Vision-Language Models (VLMs) have enabled a new paradigm for GUI automation:

#### Key Research Directions

1. **GUI Grounding**
   - Mapping natural language to precise screen coordinates
   - Element detection without DOM/accessibility APIs
   - Bounding box prediction for UI elements

2. **Action Prediction**
   - Converting screenshots + task descriptions to executable actions
   - Handling multi-step workflows
   - Error recovery through visual feedback

3. **Benchmarks**
   - **ScreenSpot**: GUI element grounding benchmark
   - **OSWorld**: OS-level agent evaluation
   - **WebArena**: Web navigation tasks
   - **AITW**: Android task automation

#### Related Systems

| System | Key Features |
|--------|--------------|
| **Claude Computer Use** | First commercial VLM with native computer control |
| **UI-TARS** (ByteDance) | Unified action space, native resolution processing |
| **OS-Atlas** (Microsoft) | 4M+ screenshot training, cross-platform |
| **SeeClick** | GUI grounding focused, visual prompting |
| **CogAgent** | High-res vision encoder, cross-platform |
| **OmniParser** | Structured screen parsing, DOM-like output |

### Agent Architecture Patterns

#### 1. Single-Step Agents
```
Screenshot → VLM → Action → Repeat
```
- Simple but effective for many tasks
- Each step is independent

#### 2. ReAct Pattern
```
Screenshot → Reasoning → Action → Observation → Repeat
```
- Explicit reasoning before acting
- Better for complex tasks

#### 3. Planning + Execution
```
Screenshot → Plan → Execute Steps → Verify
```
- High-level planning first
- Then step-by-step execution

This implementation supports all three patterns.

## Installation

### Prerequisites
- Python 3.10+
- Windows (for win32 window management)
- Local LLM endpoint (Anthropic API compatible)

### Setup

```bash
# Navigate to project
cd rpa

# Install with uv
uv sync

# Or with pip
pip install -e .
```

### Dependencies
- `anthropic` - API client
- `pyautogui` - Mouse/keyboard control
- `mss` - Fast screenshots
- `pywin32` - Windows APIs
- `pillow` - Image processing
- `rich` - Terminal UI
- `typer` - CLI framework

## Usage

### Command Line

```bash
# Run a task
rpa-agent run "Open Chrome and search for weather"

# With planning phase
rpa-agent run "Fill out the login form" --plan

# Dry run (no execution)
rpa-agent run "Click the submit button" --dry-run

# Find element coordinates
rpa-agent ground "Submit button"

# Interactive mode
rpa-agent interactive

# Test VLM connection
rpa-agent test-vlm
```

### Python API

```python
from rpa_agent import GUIAgent, AgentConfig
from rpa_agent.vlm import VLMConfig

# Option 1: Auto-configure from environment variables
agent = GUIAgent()

# Option 2: Official Anthropic API
vlm_config = VLMConfig.for_anthropic(
    api_key="sk-ant-your-api-key",
    model="claude-opus-4-20250514"  # recommended
)

# Option 3: Custom endpoint
vlm_config = VLMConfig.for_custom_endpoint(
    base_url="http://localhost:23333/api/anthropic",
    api_key="your-api-key",
    model="claude-opus-4.6-fast"  # recommended for custom endpoints
)

config = AgentConfig(
    vlm_config=vlm_config,
    max_steps=20,
    save_screenshots=True
)

# Create agent with custom config
agent = GUIAgent(config=config)

# Run task
steps = agent.run("Open Notepad and type 'Hello World'")

# Save history
agent.save_history("task_history.json")
```

### Element Grounding

```python
# Find specific element
coords = agent.ground_element("red button with text 'Submit'")
if coords:
    print(f"Found at: {coords}")
```

### Custom Action Handling

```python
def on_action(action):
    """Called before each action execution."""
    print(f"About to execute: {action.action_type}")
    return True  # Return False to skip

def on_step(step):
    """Called after each step."""
    print(f"Step {step.step_number}: {step.reasoning}")

agent.run("Complete the form", on_action=on_action, on_step=on_step)
```

## Configuration

### VLM Configuration

The VLM client automatically configures itself from environment variables. You can also configure it programmatically:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `base_url` | `None` (uses Anthropic default) | Custom API endpoint |
| `api_key` | From `ANTHROPIC_API_KEY` | API key |
| `model` | `claude-opus-4-20250514` | Model name |
| `max_tokens` | `4096` | Max response tokens |
| `temperature` | `0.1` | Sampling temperature |
| `use_official_api` | Auto-detected | Use official Anthropic API |

**Configuration Priority:**
1. Custom endpoint (`RPA_VLM_BASE_URL`) if set
2. Official Anthropic API (`ANTHROPIC_API_KEY`) if set
3. Default development endpoint (localhost)

### Agent Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_steps` | `50` | Maximum execution steps |
| `step_delay` | `0.5` | Delay between steps (seconds) |
| `screenshot_scale` | `1.0` | Screenshot scaling factor |
| `save_screenshots` | `True` | Save screenshots to disk |
| `confirm_actions` | `False` | Confirm before executing |
| `dry_run` | `False` | Skip actual execution |
| `max_retries` | `3` | Retries on parse failure |

## Action Types

### Mouse Actions
- `click` - Left click at coordinates
- `double_click` - Double click
- `right_click` - Right click
- `drag` - Drag from point to point
- `scroll` - Scroll up/down/left/right
- `hover` - Move mouse without clicking

### Keyboard Actions
- `type` - Type text
- `press_key` - Press single key
- `hotkey` - Key combination (e.g., Ctrl+C)

### Control Actions
- `wait` - Wait for specified time
- `focus_window` - Switch to window
- `screenshot` - Capture new screenshot
- `done` - Task completed
- `fail` - Task failed

## Action Format

The VLM outputs actions in JSON format:

```json
{
    "reasoning": "The search field is at the top of the page",
    "action": "click",
    "x": 500,
    "y": 100,
    "element": "search input field"
}
```

```json
{
    "reasoning": "Need to submit the search query",
    "action": "type",
    "text": "weather forecast",
    "press_enter": true
}
```

## Project Structure

```
rpa/
├── pyproject.toml          # Project configuration
├── README.md               # This file
├── claude_request_guide.md # LLM API guide
├── rpa_agent/
│   ├── __init__.py
│   ├── agent.py            # Main agent orchestrator
│   ├── cli.py              # Command-line interface
│   ├── core/
│   │   ├── __init__.py
│   │   ├── screen.py       # Screen capture
│   │   ├── controller.py   # UI control
│   │   └── window.py       # Window management
│   ├── actions/
│   │   ├── __init__.py
│   │   ├── definitions.py  # Action types
│   │   └── parser.py       # Action parser
│   └── vlm/
│       ├── __init__.py
│       ├── client.py       # VLM API client
│       └── prompts.py      # System prompts
└── screenshots/            # Captured screenshots
```

## Safety Features

1. **Screen boundary clamping** - Prevents clicks outside screen
2. **Failsafe** - Move mouse to corner to abort (pyautogui)
3. **Dry run mode** - Test without execution
4. **Action confirmation** - Manual approval before each action
5. **Max steps limit** - Prevents infinite loops

## Limitations

- **Windows only** for window management (core automation is cross-platform)
- **Requires VLM endpoint** - Won't work offline
- **Single monitor** optimized (multi-monitor possible)
- **No complex gesture support** (multi-finger, pressure)

## Future Improvements

- [ ] Linux/macOS window management
- [ ] Vision encoder fine-tuning for GUI grounding
- [ ] Workflow recording and playback
- [ ] Multi-agent coordination
- [ ] Accessibility API integration
- [ ] Element caching for faster grounding

## License

MIT License

## Acknowledgments

This project draws inspiration from:
- Anthropic's Claude Computer Use
- Microsoft's OS-Atlas
- ByteDance's UI-TARS
- Academic research on GUI agents and VLM grounding
