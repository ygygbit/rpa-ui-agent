"""
Experiment 49: Cumulative Validation Round 3

Test all 21 merged improvements together on an expanded set of 10 tasks.
This validates the complete optimized config:
  - JPEG q10 at 1024px
  - Grid spacing 400px
  - Sliding window 10 messages
  - Relaxed coordinate validation
  - Action feedback
  - Smart wait 1.5s
  - Step budget awareness
  - Adaptive prompt hints
  - Auto-navigate + task rewrite
  - Prompt aligned to 400px grid

Previous validations:
  Exp 17: 100% (10/10) on 10 tasks
  Exp 33: 100% (10/10) on 10 tasks, 5.8 avg steps

Target: 90%+ on 10 diverse tasks using current defaults.

Usage:
    python test_exp49_cumulative_validation_3.py
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

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SANDBOX_URL = "http://localhost:8000"
VLM_BASE_URL = "http://localhost:23333/api/anthropic"
VLM_MODEL = "claude-opus-4.6-fast"
STEP_DELAY = 0.5
MAX_STEPS = 25

# 10 diverse tasks: navigation, search, multi-step, reading
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
    {
        "name": "Google Search",
        "task": "Go to google.com and search for 'climate change'",
    },
    {
        "name": "Wikipedia Navigation",
        "task": (
            "Go to en.wikipedia.org and click on the 'Contents' link "
            "in the left sidebar to see the portal page"
        ),
    },
    {
        "name": "DuckDuckGo Images",
        "task": (
            "Go to duckduckgo.com, search for 'sunset photos', "
            "and click on the 'Images' tab to see image results"
        ),
    },
    {
        "name": "Wikipedia Random",
        "task": (
            "Go to en.wikipedia.org and click on the 'Random article' link "
            "in the left sidebar, then scroll down to read the article"
        ),
    },
    {
        "name": "Multi-Tab Search",
        "task": (
            "Go to duckduckgo.com, search for 'Python tutorial', "
            "then change the search to 'JavaScript tutorial' by clearing "
            "the search box and typing the new query"
        ),
    },
]


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

@dataclass
class TaskResult:
    task_name: str
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


def run_single_test(task_info: dict) -> TaskResult:
    task_name = task_info["name"]
    task_text = task_info["task"]

    console.print(f"\n  [bold]Task {task_name}[/]")
    console.print(f"  {task_text[:120]}...")

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
        outcome=outcome,
        step_count=len(steps),
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        wall_time_seconds=round(wall_time, 1),
        per_step_input_tokens=per_step_in,
    )

    status_color = {"completed": "green", "failed": "red", "max_steps": "yellow"}[outcome]
    console.print(
        f"  => [{status_color}]{outcome}[/] in {len(steps)} steps, "
        f"{total_in:,} in / {total_out:,} out tokens, "
        f"{wall_time:.1f}s"
    )
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    console.print(Panel.fit(
        "[bold blue]Experiment 49: Cumulative Validation Round 3[/]\n"
        "All 21 merged improvements on 10 diverse tasks\n"
        "Config: JPEG q10, 1024px, grid_spacing=400, window=10, all features on",
        border_style="blue",
    ))

    if not ensure_sandbox_ready():
        return

    results: List[TaskResult] = []

    for i, task_info in enumerate(TASKS, 1):
        console.print(Panel(
            f"[bold]Task {i}/{len(TASKS)}: {task_info['name']}[/]",
            border_style="cyan",
        ))
        result = run_single_test(task_info)
        results.append(result)

    # ---- Results Table ----
    console.print("\n")
    console.print(Panel("[bold]Experiment 49: Cumulative Validation Results[/]", border_style="cyan"))

    table = Table(title="Cumulative Validation Round 3 (10 tasks)")
    table.add_column("#", style="dim", justify="right")
    table.add_column("Task", style="bold")
    table.add_column("Outcome")
    table.add_column("Steps", justify="right")
    table.add_column("Input Tokens", justify="right")
    table.add_column("Time (s)", justify="right")

    for i, r in enumerate(results, 1):
        outcome_style = {
            "completed": "[green]completed[/]",
            "failed": "[red]failed[/]",
            "max_steps": "[yellow]max_steps[/]",
        }.get(r.outcome, r.outcome)
        table.add_row(
            str(i),
            r.task_name,
            outcome_style,
            str(r.step_count),
            f"{r.total_input_tokens:,}",
            str(r.wall_time_seconds),
        )

    console.print(table)

    # ---- Summary ----
    completed = sum(1 for r in results if r.outcome == "completed")
    total = len(results)
    avg_steps = sum(r.step_count for r in results) / total if total else 0
    avg_tokens = sum(r.total_input_tokens for r in results) / total if total else 0
    avg_time = sum(r.wall_time_seconds for r in results) / total if total else 0
    total_tokens = sum(r.total_input_tokens for r in results)
    total_time = sum(r.wall_time_seconds for r in results)

    # Only successful tasks for "avg steps on success"
    completed_results = [r for r in results if r.outcome == "completed"]
    avg_steps_success = sum(r.step_count for r in completed_results) / len(completed_results) if completed_results else 0

    summary = Table(title="Overall Summary")
    summary.add_column("Metric", style="bold")
    summary.add_column("Value", justify="right")
    summary.add_row("Success Rate", f"{completed}/{total} ({completed/total:.0%})" if total else "N/A")
    summary.add_row("Avg Steps (all)", f"{avg_steps:.1f}")
    summary.add_row("Avg Steps (success only)", f"{avg_steps_success:.1f}")
    summary.add_row("Avg Input Tokens", f"{avg_tokens:,.0f}")
    summary.add_row("Avg Wall Time (s)", f"{avg_time:.1f}")
    summary.add_row("Total Input Tokens", f"{total_tokens:,}")
    summary.add_row("Total Wall Time (s)", f"{total_time:.1f}")
    console.print(summary)

    # ---- Save results ----
    output_path = Path("exp49_cumulative_validation_3_results.json")
    with open(output_path, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    console.print(f"\n[dim]Raw results saved to {output_path}[/]")


if __name__ == "__main__":
    main()
