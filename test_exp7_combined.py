"""
Experiment 7: Combined Best Improvements

Combines the two positive findings:
  - Exp 5: JPEG q75, max_edge=1024 (-76% tokens)
  - Exp 6: Ctrl+L navigation hints (-24% steps, -27% time)

Configs:
  A: Baseline — PNG 1344, standard prompt
  B: Combined — JPEG q75 1024 + Ctrl+L enforced prompt

Both use sliding window=10 + SandboxOperator.

Usage:
    python test_exp7_combined.py
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
from rpa_agent.vlm.prompts import SystemPrompts
from rpa_agent.operators.sandbox import SandboxOperator

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SANDBOX_URL = "http://localhost:8000"
VLM_BASE_URL = "http://localhost:23333/api/anthropic"
VLM_MODEL = "claude-opus-4.6-fast"
MAX_STEPS = 20
STEP_DELAY = 0.5

TASKS = [
    {
        "name": "DuckDuckGo Search",
        "task": "Go to duckduckgo.com and search for 'python programming'",
        "reset_url": "about:blank",
    },
    {
        "name": "Google Search",
        "task": "Go to google.com and search for 'artificial intelligence news'",
        "reset_url": "about:blank",
    },
    {
        "name": "Multi-step Search + Scroll",
        "task": "Go to duckduckgo.com, search for 'weather', then scroll down to see more results",
        "reset_url": "about:blank",
    },
]

# Enhanced Ctrl+L navigation section (from Exp 6)
ENHANCED_NAV_SECTION = """### Browser Address Bar Navigation \u2014 CRITICAL WORKFLOW
**ALWAYS use Ctrl+L to focus the address bar.** NEVER click on the address bar directly \u2014 clicking often fails to select existing text, causing URLs to be appended (e.g., 'about:blankgoogle.com').

The ONLY correct sequence for URL navigation is:
1. **hotkey(["ctrl", "l"])** \u2014 focuses address bar AND selects all existing text
2. **type("yoururl.com", press_enter=false)** \u2014 replaces selected text with new URL
3. **hotkey(["Escape"])** \u2014 dismiss autocomplete dropdown
4. **hotkey(["enter"])** \u2014 navigate to the URL

**NEVER DO THIS:** click on address bar then type \u2014 this WILL append text to existing URL.
**ALWAYS DO THIS:** Ctrl+L then type \u2014 this WILL replace existing URL."""


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


def build_enhanced_prompt(operator: SandboxOperator) -> str:
    """Build prompt with Ctrl+L navigation enforcement."""
    base = SystemPrompts.GUI_AGENT_TEMPLATE.replace(
        "{{action_space}}", operator.action_space()
    )
    old_nav = """### Browser Address Bar Navigation
1. To navigate to a URL: **click the address bar** (or use **hotkey(["ctrl", "l"])**), then **type** the URL
2. After typing a URL, the browser shows an **autocomplete dropdown** \u2014 you MUST dismiss it first: press **hotkey(["Escape"])** to close the dropdown, then press **press_key("enter")** to navigate
3. **NEVER click on autocomplete/dropdown suggestions** \u2014 they are unreliable and often do nothing
4. The correct sequence is ALWAYS: **focus address bar \u2192 type URL \u2192 Escape \u2192 Enter** (3 separate actions)
5. If the page doesn't load after Enter, the autocomplete dropdown may have intercepted it \u2014 press **Escape** and try **Enter** again"""
    return base.replace(old_nav, ENHANCED_NAV_SECTION)


def run_single_test(
    task_info: dict,
    config_label: str,
    agent_config: AgentConfig,
    operator=None,
    system_prompt_override=None,
) -> TaskResult:
    task_name = task_info["name"]
    task_text = task_info["task"]

    console.print(f"\n  [bold]{config_label.upper()}[/] | {task_name}")
    console.print(f"  Task: {task_text}")

    reset_sandbox(task_info.get("reset_url", "about:blank"))

    agent = GUIAgent(config=agent_config, console=console, operator=operator)
    if system_prompt_override:
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
        "[bold blue]Experiment 7: Combined Best Improvements[/]\n"
        "A: Baseline \u2014 PNG 1344, standard prompt\n"
        "B: Combined \u2014 JPEG q75 1024 + Ctrl+L enforced prompt",
        border_style="blue",
    ))

    if not ensure_sandbox_ready():
        return

    vlm_config = VLMConfig(base_url=VLM_BASE_URL, model=VLM_MODEL)
    results: List[TaskResult] = []

    # ---- Run A: Baseline ----
    console.print(Panel(
        "[bold]Phase A: Baseline[/] (PNG 1344, standard prompt)",
        border_style="yellow",
    ))

    for task_info in TASKS:
        config_a = AgentConfig(
            vlm_config=vlm_config,
            max_steps=MAX_STEPS,
            step_delay=STEP_DELAY,
            save_screenshots=False,
            max_history_turns=10,
            vlm_image_format="png",
            vlm_max_edge=1344,
        )
        operator_a = SandboxOperator(sandbox_url=SANDBOX_URL)
        result = run_single_test(task_info, "baseline", config_a, operator=operator_a)
        results.append(result)

    # ---- Run B: Combined improvements ----
    console.print(Panel(
        "[bold]Phase B: Combined[/] (JPEG q75 1024 + Ctrl+L enforced)",
        border_style="green",
    ))

    for task_info in TASKS:
        config_b = AgentConfig(
            vlm_config=vlm_config,
            max_steps=MAX_STEPS,
            step_delay=STEP_DELAY,
            save_screenshots=False,
            max_history_turns=10,
            vlm_image_format="jpeg",
            vlm_image_quality=75,
            vlm_max_edge=1024,
        )
        operator_b = SandboxOperator(sandbox_url=SANDBOX_URL)
        enhanced_prompt = build_enhanced_prompt(operator_b)
        result = run_single_test(
            task_info, "combined", config_b,
            operator=operator_b,
            system_prompt_override=enhanced_prompt,
        )
        results.append(result)

    # ---- Report ----
    console.print("\n")
    console.print(Panel("[bold]Results: Baseline vs Combined Improvements[/]", border_style="cyan"))

    table = Table(title="Experiment 7: Baseline vs Combined (JPEG + Ctrl+L)")
    table.add_column("Task", style="bold")
    table.add_column("Config", style="dim")
    table.add_column("Outcome")
    table.add_column("Steps", justify="right")
    table.add_column("Input Tokens", justify="right")
    table.add_column("Output Tokens", justify="right")
    table.add_column("Time (s)", justify="right")
    table.add_column("Tokens/Step", justify="right")

    for r in results:
        outcome_style = {
            "completed": "[green]completed[/]",
            "failed": "[red]failed[/]",
            "max_steps": "[yellow]max_steps[/]",
        }.get(r.outcome, r.outcome)
        tps = r.total_input_tokens // max(r.step_count, 1)
        table.add_row(
            r.task_name,
            r.config_label,
            outcome_style,
            str(r.step_count),
            f"{r.total_input_tokens:,}",
            f"{r.total_output_tokens:,}",
            str(r.wall_time_seconds),
            f"{tps:,}",
        )

    console.print(table)

    # ---- Summary ----
    baseline = [r for r in results if r.config_label == "baseline"]
    combined = [r for r in results if r.config_label == "combined"]

    def avg(lst, key):
        vals = [getattr(r, key) for r in lst]
        return sum(vals) / len(vals) if vals else 0

    summary = Table(title="Summary: Baseline vs Combined")
    summary.add_column("Metric")
    summary.add_column("Baseline", justify="right")
    summary.add_column("Combined", justify="right")
    summary.add_column("Delta", justify="right")

    for metric, label in [
        ("step_count", "Avg Steps"),
        ("total_input_tokens", "Avg Input Tokens"),
        ("total_output_tokens", "Avg Output Tokens"),
        ("wall_time_seconds", "Avg Wall Time (s)"),
    ]:
        b = avg(baseline, metric)
        i = avg(combined, metric)
        delta = i - b
        pct = (delta / b * 100) if b != 0 else 0
        sign = "+" if delta >= 0 else ""
        summary.add_row(
            label,
            f"{b:,.1f}",
            f"{i:,.1f}",
            f"{sign}{delta:,.1f} ({sign}{pct:.0f}%)",
        )

    b_success = sum(1 for r in baseline if r.outcome == "completed") / max(len(baseline), 1)
    c_success = sum(1 for r in combined if r.outcome == "completed") / max(len(combined), 1)
    delta_success = c_success - b_success
    summary.add_row(
        "Success Rate",
        f"{b_success:.0%}",
        f"{c_success:.0%}",
        f"{'+' if delta_success >= 0 else ''}{delta_success:.0%}",
    )

    console.print(summary)

    # ---- Per-step token comparison ----
    console.print("\n[bold]Per-step input token growth:[/]")
    for r in results:
        if r.per_step_input_tokens:
            tokens_str = " -> ".join(f"{t:,}" for t in r.per_step_input_tokens)
            console.print(f"  [{r.config_label}] {r.task_name}: {tokens_str}")

    # ---- Save results ----
    output_path = Path("exp7_combined_results.json")
    with open(output_path, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    console.print(f"\n[dim]Raw results saved to {output_path}[/]")


if __name__ == "__main__":
    main()
