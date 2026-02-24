"""
Experiment 46: Prompt-Grid 400px Alignment

The base prompt says "grid lines every 200 pixels" but the actual grid has
400px spacing (since Exp 43). Additionally, the prompt mentions "Thicker lines
mark every 1000px" but at 400px spacing the major interval is 2000px, which is
off-screen. This experiment tests whether fixing the prompt to match the actual
400px grid improves performance.

Configs:
  A (mismatched): current prompt text says "200 pixels", mentions 1000px majors
  B (aligned):    fixed prompt text says "400 pixels", removes major line refs

Usage:
    python test_exp46_prompt_grid_400_alignment.py
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
# Build the aligned prompt (fix "200" to "400", remove major line refs)
# ---------------------------------------------------------------------------

def build_aligned_prompt(operator):
    """Build system prompt with '400 pixels' wording matching 400px grid."""
    prompt = SystemPrompts.GUI_AGENT_TEMPLATE.replace(
        "{{action_space}}", operator.action_space()
    )
    # Fix grid spacing description
    prompt = prompt.replace(
        "labeled lines every 200 pixels",
        "labeled lines every 400 pixels",
    )
    # Fix interpolation example (400px gap: between y=400 and y=800)
    prompt = prompt.replace(
        "halfway between y=400 and y=600 lines, the y coordinate is ~500",
        "halfway between y=400 and y=800 lines, the y coordinate is ~600",
    )
    # Remove major line reference (no major lines visible at 400px spacing)
    prompt = prompt.replace(
        "4. **Thicker lines mark every 1000px** — use these as major landmarks (x=1000 and y=1000)\n",
        "",
    )
    # Fix browser chrome reference
    prompt = prompt.replace(
        "above first grid line at y=200",
        "above first grid line at y=400",
    )
    # Fix web content start reference
    prompt = prompt.replace(
        "at or below the y=200 grid line",
        "at or below the y=400 grid line",
    )
    # Fix page center reference (no 500 grid line at 400px spacing)
    prompt = prompt.replace(
        "y ≈ 500 (at the y=500 major grid line)",
        "y ≈ 540 (between y=400 and y=800 grid lines)",
    )
    # Fix page center horizontal reference
    prompt = prompt.replace(
        "x ≈ 960 (between x=900 and x=1000 grid lines)",
        "x ≈ 960 (between x=800 and x=1200 grid lines)",
    )
    # Fix grid label example (no 900 label at 400px spacing)
    prompt = prompt.replace(
        '"400" on the left means y=400, "900" on the top means x=900',
        '"400" on the left means y=400, "800" on the top means x=800',
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
        "[bold blue]Experiment 46: Prompt-Grid 400px Alignment[/]\n"
        'Fix prompt "200 pixels" to "400 pixels" to match 400px grid spacing\n'
        "Also removes stale major-line references (2000px = off-screen)\n"
        "JPEG q10, 1024px, grid_spacing=400",
        border_style="blue",
    ))

    if not ensure_sandbox_ready():
        return

    results: List[TaskResult] = []

    # Build aligned prompt (fix "200" to "400")
    temp_operator = SandboxOperator(sandbox_url=SANDBOX_URL)
    aligned_prompt = build_aligned_prompt(temp_operator)

    # --- Config A: mismatched (current prompt says "200 pixels", grid is 400px) ---
    console.print(Panel(
        '[bold]Config A: mismatched[/] (prompt says "200 pixels", grid is 400px)',
        border_style="yellow",
    ))
    for task_info in TASKS:
        result = run_single_test(task_info, "mismatched", system_prompt_override=None)
        results.append(result)

    # --- Config B: aligned (prompt says "400 pixels", grid is 400px) ---
    console.print(Panel(
        '[bold]Config B: aligned[/] (prompt says "400 pixels", grid is 400px)',
        border_style="green",
    ))
    for task_info in TASKS:
        result = run_single_test(task_info, "aligned", system_prompt_override=aligned_prompt)
        results.append(result)

    # ---- Comparison Table ----
    console.print("\n")
    console.print(Panel("[bold]Experiment 46 Results[/]", border_style="cyan"))

    table = Table(title="Experiment 46: Prompt-Grid 400px Alignment")
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
    delta_table = Table(title="Per-Task Comparison (mismatched to aligned)")
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
    output_path = Path("exp46_prompt_grid_400_alignment_results.json")
    with open(output_path, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    console.print(f"\n[dim]Raw results saved to {output_path}[/]")


if __name__ == "__main__":
    main()
