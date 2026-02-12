"""
Example usage of the RPA UI Agent.

This script demonstrates various capabilities of the agent.
"""

from pathlib import Path
from rpa_agent import GUIAgent, AgentConfig
from rpa_agent.vlm import VLMConfig


def basic_example():
    """Basic agent usage - run a simple task."""
    print("=" * 60)
    print("Basic Agent Example")
    print("=" * 60)

    # Create agent with default config
    agent = GUIAgent()

    # Run a simple task
    steps = agent.run("Take a screenshot and describe what you see")

    print(f"\nCompleted {len(steps)} steps")


def configured_example():
    """Agent with custom configuration."""
    print("=" * 60)
    print("Configured Agent Example")
    print("=" * 60)

    # Custom VLM config
    vlm_config = VLMConfig(
        base_url="http://localhost:23333/api/anthropic",
        model="claude-opus-4.6-1m",
        max_tokens=2048,
        temperature=0.0  # More deterministic
    )

    # Custom agent config
    config = AgentConfig(
        vlm_config=vlm_config,
        max_steps=10,
        step_delay=1.0,
        save_screenshots=True,
        screenshot_dir=Path("./example_screenshots"),
        dry_run=True  # Don't actually execute actions
    )

    agent = GUIAgent(config=config)
    steps = agent.run("Click on the Start menu")

    # Save history
    agent.save_history(Path("example_history.json"))


def grounding_example():
    """Element grounding example."""
    print("=" * 60)
    print("Element Grounding Example")
    print("=" * 60)

    agent = GUIAgent()

    # Find various elements
    elements_to_find = [
        "taskbar at bottom of screen",
        "close button (X) in any window",
        "search icon or search box"
    ]

    for element in elements_to_find:
        print(f"\nLooking for: {element}")
        coords = agent.ground_element(element)
        if coords:
            print(f"  Found at: ({coords[0]}, {coords[1]})")
        else:
            print("  Not found")


def planning_example():
    """Task planning example."""
    print("=" * 60)
    print("Task Planning Example")
    print("=" * 60)

    config = AgentConfig(
        max_steps=5,
        dry_run=True
    )

    agent = GUIAgent(config=config)

    # Run with planning phase
    steps = agent.run_with_plan("Open a text editor and write a short note")

    print(f"\nPlanned and executed {len(steps)} steps")


def callback_example():
    """Using callbacks for monitoring."""
    print("=" * 60)
    print("Callback Example")
    print("=" * 60)

    def on_action(action):
        """Called before each action - return False to skip."""
        print(f"[CALLBACK] About to execute: {action.action_type.value}")
        # Could implement custom logic here
        return True

    def on_step(step):
        """Called after each step."""
        status = "✓" if step.action_result and step.action_result.success else "✗"
        print(f"[CALLBACK] Step {step.step_number} {status}: {step.reasoning[:50]}...")

    config = AgentConfig(max_steps=3, dry_run=True)
    agent = GUIAgent(config=config)

    agent.run(
        "Click on a button",
        on_action=on_action,
        on_step=on_step
    )


def screen_capture_example():
    """Direct screen capture usage."""
    print("=" * 60)
    print("Screen Capture Example")
    print("=" * 60)

    from rpa_agent.core import ScreenCapture

    with ScreenCapture() as screen:
        # Get screen info
        print(f"Screen size: {screen.screen_size}")
        print(f"Available monitors: {len(screen.monitors)}")

        # Capture full screen
        img = screen.capture()
        print(f"Captured image size: {img.size}")

        # Save screenshot
        path = screen.save_screenshot(Path("./example_capture.png"))
        print(f"Saved to: {path}")


def window_management_example():
    """Window management example."""
    print("=" * 60)
    print("Window Management Example")
    print("=" * 60)

    from rpa_agent.core import WindowManager

    wm = WindowManager()

    # List all windows
    windows = wm.get_all_windows(visible_only=True)
    print(f"Found {len(windows)} visible windows\n")

    # Show first 5 with titles
    for win in windows[:5]:
        if win.title:
            print(f"  {win.title[:50]}")
            print(f"    Position: ({win.rect[0]}, {win.rect[1]})")
            print(f"    Size: {win.width}x{win.height}")

    # Get foreground window
    fg = wm.get_foreground_window()
    if fg:
        print(f"\nForeground window: {fg.title}")


if __name__ == "__main__":
    import sys

    examples = {
        "basic": basic_example,
        "config": configured_example,
        "grounding": grounding_example,
        "planning": planning_example,
        "callback": callback_example,
        "screen": screen_capture_example,
        "windows": window_management_example,
    }

    if len(sys.argv) > 1:
        example_name = sys.argv[1]
        if example_name in examples:
            examples[example_name]()
        else:
            print(f"Unknown example: {example_name}")
            print(f"Available: {', '.join(examples.keys())}")
    else:
        print("RPA UI Agent Examples")
        print("=" * 60)
        print("\nUsage: python examples.py <example_name>")
        print(f"\nAvailable examples: {', '.join(examples.keys())}")
        print("\nRunning 'screen' example as demo...")
        print()
        screen_capture_example()
