"""
Experiment 66: No Grid Overlay vs Grid Overlay at 1344px

The grid overlay adds visual noise and tokens to the screenshot image.
At 1344px resolution, VLM has more pixels to work with and may be able
to estimate coordinates accurately without the grid.

Removing the grid means:
- Cleaner screenshots (less visual clutter)
- Potentially fewer image tokens (grid lines add edges/patterns)
- Need to remove grid-related instructions from prompt

Configs:
  A (grid): current default with grid overlay + grid instructions
  B (no_grid): no grid overlay, simplified coordinate instructions

Usage:
    python test_exp66_no_grid_overlay.py
"""

import time
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List

import httpx
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from rpa_agent.agent import GUIAgent, AgentConfig, AgentState
from rpa_agent.vlm import VLMConfig
from rpa_agent.operators.sandbox import SandboxOperator

SANDBOX_URL = "http://localhost:8000"
VLM_BASE_URL = "http://localhost:23333/api/anthropic"
VLM_MODEL = "claude-opus-4.6-fast"
MAX_STEPS = 25

# Prompt for no-grid mode: simplified coordinate instructions without grid references
NO_GRID_PROMPT = """You are a GUI automation agent. Observe screenshots, execute one action per response as JSON.

## Coordinates
- (0,0) = top-left, X right, Y down. Screen is 1920x1080.
- Estimate element coordinates by visual position on screen.
- Browser chrome (tabs, address bar): y ≈ 0-140. Web content starts y > 140.
- CRITICAL: element at y < 140 = browser chrome, NOT web page content.

## Response Format
```json
{"reasoning": "Brief description of target element and estimated coordinates", "action": "type", ...params}
```

## Actions
- **click**: `{"action":"click","x":500,"y":300,"element":"Search button"}`
- **double_click**: `{"action":"double_click","x":500,"y":300,"element":"Icon"}`
- **right_click**: `{"action":"right_click","x":500,"y":300,"element":"Desktop"}`
- **move_relative**: `{"action":"move_relative","dx":150,"dy":-80}`
- **click_now**: `{"action":"click_now","element":"Button"}`
- **type**: `{"action":"type","text":"Hello","press_enter":false}`
- **press_key**: `{"action":"press_key","key":"enter"}`
- **hotkey**: `{"action":"hotkey","keys":["ctrl","a"]}`
- **scroll**: `{"action":"scroll","direction":"down","amount":3}`
- **wait**: `{"action":"wait","seconds":2}`
- **done**: `{"action":"done","summary":"What was accomplished"}`
- **fail**: `{"action":"fail","error":"Why task cannot be completed"}`

## Rules
1. ONE action per response. Prefer click(x,y) over move_relative+click_now.
2. After clicking a text field, IMMEDIATELY type on next step — do NOT click again.
3. Address bar: ALWAYS use hotkey(["ctrl","l"]) then type. NEVER click the address bar.
4. After typing in search/form field, press Enter to submit.
5. Never repeat a failing action — try a different approach.
6. Never click autocomplete dropdowns — press Escape then Enter.
7. Report done when objective is achieved. Be efficient."""

TASKS = [
    {"name": "DuckDuckGo Search", "task": "Go to duckduckgo.com and search for 'python programming'"},
    {"name": "Wikipedia Search", "task": "Go to en.wikipedia.org, search for 'Artificial intelligence', and click the search button to see results"},
    {"name": "Multi-Step Navigation", "task": "Go to duckduckgo.com, search for 'weather forecast', then scroll down to see more results"},
    {"name": "DuckDuckGo Click Result", "task": "Go to duckduckgo.com, search for 'OpenAI', and click on the first search result link"},
    {"name": "Wikipedia Article Scroll", "task": "Go to en.wikipedia.org, search for 'Machine learning', click on the article, and scroll down to find the 'History' section"},
]

@dataclass
class TaskResult:
    task_name: str
    config_label: str
    outcome: str
    step_count: int
    total_input_tokens: int
    total_output_tokens: int
    wall_time_seconds: float
    per_step_input_tokens: List[int] = field(default_factory=list)

console = Console()

def reset_sandbox(url="about:blank"):
    try:
        resp = httpx.post(f"{SANDBOX_URL}/chrome/navigate", params={"url": url}, timeout=10)
        if resp.status_code != 200:
            console.print(f"[yellow]Warning: Chrome navigate returned {resp.status_code}[/]")
    except Exception as e:
        console.print(f"[yellow]Warning: Could not reset sandbox: {e}[/]")
    time.sleep(2)

def ensure_sandbox_ready():
    try:
        resp = httpx.get(f"{SANDBOX_URL}/status", timeout=5)
        status = resp.json()
        if not status.get("chrome_running"):
            console.print("[dim]Starting Chrome in sandbox...[/]")
            httpx.post(f"{SANDBOX_URL}/chrome/start?url=about:blank", timeout=10)
            time.sleep(3)
        return True
    except Exception as e:
        console.print(f"[red]Sandbox not available: {e}[/]")
        return False

def run_single_test(task_info, config_label, system_prompt=None, show_grid=True):
    task_name = task_info["name"]
    task_text = task_info["task"]
    console.print(f"\n  [bold]{config_label.upper()}[/] | {task_name}")
    reset_sandbox("about:blank")
    vlm_config = VLMConfig(base_url=VLM_BASE_URL, model=VLM_MODEL)
    config = AgentConfig(
        vlm_config=vlm_config,
        max_steps=MAX_STEPS,
        save_screenshots=False,
        system_prompt=system_prompt,
        show_coordinate_grid=show_grid,
    )
    operator = SandboxOperator(sandbox_url=SANDBOX_URL)
    agent = GUIAgent(config=config, console=console, operator=operator)
    t0 = time.time()
    steps = agent.run(task_text)
    wall_time = time.time() - t0
    total_in, total_out, per_step_in = 0, 0, []
    for step in steps:
        if step.token_usage:
            inp = step.token_usage.get("input_tokens", 0)
            out = step.token_usage.get("output_tokens", 0)
            total_in += inp
            total_out += out
            per_step_in.append(inp)
    outcome = "completed" if agent.state == AgentState.COMPLETED else ("failed" if agent.state == AgentState.FAILED else "max_steps")
    result = TaskResult(task_name=task_name, config_label=config_label, outcome=outcome,
                        step_count=len(steps), total_input_tokens=total_in, total_output_tokens=total_out,
                        wall_time_seconds=round(wall_time, 1), per_step_input_tokens=per_step_in)
    console.print(f"  => {outcome} in {len(steps)} steps, {total_in:,} in / {total_out:,} out tokens, {wall_time:.1f}s")
    return result

def main():
    console.print(Panel.fit(
        "[bold blue]Experiment 66: No Grid Overlay vs Grid Overlay[/]\n"
        "1344px, q2, grid_spacing=400",
        border_style="blue",
    ))
    if not ensure_sandbox_ready():
        return
    results: List[TaskResult] = []

    console.print(Panel("[bold]Config A: Grid overlay[/] (current default)", border_style="yellow"))
    for task_info in TASKS:
        results.append(run_single_test(task_info, "grid", system_prompt=None, show_grid=True))

    console.print(Panel("[bold]Config B: No grid overlay[/] (clean screenshots)", border_style="green"))
    for task_info in TASKS:
        results.append(run_single_test(task_info, "no_grid", system_prompt=NO_GRID_PROMPT, show_grid=False))

    # Results table
    console.print("\n")
    table = Table(title="Experiment 66: No Grid vs Grid Overlay")
    table.add_column("Task", style="bold")
    table.add_column("Config")
    table.add_column("Outcome")
    table.add_column("Steps", justify="right")
    table.add_column("Input Tokens", justify="right")
    table.add_column("Tok/Step", justify="right")
    table.add_column("Time (s)", justify="right")
    for r in results:
        os = {"completed": "[green]completed[/]", "failed": "[red]failed[/]", "max_steps": "[yellow]max_steps[/]"}.get(r.outcome, r.outcome)
        tok_per_step = r.total_input_tokens // r.step_count if r.step_count else 0
        table.add_row(r.task_name, r.config_label, os, str(r.step_count), f"{r.total_input_tokens:,}", f"{tok_per_step:,}", str(r.wall_time_seconds))
    console.print(table)

    for label in ["grid", "no_grid"]:
        subset = [r for r in results if r.config_label == label]
        completed = sum(1 for r in subset if r.outcome == "completed")
        total = len(subset)
        avg_steps = sum(r.step_count for r in subset) / total
        avg_tokens = sum(r.total_input_tokens for r in subset) / total
        avg_time = sum(r.wall_time_seconds for r in subset) / total
        total_tok = sum(r.total_input_tokens for r in subset)
        total_steps = sum(r.step_count for r in subset)
        avg_tok_per_step = total_tok // total_steps if total_steps else 0
        s = Table(title=f"Summary: {label}")
        s.add_column("Metric", style="bold")
        s.add_column("Value", justify="right")
        s.add_row("Success Rate", f"{completed}/{total} ({completed/total:.0%})")
        s.add_row("Avg Steps", f"{avg_steps:.1f}")
        s.add_row("Avg Input Tokens", f"{avg_tokens:,.0f}")
        s.add_row("Avg Tok/Step", f"{avg_tok_per_step:,}")
        s.add_row("Avg Wall Time (s)", f"{avg_time:.1f}")
        console.print(s)

    output_path = Path("exp66_no_grid_overlay_results.json")
    with open(output_path, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    console.print(f"\n[dim]Raw results saved to {output_path}[/]")

if __name__ == "__main__":
    main()
