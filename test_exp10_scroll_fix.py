"""
Experiment 10: Scroll Fix + Higher Max Steps

Tests two improvements on hard tasks that previously failed:
  1. Fixed stuck-loop detection for scroll actions (threshold 3->6)
  2. Included scroll direction/amount in action signature
  3. Max steps raised from 25 to 35

Configs:
  A: Old behavior — max_steps=25, old stuck detection (blocks scroll at 3)
  B: Fixed behavior — max_steps=35, scroll-aware stuck detection

Tests the same hard tasks from Exp 8/9 that had failures.

Usage:
    python test_exp10_scroll_fix.py
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

# Tasks that previously failed or were difficult
TASKS = [
    {
        "name": "Page Scroll + Back Navigation",
        "task": (
            "Go to duckduckgo.com, search for 'machine learning', "
            "scroll down to the bottom of the results page, "
            "then press the browser back button or use Alt+Left to go back to the search page"
        ),
        "reset_url": "about:blank",
    },
    {
        "name": "Wikipedia Deep Scroll",
        "task": (
            "Go to en.wikipedia.org, search for 'Python programming language', "
            "and scroll down to find the 'History' section on the article page"
        ),
        "reset_url": "about:blank",
    },
    {
        "name": "DuckDuckGo Multi-Page",
        "task": (
            "Go to duckduckgo.com, search for 'climate change', "
            "scroll to the bottom of the results, "
            "then click 'More results' or 'Next' to go to the second page of results"
        ),
        "reset_url": "about:blank",
    },
    {
        "name": "Multi-Tab + Content",
        "task": (
            "Open duckduckgo.com, search for 'weather'. "
            "Then open a new tab with Ctrl+T, navigate to en.wikipedia.org in that tab, "
            "and then close the current tab with Ctrl+W to go back to the DuckDuckGo results"
        ),
        "reset_url": "about:blank",
    },
    {
        "name": "DuckDuckGo Search + Click + Scroll",
        "task": (
            "Go to duckduckgo.com, search for 'OpenAI', "
            "click on the first search result, "
            "then scroll down on the result page to read more content"
        ),
        "reset_url": "about:blank",
    },
]


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


def run_single_test(task_info: dict, config_label: str, max_steps: int) -> TaskResult:
    task_name = task_info["name"]
    task_text = task_info["task"]

    console.print(f"\n  [bold]{config_label.upper()}[/] | {task_name} (max_steps={max_steps})")
    console.print(f"  Task: {task_text[:100]}...")

    reset_sandbox(task_info.get("reset_url", "about:blank"))

    vlm_config = VLMConfig(base_url=VLM_BASE_URL, model=VLM_MODEL)
    config = AgentConfig(
        vlm_config=vlm_config,
        max_steps=max_steps,
        step_delay=STEP_DELAY,
        save_screenshots=False,
        max_history_turns=10,
        vlm_image_format="jpeg",
        vlm_image_quality=75,
        vlm_max_edge=1024,
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
        "[bold blue]Experiment 10: Scroll Fix + Higher Max Steps[/]\n"
        "Tests scroll-aware stuck detection + max_steps=35\n"
        "on hard tasks from Exp 8/9 that previously failed",
        border_style="blue",
    ))

    if not ensure_sandbox_ready():
        return

    results: List[TaskResult] = []

    # Run with the fixed config (scroll-aware stuck detection + 35 steps)
    console.print(Panel(
        "[bold]Fixed Config[/] (scroll-tolerant stuck detect, max_steps=35)",
        border_style="green",
    ))

    for task_info in TASKS:
        result = run_single_test(task_info, "fixed", max_steps=35)
        results.append(result)

    # ---- Report ----
    console.print("\n")
    console.print(Panel("[bold]Results: Fixed Config on Hard Tasks[/]", border_style="cyan"))

    table = Table(title="Experiment 10: Scroll Fix + max_steps=35")
    table.add_column("Task", style="bold")
    table.add_column("Outcome")
    table.add_column("Steps", justify="right")
    table.add_column("Input Tokens", justify="right")
    table.add_column("Output Tokens", justify="right")
    table.add_column("Time (s)", justify="right")

    for r in results:
        outcome_style = {
            "completed": "[green]completed[/]",
            "failed": "[red]failed[/]",
            "max_steps": "[yellow]max_steps[/]",
        }.get(r.outcome, r.outcome)
        table.add_row(
            r.task_name,
            outcome_style,
            str(r.step_count),
            f"{r.total_input_tokens:,}",
            f"{r.total_output_tokens:,}",
            str(r.wall_time_seconds),
        )

    console.print(table)

    # ---- Summary ----
    completed = sum(1 for r in results if r.outcome == "completed")
    total = len(results)
    avg_steps = sum(r.step_count for r in results) / total
    avg_tokens = sum(r.total_input_tokens for r in results) / total
    avg_time = sum(r.wall_time_seconds for r in results) / total

    summary = Table(title="Summary")
    summary.add_column("Metric", style="bold")
    summary.add_column("Value", justify="right")
    summary.add_row("Success Rate", f"{completed}/{total} ({completed/total:.0%})")
    summary.add_row("Avg Steps", f"{avg_steps:.1f}")
    summary.add_row("Avg Input Tokens", f"{avg_tokens:,.0f}")
    summary.add_row("Avg Wall Time (s)", f"{avg_time:.1f}")

    # Compare with Exp 8 baselines
    console.print(summary)
    console.print("\n[bold]Comparison with Exp 8 (same tasks, old config):[/]")
    console.print("  Exp 8: 4/5 (80%) success, avg 17.6 steps, avg 70.0s")
    console.print(f"  Exp 10: {completed}/{total} ({completed/total:.0%}) success, avg {avg_steps:.1f} steps, avg {avg_time:.1f}s")

    # ---- Save results ----
    output_path = Path("exp10_scroll_fix_results.json")
    with open(output_path, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    console.print(f"\n[dim]Raw results saved to {output_path}[/]")


if __name__ == "__main__":
    main()
