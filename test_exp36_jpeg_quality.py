"""
Experiment 36: JPEG Quality Reduction

Tests whether lowering JPEG quality from 75 to 50 maintains accuracy
while reducing per-step token cost. Resolution stays at 1024px.

JPEG quality 50 should produce visually similar images with more
compression artifacts but text and UI elements remain identifiable.

Configs:
  A (baseline): vlm_image_quality=75 (current default)
  B (reduced):  vlm_image_quality=50

Usage:
    python test_exp36_jpeg_quality.py
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
    config_label: str
    outcome: str
    step_count: int
    total_input_tokens: int
    total_output_tokens: int
    wall_time_seconds: float
    jpeg_quality: int
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
                    quality: int) -> TaskResult:
    task_name = task_info["name"]
    task_text = task_info["task"]

    console.print(f"\n  [bold]{config_label.upper()}[/] | {task_name}")
    console.print(f"  Task: {task_text[:100]}...")
    console.print(f"  vlm_image_quality={quality}")

    reset_sandbox("about:blank")

    vlm_config = VLMConfig(base_url=VLM_BASE_URL, model=VLM_MODEL)
    config = AgentConfig(
        vlm_config=vlm_config,
        max_steps=MAX_STEPS,
        step_delay=STEP_DELAY,
        save_screenshots=False,
        vlm_image_quality=quality,
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
        jpeg_quality=quality,
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
        "[bold blue]Experiment 36: JPEG Quality Reduction[/]\n"
        "Compares q75 (current) vs q50 for screenshot compression\n"
        "Resolution stays at 1024px. Expected: lower tokens, same accuracy",
        border_style="blue",
    ))

    if not ensure_sandbox_ready():
        return

    results: List[TaskResult] = []

    # --- Config A: q75 (baseline) ---
    console.print(Panel(
        "[bold]Config A: q75[/] (current default)",
        border_style="yellow",
    ))
    for task_info in TASKS:
        result = run_single_test(task_info, "q75", quality=75)
        results.append(result)

    # --- Config B: q50 ---
    console.print(Panel(
        "[bold]Config B: q50[/] (reduced quality)",
        border_style="green",
    ))
    for task_info in TASKS:
        result = run_single_test(task_info, "q50", quality=50)
        results.append(result)

    # ---- Comparison Table ----
    console.print("\n")
    console.print(Panel("[bold]Experiment 36 Results[/]", border_style="cyan"))

    table = Table(title="Experiment 36: JPEG Quality Comparison")
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
    for label in ["q75", "q50"]:
        subset = [r for r in results if r.config_label == label]
        completed = sum(1 for r in subset if r.outcome == "completed")
        total = len(subset)
        avg_steps = sum(r.step_count for r in subset) / total if total else 0
        avg_tokens = sum(r.total_input_tokens for r in subset) / total if total else 0
        avg_time = sum(r.wall_time_seconds for r in subset) / total if total else 0
        avg_per_step_tokens = avg_tokens / avg_steps if avg_steps > 0 else 0

        summary = Table(title=f"Summary: {label}")
        summary.add_column("Metric", style="bold")
        summary.add_column("Value", justify="right")
        summary.add_row("Success Rate", f"{completed}/{total} ({completed/total:.0%})" if total else "N/A")
        summary.add_row("Avg Steps", f"{avg_steps:.1f}")
        summary.add_row("Avg Input Tokens", f"{avg_tokens:,.0f}")
        summary.add_row("Avg Tokens/Step", f"{avg_per_step_tokens:,.0f}")
        summary.add_row("Avg Wall Time (s)", f"{avg_time:.1f}")
        console.print(summary)

    # ---- Per-task delta ----
    console.print("\n")
    delta_table = Table(title="Per-Task Comparison (q75 vs q50)")
    delta_table.add_column("Task", style="bold")
    delta_table.add_column("q75 Steps", justify="right")
    delta_table.add_column("q50 Steps", justify="right")
    delta_table.add_column("Step Delta", justify="right")
    delta_table.add_column("q75 Tok/Step", justify="right")
    delta_table.add_column("q50 Tok/Step", justify="right")
    delta_table.add_column("Tok/Step Delta", justify="right")

    for task_info in TASKS:
        name = task_info["name"]
        rq75 = next((r for r in results if r.task_name == name and r.config_label == "q75"), None)
        rq50 = next((r for r in results if r.task_name == name and r.config_label == "q50"), None)
        if rq75 and rq50:
            step_delta = rq50.step_count - rq75.step_count
            step_str = f"[green]{step_delta}[/]" if step_delta < 0 else f"[red]+{step_delta}[/]" if step_delta > 0 else "0"
            q75_per = rq75.total_input_tokens // rq75.step_count if rq75.step_count else 0
            q50_per = rq50.total_input_tokens // rq50.step_count if rq50.step_count else 0
            tok_delta_pct = (q50_per - q75_per) / q75_per * 100 if q75_per else 0
            tok_str = f"[green]{tok_delta_pct:+.0f}%[/]" if tok_delta_pct < 0 else f"[red]{tok_delta_pct:+.0f}%[/]" if tok_delta_pct > 0 else "0%"
            delta_table.add_row(
                name,
                str(rq75.step_count),
                str(rq50.step_count),
                step_str,
                f"{q75_per:,}",
                f"{q50_per:,}",
                tok_str,
            )

    console.print(delta_table)

    # ---- Save results ----
    output_path = Path("exp36_jpeg_quality_results.json")
    with open(output_path, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    console.print(f"\n[dim]Raw results saved to {output_path}[/]")


if __name__ == "__main__":
    main()
