"""
Experiment 41: Prompt-Grid Alignment (fix "100 pixels" to "200 pixels")

The base prompt says "grid lines every 100 pixels" but the actual grid has
200px spacing (since Exp 40).  This experiment tests whether fixing the prompt
to say "200 pixels" improves accuracy by eliminating the contradiction.

Configs:
  A (mismatched): old prompt text says "100 pixels" with 200px grid
  B (aligned):    fixed prompt text says "200 pixels" matching 200px grid

Usage:
    python test_exp41_prompt_grid_alignment.py
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
from rpa_agent.vlm import VLMConfig, SystemPrompts
from rpa_agent.operators.sandbox import SandboxOperator

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SANDBOX_URL = "http://localhost:8000"
VLM_BASE_URL = "http://localhost:23333/api/anthropic"
VLM_MODEL = "claude-opus-4.6-fast"
STEP_DELAY = 0.5
MAX_STEPS = 25

TASKS = [
    {
        "name": "DuckDuckGo Search",
        "task": "Go to duckduckgo.com and search for 'python programming'",
    },
    {
        "name": "Wikipedia Search",
        "task": (
            "Go to en.wikipedia.org, search for 'Artificial intelligence', "
            "and click the search button to see results"
        ),
    },
    {
        "name": "Multi-Step Navigation",
        "task": (
            "Go to duckduckgo.com, search for 'weather forecast', "
            "then scroll down to see more results"
        ),
    },
    {
        "name": "DuckDuckGo Click Result",
        "task": (
            "Go to duckduckgo.com, search for 'OpenAI', "
            "and click on the first search result link"
        ),
    },
    {
        "name": "Wikipedia Article Scroll",
        "task": (
            "Go to en.wikipedia.org, search for 'Machine learning', "
            "click on the article, and scroll down to find the 'History' section"
        ),
    },
]


# ---------------------------------------------------------------------------
# Build the OLD (mismatched) prompt by reverting the "200" references to "100"
# ---------------------------------------------------------------------------

def build_mismatched_prompt(operator):
    """Build system prompt with old '100 pixels' wording (mismatched with 200px grid)."""
    prompt = SystemPrompts.GUI_AGENT_TEMPLATE.replace(
        "{{action_space}}", operator.action_space()
    )
    # Revert the 200→100 changes to simulate old prompt
    prompt = prompt.replace(
        "labeled lines every 200 pixels",
        "labeled lines every 100 pixels",
    )
    prompt = prompt.replace(
        "halfway between y=400 and y=600 lines, the y coordinate is ~500",
        "halfway between y=400 and y=500 lines, the y coordinate is ~450",
    )
    prompt = prompt.replace(
        "Thicker lines mark every 1000px",
        "Thicker lines mark every 500px",
    )
    prompt = prompt.replace(
        "use these as major landmarks (x=1000 and y=1000)",
        "use these as major landmarks (x=500, x=1000, x=1500 and y=500, y=1000)",
    )
    prompt = prompt.replace(
        "above first grid line at y=200",
        "above first grid line at y=100",
    )
    prompt = prompt.replace(
        "at or below the y=200 grid line",
        "at or below the y=100/y=200 grid lines",
    )
    return prompt


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

console = Console()


def reset_sandbox(url: str = "about:blank") -> None:
    try:
        resp = httpx.post(
            f"{SANDBOX_URL}/chrome/navigate",
            params={"url": url},
            timeout=10,
        )
        if resp.status_code != 200:
            console.print(f"[yellow]Warning: Chrome navigate returned {resp.status_code}[/]")
    except Exception as e:
        console.print(f"[yellow]Warning: Could not reset sandbox: {e}[/]")
    time.sleep(2)


def ensure_sandbox_ready() -> bool:
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


def run_single_test(task_info: dict, config_label: str,
                    system_prompt_override=None) -> TaskResult:
    task_name = task_info["name"]
    task_text = task_info["task"]

    console.print(f"\n  [bold]{config_label.upper()}[/] | {task_name}")
    console.print(f"  Task: {task_text[:100]}...")

    reset_sandbox("about:blank")

    vlm_config = VLMConfig(base_url=VLM_BASE_URL, model=VLM_MODEL)
    config = AgentConfig(
        vlm_config=vlm_config,
        max_steps=MAX_STEPS,
        step_delay=STEP_DELAY,
        save_screenshots=False,
    )
    operator = SandboxOperator(sandbox_url=SANDBOX_URL)
    agent = GUIAgent(config=config, console=console, operator=operator)

    # Override the system prompt if needed
    if system_prompt_override is not None:
        agent._system_prompt = system_prompt_override

    t0 = time.time()
    steps = agent.run(task_text)
    wall_time = time.time() - t0

    total_in = 0
    total_out = 0
    per_step_in = []
    for step in steps:
        if step.token_usage:
            inp = step.token_usage.get("input_tokens", 0)
            out = step.token_usage.get("output_tokens", 0)
            total_in += inp
            total_out += out
            per_step_in.append(inp)

    if agent.state == AgentState.COMPLETED:
        outcome = "completed"
    elif agent.state == AgentState.FAILED:
        outcome = "failed"
    else:
        outcome = "max_steps"

    result = TaskResult(
        task_name=task_name,
        config_label=config_label,
        outcome=outcome,
        step_count=len(steps),
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        wall_time_seconds=round(wall_time, 1),
        per_step_input_tokens=per_step_in,
    )

    console.print(
        f"  => {outcome} in {len(steps)} steps, "
        f"{total_in:,} in / {total_out:,} out tokens, "
        f"{wall_time:.1f}s"
    )
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    console.print(Panel.fit(
        "[bold blue]Experiment 41: Prompt-Grid Alignment[/]\n"
        'Fix prompt "100 pixels" to "200 pixels" to match 200px grid spacing\n'
        "JPEG q10, 1024px, grid_spacing=200",
        border_style="blue",
    ))

    if not ensure_sandbox_ready():
        return

    results: List[TaskResult] = []

    # Build mismatched prompt (old "100 pixels" wording)
    temp_operator = SandboxOperator(sandbox_url=SANDBOX_URL)
    old_prompt = build_mismatched_prompt(temp_operator)

    # --- Config A: mismatched prompt ("100 pixels" with 200px grid) ---
    console.print(Panel(
        '[bold]Config A: mismatched[/] (prompt says "100 pixels", grid is 200px)',
        border_style="yellow",
    ))
    for task_info in TASKS:
        result = run_single_test(task_info, "mismatched", system_prompt_override=old_prompt)
        results.append(result)

    # --- Config B: aligned prompt ("200 pixels" matching 200px grid) ---
    console.print(Panel(
        '[bold]Config B: aligned[/] (prompt says "200 pixels", grid is 200px)',
        border_style="green",
    ))
    for task_info in TASKS:
        result = run_single_test(task_info, "aligned", system_prompt_override=None)
        results.append(result)

    # ---- Comparison Table ----
    console.print("\n")
    console.print(Panel("[bold]Experiment 41 Results[/]", border_style="cyan"))

    table = Table(title="Experiment 41: Prompt-Grid Alignment")
    table.add_column("Task", style="bold")
    table.add_column("Config")
    table.add_column("Outcome")
    table.add_column("Steps", justify="right")
    table.add_column("Input Tokens", justify="right")
    table.add_column("Time (s)", justify="right")

    for r in results:
        outcome_style = {
            "completed": "[green]completed[/]",
            "failed": "[red]failed[/]",
            "max_steps": "[yellow]max_steps[/]",
        }.get(r.outcome, r.outcome)
        table.add_row(
            r.task_name,
            r.config_label,
            outcome_style,
            str(r.step_count),
            f"{r.total_input_tokens:,}",
            str(r.wall_time_seconds),
        )

    console.print(table)

    # ---- Per-config summaries ----
    for label in ["mismatched", "aligned"]:
        subset = [r for r in results if r.config_label == label]
        completed = sum(1 for r in subset if r.outcome == "completed")
        total = len(subset)
        avg_steps = sum(r.step_count for r in subset) / total if total else 0
        avg_tokens = sum(r.total_input_tokens for r in subset) / total if total else 0
        avg_time = sum(r.wall_time_seconds for r in subset) / total if total else 0

        summary = Table(title=f"Summary: {label}")
        summary.add_column("Metric", style="bold")
        summary.add_column("Value", justify="right")
        summary.add_row("Success Rate", f"{completed}/{total} ({completed/total:.0%})" if total else "N/A")
        summary.add_row("Avg Steps", f"{avg_steps:.1f}")
        summary.add_row("Avg Input Tokens", f"{avg_tokens:,.0f}")
        summary.add_row("Avg Wall Time (s)", f"{avg_time:.1f}")
        console.print(summary)

    # ---- Per-task delta ----
    console.print("\n")
    delta_table = Table(title="Per-Task Comparison")
    delta_table.add_column("Task", style="bold")
    delta_table.add_column("Mismatched Steps", justify="right")
    delta_table.add_column("Aligned Steps", justify="right")
    delta_table.add_column("Delta", justify="right")

    for task_info in TASKS:
        name = task_info["name"]
        ra = next((r for r in results if r.task_name == name and r.config_label == "mismatched"), None)
        rb = next((r for r in results if r.task_name == name and r.config_label == "aligned"), None)
        if ra and rb:
            d = rb.step_count - ra.step_count
            d_str = f"[green]{d}[/]" if d < 0 else f"[red]+{d}[/]" if d > 0 else "0"
            delta_table.add_row(name, str(ra.step_count), str(rb.step_count), d_str)

    console.print(delta_table)

    # ---- Save results ----
    output_path = Path("exp41_prompt_grid_alignment_results.json")
    with open(output_path, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    console.print(f"\n[dim]Raw results saved to {output_path}[/]")


if __name__ == "__main__":
    main()
