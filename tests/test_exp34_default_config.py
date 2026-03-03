"""
Experiment 34: Default Config Validation

Validates that changing adaptive_prompt and auto_navigate defaults to True
works correctly with default AgentConfig (no explicit flag overrides).

This ensures that new users get the optimized behavior out of the box.

Usage:
    python test_exp34_default_config.py
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

    console.print(f"\n  [bold]{task_name}[/]")
    console.print(f"  Task: {task_text[:100]}...")

    reset_sandbox("about:blank")

    # Use DEFAULT config — only set VLM connection params
    vlm_config = VLMConfig(base_url=VLM_BASE_URL, model=VLM_MODEL)
    config = AgentConfig(vlm_config=vlm_config, save_screenshots=False)
    operator = SandboxOperator(sandbox_url=SANDBOX_URL)
    agent = GUIAgent(config=config, console=console, operator=operator)

    # Verify defaults are active
    console.print(f"  adaptive_prompt={config.adaptive_prompt}, auto_navigate={config.auto_navigate}")
    console.print(f"  action_feedback={config.action_feedback}, smart_wait={config.smart_wait}")
    console.print(f"  step_budget_awareness={config.step_budget_awareness}")

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
        "[bold blue]Experiment 34: Default Config Validation[/]\n"
        "Validates new defaults: adaptive_prompt=True, auto_navigate=True\n"
        "Uses AgentConfig() with NO explicit flag overrides",
        border_style="blue",
    ))

    if not ensure_sandbox_ready():
        return

    results: List[TaskResult] = []

    console.print(Panel(
        "[bold]Running with DEFAULT config[/] (all new defaults active)",
        border_style="green",
    ))
    for task_info in TASKS:
        result = run_single_test(task_info)
        results.append(result)

    # ---- Results Table ----
    console.print("\n")
    console.print(Panel("[bold]Experiment 34 Results[/]", border_style="cyan"))

    table = Table(title="Experiment 34: Default Config (all optimizations active)")
    table.add_column("Task", style="bold")
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

    summary = Table(title="Summary: Default Config")
    summary.add_column("Metric", style="bold")
    summary.add_column("Value", justify="right")
    summary.add_row("Success Rate", f"{completed}/{total} ({completed/total:.0%})" if total else "N/A")
    summary.add_row("Avg Steps", f"{avg_steps:.1f}")
    summary.add_row("Avg Input Tokens", f"{avg_tokens:,.0f}")
    summary.add_row("Avg Wall Time (s)", f"{avg_time:.1f}")

    # Comparison with Exp 33 standard results
    summary.add_row("", "")
    summary.add_row("[dim]Exp 33 Standard Avg Steps[/]", "[dim]5.8[/]")
    summary.add_row("[dim]Exp 33 Standard Avg Tokens[/]", "[dim]552,900[/]")
    console.print(summary)

    # ---- Save results ----
    output_path = Path("exp34_default_config_results.json")
    with open(output_path, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    console.print(f"\n[dim]Raw results saved to {output_path}[/]")


if __name__ == "__main__":
    main()
