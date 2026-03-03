"""
Experiment 105: max_steps=35 vs 25 on Hard Tasks

Exp 104 showed 6/8 (75%) on hard tasks, with 2 failures at max_steps.
Tests whether a higher step budget helps complete the harder tasks.
Uses only the tasks that failed or were borderline in Exp 104.

Configs:
  A (ms25): max_steps=25 (current default)
  B (ms35): max_steps=35

Usage:
    python test_exp105_max_steps_35_hard.py
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

SANDBOX_URL = "http://localhost:8000"
VLM_BASE_URL = "http://localhost:23333/api/anthropic"
VLM_MODEL = "claude-opus-4.6-fast"

# Focus on the hardest tasks from Exp 104
TASKS = [
    {
        "name": "Wikipedia Link Chain",
        "task": "Go to en.wikipedia.org, search for 'Albert Einstein', click on the article, then click the link to 'Theory of relativity' within the article text",
    },
    {
        "name": "DuckDuckGo Region Filter",
        "task": "Go to duckduckgo.com, search for 'best restaurants', then click on 'All Regions' dropdown and select a specific region",
    },
    {
        "name": "Wikipedia Table of Contents",
        "task": "Go to en.wikipedia.org, search for 'Python (programming language)', click the article, and navigate to the 'Libraries' section using the table of contents",
    },
    {
        "name": "Wikipedia History Section",
        "task": "Go to en.wikipedia.org, search for 'Computer science', click the article, scroll down to find and read the 'History' section",
    },
    {
        "name": "Wikipedia External Links",
        "task": "Go to en.wikipedia.org, search for 'Linux', click the article, and scroll to the very bottom to find the 'External links' section",
    },
]

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

console = Console()

def reset_sandbox(url="about:blank"):
    try:
        resp = httpx.post(f"{SANDBOX_URL}/chrome/navigate", params={"url": url}, timeout=10)
        if resp.status_code != 200:
            console.print(f"[yellow]Warning: Chrome navigate returned {resp.status_code}[/]")
    except Exception as e:
        console.print(f"[yellow]Warning: Could not reset sandbox: {e}[/]")
    time.sleep(2)

def ensure_sandbox_ready():
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

def run_single_test(task_info, config_label, max_steps=25):
    task_name = task_info["name"]
    task_text = task_info["task"]
    console.print(f"\n  [bold]{config_label.upper()}[/] | {task_name}")
    reset_sandbox("about:blank")
    vlm_config = VLMConfig(base_url=VLM_BASE_URL, model=VLM_MODEL)
    config = AgentConfig(
        vlm_config=vlm_config,
        max_steps=max_steps,
        save_screenshots=False,
    )
    operator = SandboxOperator(sandbox_url=SANDBOX_URL)
    agent = GUIAgent(config=config, console=console, operator=operator)
    t0 = time.time()
    steps = agent.run(task_text)
    wall_time = time.time() - t0
    total_in, total_out, per_step_in = 0, 0, []
    for step in steps:
        if step.token_usage:
            inp = step.token_usage.get("input_tokens", 0)
            out = step.token_usage.get("output_tokens", 0)
            total_in += inp
            total_out += out
            per_step_in.append(inp)
    outcome = "completed" if agent.state == AgentState.COMPLETED else ("failed" if agent.state == AgentState.FAILED else "max_steps")
    result = TaskResult(task_name=task_name, config_label=config_label, outcome=outcome,
                        step_count=len(steps), total_input_tokens=total_in, total_output_tokens=total_out,
                        wall_time_seconds=round(wall_time, 1), per_step_input_tokens=per_step_in)
    console.print(f"  => {outcome} in {len(steps)} steps, {total_in:,} in / {total_out:,} out tokens, {wall_time:.1f}s")
    return result

def main():
    console.print(Panel.fit(
        "[bold blue]Experiment 105: max_steps=35 vs 25 on Hard Tasks[/]\n"
        "Testing whether more steps helps complete harder tasks",
        border_style="blue",
    ))
    if not ensure_sandbox_ready():
        return
    results: List[TaskResult] = []

    console.print(Panel("[bold]Config A: max_steps=25[/] (current default)", border_style="yellow"))
    for task_info in TASKS:
        results.append(run_single_test(task_info, "ms25", max_steps=25))

    console.print(Panel("[bold]Config B: max_steps=35[/]", border_style="green"))
    for task_info in TASKS:
        results.append(run_single_test(task_info, "ms35", max_steps=35))

    # Results table
    console.print("\n")
    table = Table(title="Experiment 105: max_steps=35 vs 25 on Hard Tasks")
    table.add_column("Task", style="bold")
    table.add_column("Config")
    table.add_column("Outcome")
    table.add_column("Steps", justify="right")
    table.add_column("Input Tokens", justify="right")
    table.add_column("Tok/Step", justify="right")
    table.add_column("Time (s)", justify="right")
    for r in results:
        os = {"completed": "[green]completed[/]", "failed": "[red]failed[/]", "max_steps": "[yellow]max_steps[/]"}.get(r.outcome, r.outcome)
        tok_per_step = r.total_input_tokens // r.step_count if r.step_count else 0
        table.add_row(r.task_name, r.config_label, os, str(r.step_count), f"{r.total_input_tokens:,}",
                      f"{tok_per_step:,}", str(r.wall_time_seconds))
    console.print(table)

    for label in ["ms25", "ms35"]:
        subset = [r for r in results if r.config_label == label]
        completed = sum(1 for r in subset if r.outcome == "completed")
        total = len(subset)
        avg_steps = sum(r.step_count for r in subset) / total
        avg_tokens = sum(r.total_input_tokens for r in subset) / total
        avg_time = sum(r.wall_time_seconds for r in subset) / total
        total_tok = sum(r.total_input_tokens for r in subset)
        total_steps = sum(r.step_count for r in subset)
        avg_tok_per_step = total_tok // total_steps if total_steps else 0
        s = Table(title=f"Summary: {label}")
        s.add_column("Metric", style="bold")
        s.add_column("Value", justify="right")
        s.add_row("Success Rate", f"{completed}/{total} ({completed/total:.0%})")
        s.add_row("Avg Steps", f"{avg_steps:.1f}")
        s.add_row("Avg Input Tokens", f"{avg_tokens:,.0f}")
        s.add_row("Avg Tok/Step", f"{avg_tok_per_step:,}")
        s.add_row("Avg Wall Time (s)", f"{avg_time:.1f}")
        console.print(s)

    output_path = Path("exp105_max_steps_35_hard_results.json")
    with open(output_path, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    console.print(f"\n[dim]Raw results saved to {output_path}[/]")

if __name__ == "__main__":
    main()
