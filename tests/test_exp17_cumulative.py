"""
Experiment 17: Cumulative Improvements Validation

Validates all 6 improvements merged to main by running the same 5-task suite
used across Exp 12-16 with full optimized config. This validates that the
improvements stack without interference.

Also runs 5 additional harder tasks to test generalization beyond the
tasks used for optimization.

Config: All defaults from main (JPEG, relaxed validation, action feedback,
smart wait all enabled).

Usage:
    python test_exp17_cumulative.py
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

# Standard test suite (same as Exp 12-16)
STANDARD_TASKS = [
    {
        "name": "DuckDuckGo Search",
        "task": "Go to duckduckgo.com and search for 'python programming'",
        "reset_url": "about:blank",
        "category": "standard",
    },
    {
        "name": "Wikipedia Search",
        "task": (
            "Go to en.wikipedia.org, search for 'Artificial intelligence', "
            "and click the search button to see results"
        ),
        "reset_url": "about:blank",
        "category": "standard",
    },
    {
        "name": "Multi-Step Navigation",
        "task": (
            "Go to duckduckgo.com, search for 'weather forecast', "
            "then scroll down to see more results"
        ),
        "reset_url": "about:blank",
        "category": "standard",
    },
    {
        "name": "DuckDuckGo Click Result",
        "task": (
            "Go to duckduckgo.com, search for 'OpenAI', "
            "and click on the first search result link"
        ),
        "reset_url": "about:blank",
        "category": "standard",
    },
    {
        "name": "Wikipedia Article Scroll",
        "task": (
            "Go to en.wikipedia.org, search for 'Machine learning', "
            "click on the article, and scroll down to find the 'History' section"
        ),
        "reset_url": "about:blank",
        "category": "standard",
    },
]

# New harder tasks not used in optimization
HARD_TASKS = [
    {
        "name": "Wikipedia + Back Nav",
        "task": (
            "Go to en.wikipedia.org, search for 'Python programming language', "
            "click on the article, then use Alt+Left to go back to the search results"
        ),
        "reset_url": "about:blank",
        "category": "hard",
    },
    {
        "name": "DuckDuckGo Image Search",
        "task": (
            "Go to duckduckgo.com, search for 'cats', "
            "then click on the 'Images' tab to see image results"
        ),
        "reset_url": "about:blank",
        "category": "hard",
    },
    {
        "name": "Multi-Tab Workflow",
        "task": (
            "Open duckduckgo.com, search for 'weather'. "
            "Then open a new tab with Ctrl+T, navigate to en.wikipedia.org in that tab, "
            "search for 'Climate', then close the current tab with Ctrl+W"
        ),
        "reset_url": "about:blank",
        "category": "hard",
    },
    {
        "name": "Form Interaction",
        "task": (
            "Go to duckduckgo.com, search for 'calculator', "
            "and scroll down to examine the search results"
        ),
        "reset_url": "about:blank",
        "category": "hard",
    },
    {
        "name": "Deep Scroll + Find",
        "task": (
            "Go to en.wikipedia.org, search for 'Computer science', "
            "click the article, and use Ctrl+F to find the word 'algorithm' on the page"
        ),
        "reset_url": "about:blank",
        "category": "hard",
    },
]


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

@dataclass
class TaskResult:
    task_name: str
    category: str
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
    category = task_info["category"]

    console.print(f"\n  [bold]{category.upper()}[/] | {task_name}")
    console.print(f"  Task: {task_text[:100]}...")

    reset_sandbox(task_info.get("reset_url", "about:blank"))

    # Use ALL improvements from main (defaults)
    vlm_config = VLMConfig(base_url=VLM_BASE_URL, model=VLM_MODEL)
    config = AgentConfig(
        vlm_config=vlm_config,
        max_steps=MAX_STEPS,
        step_delay=STEP_DELAY,
        save_screenshots=False,
        max_history_turns=10,
        vlm_image_format="jpeg",
        vlm_image_quality=75,
        vlm_max_edge=1024,
        # All improvements enabled (defaults on main):
        # coordinate_validation="relaxed" (default)
        # action_feedback=True (default)
        # smart_wait=True (default)
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
        category=category,
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
        "[bold blue]Experiment 17: Cumulative Improvements Validation[/]\n"
        "Validates all 6 merged improvements on standard + harder tasks\n"
        "Config: all defaults from main (JPEG, relaxed validation,\n"
        "action feedback, smart wait)",
        border_style="blue",
    ))

    if not ensure_sandbox_ready():
        return

    results: List[TaskResult] = []

    # --- Standard tasks ---
    console.print(Panel(
        "[bold]Standard Tasks[/] (same as Exp 12-16)",
        border_style="green",
    ))
    for task_info in STANDARD_TASKS:
        result = run_single_test(task_info)
        results.append(result)

    # --- Harder tasks ---
    console.print(Panel(
        "[bold]Harder Tasks[/] (new, not used in optimization)",
        border_style="yellow",
    ))
    for task_info in HARD_TASKS:
        result = run_single_test(task_info)
        results.append(result)

    # ---- Results Table ----
    console.print("\n")
    console.print(Panel("[bold]Experiment 17 Results[/]", border_style="cyan"))

    table = Table(title="Experiment 17: Cumulative Validation (All Improvements)")
    table.add_column("Task", style="bold")
    table.add_column("Category")
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
            r.category,
            outcome_style,
            str(r.step_count),
            f"{r.total_input_tokens:,}",
            str(r.wall_time_seconds),
        )

    console.print(table)

    # ---- Per-category summaries ----
    for cat in ["standard", "hard"]:
        subset = [r for r in results if r.category == cat]
        completed = sum(1 for r in subset if r.outcome == "completed")
        total = len(subset)
        avg_steps = sum(r.step_count for r in subset) / total if total else 0
        avg_tokens = sum(r.total_input_tokens for r in subset) / total if total else 0
        avg_time = sum(r.wall_time_seconds for r in subset) / total if total else 0

        summary = Table(title=f"Summary: {cat} tasks")
        summary.add_column("Metric", style="bold")
        summary.add_column("Value", justify="right")
        summary.add_row("Success Rate", f"{completed}/{total} ({completed/total:.0%})" if total else "N/A")
        summary.add_row("Avg Steps", f"{avg_steps:.1f}")
        summary.add_row("Avg Input Tokens", f"{avg_tokens:,.0f}")
        summary.add_row("Avg Wall Time (s)", f"{avg_time:.1f}")
        console.print(summary)

    # ---- Overall summary ----
    all_completed = sum(1 for r in results if r.outcome == "completed")
    all_total = len(results)
    all_avg_steps = sum(r.step_count for r in results) / all_total
    all_avg_tokens = sum(r.total_input_tokens for r in results) / all_total
    all_avg_time = sum(r.wall_time_seconds for r in results) / all_total

    overall = Table(title="OVERALL (10 tasks)")
    overall.add_column("Metric", style="bold")
    overall.add_column("Value", justify="right")
    overall.add_row("Success Rate", f"{all_completed}/{all_total} ({all_completed/all_total:.0%})")
    overall.add_row("Avg Steps", f"{all_avg_steps:.1f}")
    overall.add_row("Avg Input Tokens", f"{all_avg_tokens:,.0f}")
    overall.add_row("Avg Wall Time (s)", f"{all_avg_time:.1f}")
    console.print(overall)

    # Compare with historical baselines
    console.print("\n[bold]Historical Comparison:[/]")
    console.print("  Exp 8 (original hard tasks, no improvements): 80% (4/5)")
    console.print("  Exp 12 baseline (strict coord validation): 80% (4/5)")
    console.print("  Exp 15 baseline (no action feedback): 80% (4/5)")
    console.print(f"  Exp 17 (all improvements, std tasks): {sum(1 for r in results if r.category == 'standard' and r.outcome == 'completed')}/5")
    console.print(f"  Exp 17 (all improvements, hard tasks): {sum(1 for r in results if r.category == 'hard' and r.outcome == 'completed')}/5")
    console.print(f"  Exp 17 (all improvements, overall): {all_completed}/{all_total} ({all_completed/all_total:.0%})")

    # ---- Save results ----
    output_path = Path("exp17_cumulative_results.json")
    with open(output_path, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    console.print(f"\n[dim]Raw results saved to {output_path}[/]")


if __name__ == "__main__":
    main()
