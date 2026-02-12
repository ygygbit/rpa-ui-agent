"""
Command-line interface for the RPA UI Agent.
"""

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from .agent import GUIAgent, AgentConfig
from .vlm import VLMConfig

app = typer.Typer(
    name="rpa-agent",
    help="Vision-Language Model based RPA UI Control Agent",
    add_completion=False
)
console = Console()


@app.command()
def run(
    task: str = typer.Argument(..., help="Task to accomplish"),
    max_steps: int = typer.Option(50, "--max-steps", "-n", help="Maximum steps"),
    step_delay: float = typer.Option(0.5, "--delay", "-d", help="Delay between steps"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Don't execute actions"),
    confirm: bool = typer.Option(False, "--confirm", "-c", help="Confirm each action"),
    save_screenshots: bool = typer.Option(True, "--screenshots/--no-screenshots", help="Save screenshots"),
    screenshot_dir: str = typer.Option("./screenshots", "--screenshot-dir", help="Screenshot directory"),
    plan: bool = typer.Option(False, "--plan", "-p", help="Create plan before execution"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save history to JSON file"),
    base_url: str = typer.Option(
        "http://localhost:23333/api/anthropic",
        "--base-url",
        help="VLM API base URL"
    ),
    model: str = typer.Option(
        "claude-opus-4.6-1m",
        "--model",
        "-m",
        help="Model name"
    ),
):
    """
    Run the GUI agent to accomplish a task.

    Examples:
        rpa-agent run "Open Chrome and go to google.com"
        rpa-agent run "Click the search button" --max-steps 10
        rpa-agent run "Fill out the form" --plan --confirm
    """
    console.print(Panel.fit(
        "[bold blue]RPA UI Agent[/]\nVision-Language Model based GUI Automation",
        border_style="blue"
    ))

    # Create configuration
    vlm_config = VLMConfig(
        base_url=base_url,
        model=model
    )

    config = AgentConfig(
        vlm_config=vlm_config,
        max_steps=max_steps,
        step_delay=step_delay,
        dry_run=dry_run,
        confirm_actions=confirm,
        save_screenshots=save_screenshots,
        screenshot_dir=Path(screenshot_dir)
    )

    # Create and run agent
    agent = GUIAgent(config=config, console=console)

    try:
        if plan:
            steps = agent.run_with_plan(task)
        else:
            steps = agent.run(task)

        # Save history if requested
        if output:
            agent.save_history(Path(output))
            console.print(f"\n[dim]History saved to {output}[/]")

        # Summary
        successful = sum(1 for s in steps if s.action_result and s.action_result.success)
        console.print(f"\n[bold]Summary:[/] {successful}/{len(steps)} steps successful")

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/]")
        agent.stop()


@app.command()
def ground(
    element: str = typer.Argument(..., help="Element description to find"),
    base_url: str = typer.Option(
        "http://localhost:23333/api/anthropic",
        "--base-url",
        help="VLM API base URL"
    ),
):
    """
    Find coordinates of a specific UI element.

    Examples:
        rpa-agent ground "Submit button"
        rpa-agent ground "Search text field"
    """
    console.print(f"[dim]Looking for: {element}[/]")

    config = AgentConfig(
        vlm_config=VLMConfig(base_url=base_url)
    )
    agent = GUIAgent(config=config, console=console)

    result = agent.ground_element(element)

    if result:
        console.print(f"[green]Found at coordinates: ({result[0]}, {result[1]})[/]")
    else:
        console.print("[red]Element not found[/]")


@app.command()
def screenshot(
    output: str = typer.Option("screenshot.png", "--output", "-o", help="Output file"),
    scale: float = typer.Option(1.0, "--scale", "-s", help="Scale factor"),
):
    """
    Capture a screenshot of the current screen.
    """
    from .core import ScreenCapture

    with ScreenCapture() as screen:
        path = screen.save_screenshot(Path(output), scale=scale)
        console.print(f"[green]Screenshot saved to: {path}[/]")


@app.command()
def windows():
    """
    List all visible windows.
    """
    from .core import WindowManager

    wm = WindowManager()
    windows = wm.get_all_windows(visible_only=True)

    console.print(f"\n[bold]Found {len(windows)} windows:[/]\n")

    for win in windows:
        if win.title:  # Only show windows with titles
            try:
                # Use repr for safe display of any characters
                title = win.title[:60]
                console.print(f"  {title}", style="cyan")
                console.print(f"    Position: ({win.rect[0]}, {win.rect[1]})")
                console.print(f"    Size: {win.width}x{win.height}")
                console.print()
            except Exception:
                # Skip windows with encoding issues
                pass


@app.command()
def interactive():
    """
    Start interactive mode for step-by-step control.
    """
    console.print(Panel.fit(
        "[bold blue]Interactive Mode[/]\nType tasks or commands",
        border_style="blue"
    ))

    config = AgentConfig(
        max_steps=1,  # One step at a time
        confirm_actions=True
    )
    agent = GUIAgent(config=config, console=console)

    console.print("\nCommands:")
    console.print("  [cyan]task <description>[/] - Execute a single-step task")
    console.print("  [cyan]ground <element>[/] - Find element coordinates")
    console.print("  [cyan]click <x> <y>[/] - Click at coordinates")
    console.print("  [cyan]type <text>[/] - Type text")
    console.print("  [cyan]screenshot[/] - Take a screenshot")
    console.print("  [cyan]quit[/] - Exit interactive mode")
    console.print()

    while True:
        try:
            cmd = Prompt.ask("[bold]>[/]")

            if not cmd.strip():
                continue

            parts = cmd.strip().split(maxsplit=1)
            command = parts[0].lower()

            if command == "quit" or command == "exit":
                break

            elif command == "task" and len(parts) > 1:
                agent.config.max_steps = 1
                agent.run(parts[1])

            elif command == "ground" and len(parts) > 1:
                result = agent.ground_element(parts[1])
                if result:
                    console.print(f"[green]Found at: ({result[0]}, {result[1]})[/]")
                else:
                    console.print("[red]Not found[/]")

            elif command == "click" and len(parts) > 1:
                coords = parts[1].split()
                if len(coords) >= 2:
                    x, y = int(coords[0]), int(coords[1])
                    agent.controller.click(x, y)
                    console.print(f"[green]Clicked at ({x}, {y})[/]")

            elif command == "type" and len(parts) > 1:
                agent.controller.write(parts[1])
                console.print(f"[green]Typed: {parts[1]}[/]")

            elif command == "screenshot":
                path = agent.screen.save_screenshot(Path("interactive_screenshot.png"))
                console.print(f"[green]Saved: {path}[/]")

            else:
                console.print("[yellow]Unknown command[/]")

        except KeyboardInterrupt:
            console.print("\n[yellow]Use 'quit' to exit[/]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/]")

    console.print("[dim]Goodbye![/]")


@app.command()
def test_vlm(
    base_url: str = typer.Option(
        "http://localhost:23333/api/anthropic",
        "--base-url",
        help="VLM API base URL"
    ),
):
    """
    Test connection to the VLM API.
    """
    from .vlm import VLMClient, VLMConfig

    console.print("[dim]Testing VLM connection...[/]")

    try:
        client = VLMClient(VLMConfig(base_url=base_url))
        response = client.chat(
            messages=[{"role": "user", "content": "Say 'Hello, I am working!' in exactly those words."}],
            system="You are a helpful assistant."
        )
        console.print(f"[green]Success![/] Response: {response.text}")
        console.print(f"[dim]Tokens used: {response.usage}[/]")
    except Exception as e:
        console.print(f"[red]Connection failed: {e}[/]")


if __name__ == "__main__":
    app()
