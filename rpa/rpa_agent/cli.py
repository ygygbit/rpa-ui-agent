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
from .vlm import VLMConfig, AVAILABLE_MODELS, DEFAULT_MODEL

app = typer.Typer(
    name="rpa-agent",
    help="Vision-Language Model based RPA UI Control Agent",
    add_completion=False
)
console = Console()


def model_callback(value: str) -> str:
    """Validate model selection."""
    if value not in AVAILABLE_MODELS:
        raise typer.BadParameter(
            f"Invalid model. Available: {', '.join(AVAILABLE_MODELS)}"
        )
    return value


@app.command()
def run(
    task: str = typer.Argument(..., help="Task to accomplish"),
    max_steps: int = typer.Option(50, "--max-steps", "-n", help="Maximum steps"),
    step_delay: float = typer.Option(0.5, "--delay", "-d", help="Delay between steps"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Don't execute actions"),
    confirm: bool = typer.Option(False, "--confirm", "-c", help="Confirm each action"),
    save_screenshots: bool = typer.Option(True, "--screenshots/--no-screenshots", help="Save screenshots"),
    screenshot_dir: str = typer.Option("./screenshots", "--screenshot-dir", help="Screenshot directory"),
    screenshot_quality: int = typer.Option(50, "--quality", "-q", help="Screenshot JPEG quality (1-100, lower=faster)"),
    screenshot_scale: float = typer.Option(1.0, "--scale", "-s", help="Screenshot scale (1.0 = original size for accurate coordinates)"),
    plan: bool = typer.Option(False, "--plan", "-p", help="Create plan before execution"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save history to JSON file"),
    no_overlay: bool = typer.Option(False, "--no-overlay", help="Disable cursor overlay"),
    base_url: str = typer.Option(
        "http://localhost:23333/api/anthropic",
        "--base-url",
        help="VLM API base URL"
    ),
    model: str = typer.Option(
        DEFAULT_MODEL,
        "--model",
        "-m",
        help=f"Model name. Available: {', '.join(AVAILABLE_MODELS)}",
        callback=model_callback
    ),
):
    """
    Run the GUI agent to accomplish a task.

    Examples:
        rpa-agent run "Open Chrome and go to google.com"
        rpa-agent run "Click the search button" --max-steps 10 --model claude-opus-4.6-fast
        rpa-agent run "Fill out the form" --plan --confirm
        rpa-agent run "Play video" -q 30 -s 0.5  # Fast mode with lower quality
    """
    console.print(Panel.fit(
        f"[bold blue]RPA UI Agent[/]\nVision-Language Model based GUI Automation\n[dim]Model: {model}[/]",
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
        screenshot_dir=Path(screenshot_dir),
        screenshot_scale=screenshot_scale,
        screenshot_quality=screenshot_quality,
        show_cursor_overlay=not no_overlay
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


@app.command()
def models():
    """
    List available models.
    """
    console.print("\n[bold]Available models:[/]\n")
    for model in AVAILABLE_MODELS:
        if model == DEFAULT_MODEL:
            console.print(f"  [green]{model}[/] [dim](default)[/]")
        else:
            console.print(f"  [cyan]{model}[/]")
    console.print("\n[dim]Use --model/-m to select a model[/]")
    console.print("[dim]Example: rpa-agent run \"task\" --model claude-opus-4.6[/]\n")


# ==================== Sandbox Commands ====================

sandbox_app = typer.Typer(
    name="sandbox",
    help="Run RPA agent in isolated Docker sandbox (1080p, Chrome pre-installed)"
)
app.add_typer(sandbox_app, name="sandbox")


@sandbox_app.command("up")
def sandbox_up(
    detach: bool = typer.Option(True, "--detach/--no-detach", "-d", help="Run in background"),
    build: bool = typer.Option(False, "--build", "-b", help="Rebuild container image"),
):
    """
    Start the sandbox environment.

    After starting, access:
    - Web preview: http://localhost:6080
    - VNC: localhost:5900
    - API: http://localhost:8000
    """
    import subprocess
    import os

    project_root = Path(__file__).parent.parent

    console.print(Panel.fit(
        "[bold blue]RPA Sandbox Environment[/]\n"
        "Starting Docker container with:\n"
        "• 1920x1080 virtual display\n"
        "• Chrome browser pre-installed\n"
        "• VNC/noVNC preview access",
        border_style="blue"
    ))

    cmd = ["docker", "compose", "up"]
    if detach:
        cmd.append("-d")
    if build:
        cmd.append("--build")
    cmd.append("rpa-sandbox")

    console.print(f"[dim]Running: {' '.join(cmd)}[/]")

    result = subprocess.run(cmd, cwd=project_root)

    if result.returncode == 0:
        console.print("\n[green]Sandbox started successfully![/]")
        console.print("\n[bold]Access points:[/]")
        console.print("  • [cyan]Web Preview:[/] http://localhost:6080")
        console.print("  • [cyan]VNC Client:[/] localhost:5900")
        console.print("  • [cyan]API Server:[/] http://localhost:8000")
        console.print("  • [cyan]Screenshot:[/] http://localhost:8000/screenshot")
        console.print("\n[dim]Stop with: rpa-agent sandbox down[/]")
    else:
        console.print("[red]Failed to start sandbox[/]")


@sandbox_app.command("down")
def sandbox_down(
    volumes: bool = typer.Option(False, "--volumes", "-v", help="Remove volumes too"),
):
    """
    Stop and remove the sandbox environment.
    """
    import subprocess

    project_root = Path(__file__).parent.parent

    cmd = ["docker", "compose", "down"]
    if volumes:
        cmd.append("-v")

    console.print("[dim]Stopping sandbox...[/]")
    result = subprocess.run(cmd, cwd=project_root)

    if result.returncode == 0:
        console.print("[green]Sandbox stopped and removed[/]")
    else:
        console.print("[red]Failed to stop sandbox[/]")


@sandbox_app.command("status")
def sandbox_status():
    """
    Show sandbox status.
    """
    import subprocess
    import httpx

    project_root = Path(__file__).parent.parent

    # Check Docker container status
    result = subprocess.run(
        ["docker", "compose", "ps", "--format", "json"],
        cwd=project_root,
        capture_output=True,
        text=True
    )

    console.print("\n[bold]Sandbox Status[/]\n")

    # Check if container is running
    container_running = False
    if result.returncode == 0 and result.stdout.strip():
        try:
            # Docker compose ps outputs one JSON object per line
            for line in result.stdout.strip().split('\n'):
                if line:
                    container_info = json.loads(line)
                    if 'rpa-sandbox' in container_info.get('Name', ''):
                        state = container_info.get('State', 'unknown')
                        console.print(f"[cyan]Container:[/] {state}")
                        container_running = state == 'running'
        except json.JSONDecodeError:
            console.print("[yellow]Could not parse container status[/]")
    else:
        console.print("[dim]Container not found[/]")

    # Check API server
    if container_running:
        try:
            response = httpx.get("http://localhost:8000/status", timeout=5)
            if response.status_code == 200:
                status = response.json()
                console.print(f"[cyan]API Server:[/] [green]running[/]")
                console.print(f"[cyan]Screen Size:[/] {status['screen_size']['width']}x{status['screen_size']['height']}")
                console.print(f"[cyan]Chrome:[/] {'running' if status['chrome_running'] else 'not running'}")
                console.print(f"[cyan]Task Running:[/] {status['task_running']}")
        except Exception:
            console.print("[cyan]API Server:[/] [yellow]not responding (may still be starting)[/]")

    console.print("\n[bold]Access Points:[/]")
    console.print("  • Web Preview: http://localhost:6080")
    console.print("  • API Server: http://localhost:8000")
    console.print("  • Screenshot: http://localhost:8000/screenshot")


@sandbox_app.command("screenshot")
def sandbox_screenshot(
    output: str = typer.Option("sandbox_screenshot.png", "--output", "-o", help="Output file"),
    open_browser: bool = typer.Option(False, "--open", help="Open in browser instead of saving"),
):
    """
    Capture screenshot from sandbox.
    """
    import httpx
    import webbrowser

    if open_browser:
        webbrowser.open("http://localhost:8000/screenshot")
        console.print("[green]Opened screenshot in browser[/]")
        return

    try:
        response = httpx.get("http://localhost:8000/screenshot", timeout=10)
        if response.status_code == 200:
            with open(output, "wb") as f:
                f.write(response.content)
            console.print(f"[green]Screenshot saved to: {output}[/]")
        else:
            console.print(f"[red]Failed to capture screenshot: {response.status_code}[/]")
    except httpx.ConnectError:
        console.print("[red]Cannot connect to sandbox. Is it running?[/]")
        console.print("[dim]Start with: rpa-agent sandbox up[/]")


@sandbox_app.command("chrome")
def sandbox_chrome(
    url: str = typer.Argument("https://www.google.com", help="URL to open"),
):
    """
    Open Chrome in sandbox with specified URL.
    """
    import httpx

    try:
        response = httpx.post(
            "http://localhost:8000/chrome/start",
            params={"url": url},
            timeout=10
        )
        if response.status_code == 200:
            result = response.json()
            console.print(f"[green]Chrome started: {url}[/]")
            console.print("[dim]View at: http://localhost:6080[/]")
        else:
            console.print(f"[red]Failed: {response.text}[/]")
    except httpx.ConnectError:
        console.print("[red]Cannot connect to sandbox. Is it running?[/]")


@sandbox_app.command("preview")
def sandbox_preview():
    """
    Open noVNC preview in browser.
    """
    import webbrowser
    webbrowser.open("http://localhost:6080/vnc.html?autoconnect=true")
    console.print("[green]Opened sandbox preview in browser[/]")


@sandbox_app.command("run")
def sandbox_run(
    task: str = typer.Argument(..., help="Task to accomplish"),
    max_steps: int = typer.Option(50, "--max-steps", "-n", help="Maximum steps"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Don't execute actions"),
    step_delay: float = typer.Option(0.5, "--delay", "-d", help="Delay between steps"),
    save_screenshots: bool = typer.Option(True, "--screenshots/--no-screenshots", help="Save screenshots"),
    screenshot_dir: str = typer.Option("./screenshots", "--screenshot-dir", help="Screenshot directory"),
    model: str = typer.Option(
        DEFAULT_MODEL,
        "--model",
        "-m",
        help=f"Model name. Available: {', '.join(AVAILABLE_MODELS)}",
        callback=model_callback
    ),
    base_url: str = typer.Option(
        "http://localhost:23333/api/anthropic",
        "--base-url",
        help="VLM API base URL"
    ),
    sandbox_url: str = typer.Option(
        "http://localhost:8000",
        "--sandbox-url",
        help="Sandbox API URL"
    ),
):
    """
    Run a task in the sandbox environment.

    The agent runs locally on Windows but captures screenshots and
    executes actions inside the Docker sandbox via HTTP API.
    """
    import httpx

    console.print(Panel.fit(
        f"[bold blue]RPA UI Agent - Sandbox Mode[/]\n"
        f"Task: {task}\n"
        f"[dim]Model: {model}[/]",
        border_style="blue"
    ))

    # Check sandbox is running
    try:
        response = httpx.get(f"{sandbox_url}/status", timeout=5)
        if response.status_code != 200:
            console.print("[red]Sandbox not responding properly[/]")
            return
        status = response.json()
        console.print(f"[green]Sandbox connected:[/] {status['screen_size']['width']}x{status['screen_size']['height']}")
    except httpx.ConnectError:
        console.print("[red]Cannot connect to sandbox. Is it running?[/]")
        console.print("[dim]Start with: rpa-agent sandbox up[/]")
        return

    # Create configuration with sandbox mode
    vlm_config = VLMConfig(
        base_url=base_url,
        model=model
    )

    config = AgentConfig(
        vlm_config=vlm_config,
        max_steps=max_steps,
        step_delay=step_delay,
        dry_run=dry_run,
        save_screenshots=save_screenshots,
        screenshot_dir=Path(screenshot_dir),
        sandbox_mode=True,
        sandbox_url=sandbox_url,
    )

    # Create and run agent
    agent = GUIAgent(config=config, console=console)

    try:
        steps = agent.run(task)

        # Summary
        successful = sum(1 for s in steps if s.action_result and s.action_result.success)
        console.print(f"\n[bold]Summary:[/] {successful}/{len(steps)} steps successful")

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/]")
        agent.stop()


@sandbox_app.command("logs")
def sandbox_logs(
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
):
    """
    View sandbox container logs.
    """
    import subprocess

    project_root = Path(__file__).parent.parent

    cmd = ["docker", "compose", "logs"]
    if follow:
        cmd.append("-f")
    cmd.append("rpa-sandbox")

    subprocess.run(cmd, cwd=project_root)


if __name__ == "__main__":
    app()
