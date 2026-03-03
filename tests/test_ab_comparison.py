"""
A/B Test Harness: Baseline vs Improved (Sliding Window + Operator Abstraction)

Runs the same set of tasks under two configurations:
  A) Baseline: no sliding window (max_history_turns=0), no operator (legacy sandbox_mode)
  B) Improved: sliding window (max_history_turns=10), operator abstraction (SandboxOperator)

Collects metrics per task: step count, outcome, total input/output tokens, wall time.
Outputs a comparison table at the end.

Usage:
    cd C:\\Users\\guangyang\\Documents\\rpa
    python test_ab_comparison.py
"""

import time
import json
import httpx
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Optional
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
MAX_STEPS = 20          # Cap per task to keep runs bounded
STEP_DELAY = 0.5

# Test tasks — exercise clicking, typing, navigation, scrolling
TASKS = [
    {
        "name": "DuckDuckGo Search",
        "task": "Go to duckduckgo.com and search for 'python programming'",
        "reset_url": "about:blank",
    },
    {
        "name": "YouTube Explore",
        "task": "Open youtube.com and click on the Trending or Explore section",
        "reset_url": "about:blank",
    },
    {
        "name": "Multi-step Search + Scroll",
        "task": "Go to duckduckgo.com, search for 'weather', then scroll down to see more results",
        "reset_url": "about:blank",
    },
]


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

@dataclass
class TaskResult:
    task_name: str
    config_label: str       # "baseline" or "improved"
    outcome: str            # "completed", "failed", "max_steps"
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
    """Navigate Chrome in the sandbox to a known URL."""
    try:
        # Use the /chrome/navigate endpoint
        resp = httpx.post(
            f"{SANDBOX_URL}/chrome/navigate",
            params={"url": url},
            timeout=10,
        )
        if resp.status_code != 200:
            console.print(f"[yellow]Warning: Chrome navigate returned {resp.status_code}[/]")
    except Exception as e:
        console.print(f"[yellow]Warning: Could not reset sandbox: {e}[/]")
    # Wait for page to load
    time.sleep(2)


def ensure_sandbox_ready() -> bool:
    """Check sandbox is running and Chrome is up."""
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


def run_single_test(
    task_info: dict,
    config_label: str,
    agent_config: AgentConfig,
    operator=None,
) -> TaskResult:
    """Run a single task and collect metrics."""
    task_name = task_info["name"]
    task_text = task_info["task"]

    console.print(f"\n  [bold]{config_label.upper()}[/] | {task_name}")
    console.print(f"  Task: {task_text}")

    # Reset sandbox
    reset_sandbox(task_info.get("reset_url", "about:blank"))

    # Create agent
    agent = GUIAgent(config=agent_config, console=console, operator=operator)

    # Run and time it
    t0 = time.time()
    steps = agent.run(task_text)
    wall_time = time.time() - t0

    # Collect token metrics
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

    # Determine outcome
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
        "[bold blue]A/B Comparison Test[/]\n"
        "Baseline (no sliding window, legacy sandbox_mode) vs\n"
        "Improved (sliding window=10, SandboxOperator)",
        border_style="blue",
    ))

    if not ensure_sandbox_ready():
        return

    vlm_config = VLMConfig(base_url=VLM_BASE_URL, model=VLM_MODEL)

    results: List[TaskResult] = []

    # ---- Run A: Baseline ----
    console.print(Panel("[bold]Phase A: Baseline[/] (no sliding window, legacy sandbox path)", border_style="yellow"))

    for task_info in TASKS:
        config_a = AgentConfig(
            vlm_config=vlm_config,
            max_steps=MAX_STEPS,
            step_delay=STEP_DELAY,
            save_screenshots=False,
            sandbox_mode=True,
            sandbox_url=SANDBOX_URL,
            max_history_turns=0,  # No sliding window
        )
        result = run_single_test(task_info, "baseline", config_a, operator=None)
        results.append(result)

    # ---- Run B: Improved ----
    console.print(Panel("[bold]Phase B: Improved[/] (sliding window=10, SandboxOperator)", border_style="green"))

    for task_info in TASKS:
        config_b = AgentConfig(
            vlm_config=vlm_config,
            max_steps=MAX_STEPS,
            step_delay=STEP_DELAY,
            save_screenshots=False,
            max_history_turns=10,  # Sliding window
        )
        operator = SandboxOperator(sandbox_url=SANDBOX_URL)
        result = run_single_test(task_info, "improved", config_b, operator=operator)
        results.append(result)

    # ---- Report ----
    console.print("\n")
    console.print(Panel("[bold]Results Comparison[/]", border_style="cyan"))

    table = Table(title="A/B Comparison: Baseline vs Improved")
    table.add_column("Task", style="bold")
    table.add_column("Config", style="dim")
    table.add_column("Outcome")
    table.add_column("Steps", justify="right")
    table.add_column("Input Tokens", justify="right")
    table.add_column("Output Tokens", justify="right")
    table.add_column("Time (s)", justify="right")
    table.add_column("Tokens/Step", justify="right")

    for r in results:
        tokens_per_step = r.total_input_tokens // max(r.step_count, 1)
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
            f"{r.total_output_tokens:,}",
            str(r.wall_time_seconds),
            f"{tokens_per_step:,}",
        )

    console.print(table)

    # ---- Summary stats ----
    baseline = [r for r in results if r.config_label == "baseline"]
    improved = [r for r in results if r.config_label == "improved"]

    def avg(lst, key):
        vals = [getattr(r, key) for r in lst]
        return sum(vals) / len(vals) if vals else 0

    summary = Table(title="Summary Averages")
    summary.add_column("Metric")
    summary.add_column("Baseline", justify="right")
    summary.add_column("Improved", justify="right")
    summary.add_column("Delta", justify="right")

    for metric, label in [
        ("step_count", "Avg Steps"),
        ("total_input_tokens", "Avg Input Tokens"),
        ("total_output_tokens", "Avg Output Tokens"),
        ("wall_time_seconds", "Avg Wall Time (s)"),
    ]:
        b = avg(baseline, metric)
        i = avg(improved, metric)
        delta = i - b
        pct = (delta / b * 100) if b != 0 else 0
        sign = "+" if delta >= 0 else ""
        summary.add_row(
            label,
            f"{b:,.1f}",
            f"{i:,.1f}",
            f"{sign}{delta:,.1f} ({sign}{pct:.0f}%)",
        )

    # Success rate
    b_success = sum(1 for r in baseline if r.outcome == "completed") / max(len(baseline), 1)
    i_success = sum(1 for r in improved if r.outcome == "completed") / max(len(improved), 1)
    delta_success = i_success - b_success
    summary.add_row(
        "Success Rate",
        f"{b_success:.0%}",
        f"{i_success:.0%}",
        f"{'+' if delta_success >= 0 else ''}{delta_success:.0%}",
    )

    console.print(summary)

    # ---- Per-step token growth analysis ----
    console.print("\n[bold]Per-step input token growth (shows whether sliding window bounds growth):[/]")
    for r in results:
        if r.per_step_input_tokens:
            tokens_str = " -> ".join(f"{t:,}" for t in r.per_step_input_tokens)
            console.print(f"  [{r.config_label}] {r.task_name}: {tokens_str}")

    # ---- Save raw results ----
    output_path = Path("ab_test_results.json")
    with open(output_path, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    console.print(f"\n[dim]Raw results saved to {output_path}[/]")


if __name__ == "__main__":
    main()
