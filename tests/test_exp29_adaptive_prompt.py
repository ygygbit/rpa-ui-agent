"""
Experiment 29: Adaptive Prompt

Tests whether injecting task-specific hints into the VLM prompt
(e.g., "use Ctrl+F to find sections") reduces step count compared
to the generic prompt.

Hypothesis: Task-specific hints will help the VLM choose better
strategies, especially for section-finding tasks (Wikipedia Article Scroll)
and search tasks, reducing unnecessary scrolling.

Configs:
  A (baseline): adaptive_prompt=False (no hints)
  B (adaptive): adaptive_prompt=True (inject keyword-based hints)

Usage:
    python test_exp29_adaptive_prompt.py
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
        "expected_hints": ["Enter to submit"],
    },
    {
        "name": "Wikipedia Search",
        "task": (
            "Go to en.wikipedia.org, search for 'Artificial intelligence', "
            "and click the search button to see results"
        ),
        "reset_url": "about:blank",
        "expected_hints": [],  # "click" in task disables search hint
    },
    {
        "name": "Multi-Step Navigation",
        "task": (
            "Go to duckduckgo.com, search for 'weather forecast', "
            "then scroll down to see more results"
        ),
        "reset_url": "about:blank",
        "expected_hints": ["Enter to submit"],
    },
    {
        "name": "DuckDuckGo Click Result",
        "task": (
            "Go to duckduckgo.com, search for 'OpenAI', "
            "and click on the first search result link"
        ),
        "reset_url": "about:blank",
        "expected_hints": [],  # "click" disables search hint
    },
    {
        "name": "Wikipedia Article Scroll",
        "task": (
            "Go to en.wikipedia.org, search for 'Machine learning', "
            "click on the article, and scroll down to find the 'History' section"
        ),
        "reset_url": "about:blank",
        "expected_hints": ["Ctrl+F"],  # "find the" triggers section-finding hint
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


def run_single_test(task_info: dict, config_label: str,
                    adaptive: bool) -> TaskResult:
    task_name = task_info["name"]
    task_text = task_info["task"]

    console.print(f"\n  [bold]{config_label.upper()}[/] | {task_name}")
    console.print(f"  Task: {task_text[:100]}...")
    console.print(f"  adaptive_prompt={adaptive}")

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
        adaptive_prompt=adaptive,
    )
    operator = SandboxOperator(sandbox_url=SANDBOX_URL)
    agent = GUIAgent(config=config, console=console, operator=operator)

    # Check what hints would be injected
    hints_text = agent._build_adaptive_hints(task_text) if adaptive else ""
    if hints_text:
        console.print(f"  [cyan]Hints injected:[/] {hints_text[:120]}...")

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
        "[bold blue]Experiment 29: Adaptive Prompt[/]\n"
        "Compares baseline (no hints) vs adaptive_prompt=True (task-specific hints)\n"
        "Tests whether keyword-based strategy hints reduce step count",
        border_style="blue",
    ))

    if not ensure_sandbox_ready():
        return

    results: List[TaskResult] = []

    # --- Config A: Baseline ---
    console.print(Panel(
        "[bold]Config A: Baseline[/] (adaptive_prompt=False)",
        border_style="yellow",
    ))
    for task_info in TASKS:
        result = run_single_test(task_info, "baseline", adaptive=False)
        results.append(result)

    # --- Config B: Adaptive Prompt ---
    console.print(Panel(
        "[bold]Config B: Adaptive Prompt[/] (adaptive_prompt=True)",
        border_style="green",
    ))
    for task_info in TASKS:
        result = run_single_test(task_info, "adaptive", adaptive=True)
        results.append(result)

    # ---- Comparison Table ----
    console.print("\n")
    console.print(Panel("[bold]Experiment 29 Results[/]", border_style="cyan"))

    table = Table(title="Experiment 29: Adaptive Prompt")
    table.add_column("Task", style="bold")
    table.add_column("Config")
    table.add_column("Outcome")
    table.add_column("Steps", justify="right")
    table.add_column("Input Tokens", justify="right")
    table.add_column("Time (s)", justify="right")
    table.add_column("Hints")

    for r in results:
        outcome_style = {
            "completed": "[green]completed[/]",
            "failed": "[red]failed[/]",
            "max_steps": "[yellow]max_steps[/]",
        }.get(r.outcome, r.outcome)
        hint_short = r.hints_injected[:40] + "..." if len(r.hints_injected) > 40 else r.hints_injected
        table.add_row(
            r.task_name,
            r.config_label,
            outcome_style,
            str(r.step_count),
            f"{r.total_input_tokens:,}",
            str(r.wall_time_seconds),
            hint_short,
        )

    console.print(table)

    # ---- Per-config summaries ----
    for label in ["baseline", "adaptive"]:
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
    delta_table = Table(title="Per-Task Step Comparison")
    delta_table.add_column("Task", style="bold")
    delta_table.add_column("Baseline Steps", justify="right")
    delta_table.add_column("Adaptive Steps", justify="right")
    delta_table.add_column("Delta", justify="right")
    delta_table.add_column("Hints Active")

    for task_info in TASKS:
        name = task_info["name"]
        baseline = next((r for r in results if r.task_name == name and r.config_label == "baseline"), None)
        adaptive = next((r for r in results if r.task_name == name and r.config_label == "adaptive"), None)
        if baseline and adaptive:
            delta = adaptive.step_count - baseline.step_count
            delta_str = f"[green]{delta}[/]" if delta < 0 else f"[red]+{delta}[/]" if delta > 0 else "0"
            has_hints = "yes" if adaptive.hints_injected != "none" else "no"
            delta_table.add_row(
                name,
                str(baseline.step_count),
                str(adaptive.step_count),
                delta_str,
                has_hints,
            )

    console.print(delta_table)

    # ---- Save results ----
    output_path = Path("exp29_adaptive_prompt_results.json")
    with open(output_path, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    console.print(f"\n[dim]Raw results saved to {output_path}[/]")


if __name__ == "__main__":
    main()
