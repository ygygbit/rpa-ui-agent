"""
Experiment 30: Expanded Adaptive Hints

Tests whether expanding the adaptive hint system with 2 additional
hint categories improves performance beyond Exp 29's 3-category hints.

New hint categories added:
  1. URL navigation: "Press Enter immediately after typing URL, don't Escape first"
  2. Wikipedia ToC: "Use Table of Contents links instead of scrolling"

Comparison: Exp 29 adaptive results (saved) vs expanded hints (live run)

Usage:
    python test_exp30_expanded_hints.py
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

TASKS = [
    {
        "name": "DuckDuckGo Search",
        "task": "Go to duckduckgo.com and search for 'python programming'",
        "reset_url": "about:blank",
    },
    {
        "name": "Wikipedia Search",
        "task": (
            "Go to en.wikipedia.org, search for 'Artificial intelligence', "
            "and click the search button to see results"
        ),
        "reset_url": "about:blank",
    },
    {
        "name": "Multi-Step Navigation",
        "task": (
            "Go to duckduckgo.com, search for 'weather forecast', "
            "then scroll down to see more results"
        ),
        "reset_url": "about:blank",
    },
    {
        "name": "DuckDuckGo Click Result",
        "task": (
            "Go to duckduckgo.com, search for 'OpenAI', "
            "and click on the first search result link"
        ),
        "reset_url": "about:blank",
    },
    {
        "name": "Wikipedia Article Scroll",
        "task": (
            "Go to en.wikipedia.org, search for 'Machine learning', "
            "click on the article, and scroll down to find the 'History' section"
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
    hints_injected: str
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

    console.print(f"\n  [bold]EXPANDED[/] | {task_name}")
    console.print(f"  Task: {task_text[:100]}...")

    reset_sandbox(task_info.get("reset_url", "about:blank"))

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
        coordinate_validation="relaxed",
        action_feedback=True,
        smart_wait=True,
        smart_wait_delay=1.5,
        step_budget_awareness=True,
        adaptive_prompt=True,
    )
    operator = SandboxOperator(sandbox_url=SANDBOX_URL)
    agent = GUIAgent(config=config, console=console, operator=operator)

    # Show which hints are injected
    hints_text = agent._build_adaptive_hints(task_text)
    if hints_text:
        console.print(f"  [cyan]Hints ({len(hints_text.split(chr(10)))} total):[/]")
        for h in hints_text.split("\n"):
            console.print(f"    {h[:100]}...")

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
        config_label="expanded",
        outcome=outcome,
        step_count=len(steps),
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        wall_time_seconds=round(wall_time, 1),
        hints_injected=hints_text[:200] if hints_text else "none",
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
        "[bold blue]Experiment 30: Expanded Adaptive Hints[/]\n"
        "Tests expanded hints (5 categories) vs Exp 29 baseline (3 categories)\n"
        "New: URL nav hint (skip Escape), Wikipedia ToC hint",
        border_style="blue",
    ))

    if not ensure_sandbox_ready():
        return

    # Run expanded hints
    expanded_results: List[TaskResult] = []
    console.print(Panel(
        "[bold]Running Expanded Hints[/] (adaptive_prompt=True, 5 hint categories)",
        border_style="green",
    ))
    for task_info in TASKS:
        result = run_single_test(task_info)
        expanded_results.append(result)

    # Load Exp 29 baseline (adaptive config) for comparison
    exp29_path = Path("exp29_adaptive_prompt_results.json")
    exp29_adaptive = []
    if exp29_path.exists():
        with open(exp29_path) as f:
            all_exp29 = json.load(f)
            exp29_adaptive = [r for r in all_exp29 if r["config_label"] == "adaptive"]
        console.print(f"\n[dim]Loaded {len(exp29_adaptive)} Exp 29 adaptive results for comparison[/]")
    else:
        console.print("[yellow]Warning: exp29_adaptive_prompt_results.json not found, no comparison[/]")

    # ---- Comparison Table ----
    console.print("\n")
    console.print(Panel("[bold]Experiment 30 Results[/]", border_style="cyan"))

    table = Table(title="Experiment 30: Expanded vs Exp 29 Adaptive Hints")
    table.add_column("Task", style="bold")
    table.add_column("Config")
    table.add_column("Outcome")
    table.add_column("Steps", justify="right")
    table.add_column("Input Tokens", justify="right")
    table.add_column("Time (s)", justify="right")

    # Add Exp 29 adaptive results
    for r in exp29_adaptive:
        outcome_style = {
            "completed": "[green]completed[/]",
            "failed": "[red]failed[/]",
            "max_steps": "[yellow]max_steps[/]",
        }.get(r["outcome"], r["outcome"])
        table.add_row(
            r["task_name"],
            "exp29",
            outcome_style,
            str(r["step_count"]),
            f"{r['total_input_tokens']:,}",
            str(r["wall_time_seconds"]),
        )

    # Add expanded results
    for r in expanded_results:
        outcome_style = {
            "completed": "[green]completed[/]",
            "failed": "[red]failed[/]",
            "max_steps": "[yellow]max_steps[/]",
        }.get(r.outcome, r.outcome)
        table.add_row(
            r.task_name,
            "expanded",
            outcome_style,
            str(r.step_count),
            f"{r.total_input_tokens:,}",
            str(r.wall_time_seconds),
        )

    console.print(table)

    # ---- Per-task delta ----
    console.print("\n")
    delta_table = Table(title="Per-Task Step Comparison (Exp 29 Adaptive → Expanded)")
    delta_table.add_column("Task", style="bold")
    delta_table.add_column("Exp 29 Steps", justify="right")
    delta_table.add_column("Expanded Steps", justify="right")
    delta_table.add_column("Delta", justify="right")
    delta_table.add_column("New Hints")

    for task_info in TASKS:
        name = task_info["name"]
        exp29_r = next((r for r in exp29_adaptive if r["task_name"] == name), None)
        expanded_r = next((r for r in expanded_results if r.task_name == name), None)
        if exp29_r and expanded_r:
            delta = expanded_r.step_count - exp29_r["step_count"]
            delta_str = f"[green]{delta}[/]" if delta < 0 else f"[red]+{delta}[/]" if delta > 0 else "0"
            # Identify which NEW hints this task gets
            new_hints = []
            task_lower = task_info["task"].lower()
            if any(kw in task_lower for kw in ["go to", "navigate to", "open", "visit"]):
                new_hints.append("URL nav")
            if "wikipedia" in task_lower and any(kw in task_lower for kw in ["section", "find", "scroll"]):
                new_hints.append("Wiki ToC")
            delta_table.add_row(
                name,
                str(exp29_r["step_count"]),
                str(expanded_r.step_count),
                delta_str,
                ", ".join(new_hints) if new_hints else "none",
            )

    console.print(delta_table)

    # ---- Summaries ----
    # Expanded
    completed = sum(1 for r in expanded_results if r.outcome == "completed")
    total = len(expanded_results)
    avg_steps = sum(r.step_count for r in expanded_results) / total if total else 0
    avg_tokens = sum(r.total_input_tokens for r in expanded_results) / total if total else 0
    avg_time = sum(r.wall_time_seconds for r in expanded_results) / total if total else 0

    summary = Table(title="Summary: Expanded Hints")
    summary.add_column("Metric", style="bold")
    summary.add_column("Value", justify="right")
    summary.add_row("Success Rate", f"{completed}/{total} ({completed/total:.0%})" if total else "N/A")
    summary.add_row("Avg Steps", f"{avg_steps:.1f}")
    summary.add_row("Avg Input Tokens", f"{avg_tokens:,.0f}")
    summary.add_row("Avg Wall Time (s)", f"{avg_time:.1f}")
    console.print(summary)

    # Exp 29 comparison summary
    if exp29_adaptive:
        e29_total = len(exp29_adaptive)
        e29_completed = sum(1 for r in exp29_adaptive if r["outcome"] == "completed")
        e29_avg_steps = sum(r["step_count"] for r in exp29_adaptive) / e29_total
        e29_avg_tokens = sum(r["total_input_tokens"] for r in exp29_adaptive) / e29_total
        e29_avg_time = sum(r["wall_time_seconds"] for r in exp29_adaptive) / e29_total

        comp = Table(title="Comparison: Exp 29 Adaptive vs Expanded")
        comp.add_column("Metric", style="bold")
        comp.add_column("Exp 29", justify="right")
        comp.add_column("Expanded", justify="right")
        comp.add_column("Delta", justify="right")
        comp.add_row("Success Rate", f"{e29_completed}/{e29_total}", f"{completed}/{total}", "—")
        step_delta = avg_steps - e29_avg_steps
        comp.add_row("Avg Steps", f"{e29_avg_steps:.1f}", f"{avg_steps:.1f}",
                     f"[green]{step_delta:+.1f}[/]" if step_delta < 0 else f"[red]{step_delta:+.1f}[/]" if step_delta > 0 else "0")
        tok_delta_pct = (avg_tokens - e29_avg_tokens) / e29_avg_tokens * 100 if e29_avg_tokens else 0
        comp.add_row("Avg Input Tokens", f"{e29_avg_tokens:,.0f}", f"{avg_tokens:,.0f}",
                     f"{tok_delta_pct:+.0f}%")
        time_delta = avg_time - e29_avg_time
        comp.add_row("Avg Wall Time", f"{e29_avg_time:.1f}s", f"{avg_time:.1f}s",
                     f"{time_delta:+.1f}s")
        console.print(comp)

    # ---- Save results ----
    output_path = Path("exp30_expanded_hints_results.json")
    with open(output_path, "w") as f:
        json.dump([asdict(r) for r in expanded_results], f, indent=2)
    console.print(f"\n[dim]Raw results saved to {output_path}[/]")


if __name__ == "__main__":
    main()
