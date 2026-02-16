"""
MiniWoB++ Benchmark Runner for RPA Agent

Runs the VLM-based RPA agent against MiniWoB++ benchmarks.
"""

import base64
import io
import json
import re
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime

import gymnasium
import miniwob
import numpy as np
from PIL import Image

# Import anthropic for VLM calls
import anthropic


@dataclass
class BenchmarkResult:
    """Result of a single benchmark run."""
    task_name: str
    success: bool
    reward: float
    steps: int
    time_taken: float
    utterance: str
    error: Optional[str] = None
    actions: List[str] = field(default_factory=list)


@dataclass
class BenchmarkSummary:
    """Summary of benchmark results."""
    total_tasks: int
    successful_tasks: int
    success_rate: float
    avg_reward: float
    avg_steps: float
    avg_time: float
    results: List[BenchmarkResult]


class MiniWoBBenchmarkRunner:
    """Runs MiniWoB++ benchmarks using VLM-based agent."""

    # Simple tasks good for initial testing
    EASY_TASKS = [
        "click-button-v1",
        "click-test-v1",
        "click-link-v1",
        "click-dialog-v1",
        "focus-text-v1",
        "enter-text-v1",
    ]

    # Medium difficulty tasks
    MEDIUM_TASKS = [
        "click-checkboxes-v1",
        "click-collapsible-v1",
        "click-option-v1",
        "click-tab-v1",
        "enter-password-v1",
        "login-user-v1",
    ]

    # All tasks for full benchmark
    ALL_TASKS = None  # Will be populated dynamically

    def __init__(
        self,
        model: str = "claude-opus-4-20250514",  # Best accuracy
        max_steps: int = 10,
        verbose: bool = True
    ):
        self.model = model
        self.max_steps = max_steps
        self.verbose = verbose
        self.client = anthropic.Anthropic()

        # Get all available tasks
        self.ALL_TASKS = [
            e.split("/")[1] for e in gymnasium.envs.registry.keys()
            if e.startswith("miniwob/")
        ]

    def _screenshot_to_base64(self, screenshot: np.ndarray, scale: int = 4) -> str:
        """Convert numpy screenshot to base64 PNG, optionally upscaled."""
        img = Image.fromarray(screenshot)

        if scale > 1:
            new_size = (img.width * scale, img.height * scale)
            img = img.resize(new_size, Image.Resampling.NEAREST)

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return base64.standard_b64encode(buffer.read()).decode("utf-8")

    def _get_vlm_action(
        self,
        screenshot: np.ndarray,
        utterance: str,
        screen_size: Tuple[int, int],
        previous_actions: List[str] = None,
        multi_action: bool = False
    ) -> Dict[str, Any]:
        """Get action from VLM based on screenshot and task description."""

        # We scale up the image for better visibility but coordinates are still in original space
        scale_factor = 4  # 4x provides good balance of visibility and coordinate accuracy
        screenshot_b64 = self._screenshot_to_base64(screenshot, scale=scale_factor)
        width, height = screen_size
        scaled_width, scaled_height = width * scale_factor, height * scale_factor

        # Build history context
        history_context = ""
        if previous_actions:
            # Check for stuck behavior (same action repeated) - trigger after just 2 identical actions
            last_actions = previous_actions[-2:] if len(previous_actions) >= 2 else previous_actions
            is_stuck = len(set(last_actions)) == 1 and len(last_actions) >= 2

            history_context = "\nPREVIOUS ACTIONS (already performed):\n"
            for i, act in enumerate(previous_actions[-3:], 1):  # Last 3 actions
                history_context += f"  {i}. {act}\n"

            if is_stuck:
                # Check if stuck on a text field click
                last_action = last_actions[0] if last_actions else ""
                is_clicking_field = "61, 78" in last_action or "61, 140" in last_action or "71, 88" in last_action
                is_clicking_checkbox = '"x": 15' in last_action or "'x': 15" in last_action
                is_clicking_collapsible_content = any(f'"y": {y}' in last_action for y in range(100, 170))

                if is_clicking_field:
                    history_context += """
WARNING: You clicked a TEXT FIELD but then clicked again instead of typing!
YOU MUST TYPE TEXT NOW. The field is ready - use: {"action": "type", "text": "<the password or text>"}
"""
                elif is_clicking_checkbox:
                    history_context += """
WARNING: You are STUCK clicking the SAME CHECKBOX repeatedly!
YOU ALREADY CLICKED THIS CHECKBOX - now do one of:
1. If there are MORE checkboxes to select (from the task), click the NEXT one (at a LOWER y position, e.g., y+20)
2. If ALL checkboxes are selected, click the SUBMIT button at (50, 147) or (80, 160)
DO NOT click the same checkbox again!
"""
                elif is_clicking_collapsible_content and "collapsible" in str(previous_actions).lower():
                    history_context += """
WARNING: You are clicking the SAME POSITION repeatedly in a collapsible task!
The section is ALREADY EXPANDED. You are clicking content, not the Submit button.
IMMEDIATELY click the SUBMIT BUTTON at:
- Try (80, 165) first
- Or try (50, 155)
Do NOT click any other position!
"""
                else:
                    history_context += """
WARNING: You are STUCK repeating the same action! This is NOT working.
YOU MUST TRY SOMETHING COMPLETELY DIFFERENT:
- If clicking failed, try a DIFFERENT y-coordinate (add or subtract 20-50 pixels)
- If the text field didn't respond, it might be at a different location
- Look at the screenshot carefully and find the ACTUAL element position
"""
            else:
                history_context += """
IMPORTANT: Based on the previous actions and current screenshot state:
- If you already clicked a text field, your NEXT action should be "type"
- If you already typed text, your NEXT action should be to click Submit or press Enter
- Do NOT repeat the same click action if you just did it
"""

        if multi_action:
            # Multi-action mode for complex tasks
            prompt = f"""You are a GUI automation agent. Plan ALL actions needed to complete this task.

TASK: {utterance}

COORDINATE SYSTEM:
- Image is {scaled_width}x{scaled_height} pixels (4x enlarged)
- Return coordinates in ORIGINAL {width}x{height} space (divide by 4)
- Screen is {width}x{height} pixels

LAYOUT FOR LOGIN/PASSWORD FORMS (exact DOM positions):
- Username input field: center at x=71, y=88
- Password input field: center at x=61, y=140
- Login button: x=45, y=166 (at very bottom!)

OUTPUT A JSON ARRAY of all actions needed:

[
  {{"action": "click", "x": <number>, "y": <number>}},
  {{"action": "type", "text": "..."}},
  ...
]

Example for login task with username "john" and password "secret":
[
  {{"action": "click", "x": 71, "y": 88}},
  {{"action": "type", "text": "john"}},
  {{"action": "click", "x": 61, "y": 140}},
  {{"action": "type", "text": "secret"}},
  {{"action": "click", "x": 45, "y": 166}}
]

Output JSON array only:"""
        else:
            prompt = f"""You are a GUI automation agent. Complete this task step by step.

TASK: {utterance}
{history_context}
COORDINATE SYSTEM:
- The image shown is {scaled_width}x{scaled_height} pixels (enlarged 4x for visibility)
- You must return coordinates in the ORIGINAL {width}x{height} pixel space
- To convert: divide any pixel position you see by 4
- Origin (0,0) is top-left corner

ELEMENT LOCATION TIPS:
- Buttons: rectangles with text labels
- Links: colored/underlined text within the content area
- Text fields: white input boxes with borders
- Close button (X): in the top-right corner OF THE DIALOG BOX itself
- For LOGIN/PASSWORD FORMS (exact DOM positions):
  - Username field center: x=71, y=88
  - Password field center: x=61, y=140
  - Login/Submit button: x=45, y=166 (at very bottom!)
- For COLLAPSIBLE SECTIONS (critical):
  - STEP 1: Click the blue section header bar (y~62) to expand it
  - STEP 2: After expansion, the Submit button appears BELOW the content
  - The Submit button is gray with "Submit" text, y position varies from 100-168
  - If you see a gray button with Submit text, click it immediately!
  - Fallback: if Submit button is not clearly visible, try clicking (80, 165) or (80, 140)
  - WARNING: Do NOT click the blue header bar (y~62) again - it will collapse back!
  - NEVER use scroll - it does not work! Only use click actions.
- For CHECKBOX tasks (CRITICAL - read carefully):
  - Checkboxes are small squares on the LEFT side (x~15)
  - Read the task carefully - it lists SPECIFIC checkbox labels to select
  - STEP 1: Find EACH label mentioned in the task and click its checkbox
  - STEP 2: After clicking ALL required checkboxes, click Submit button
  - If task says "Select nothing", just click Submit immediately without clicking any checkbox
  - Checkbox positions vary: first at y~52, each subsequent ~15-20 pixels lower
  - Submit button is at the BOTTOM - try (50, 147) or (80, 160)
  - DO NOT click same checkbox twice - move to the NEXT checkbox after each click!
- For RADIO/OPTION tasks:
  - Radio buttons have circular buttons on the LEFT side (x~15)
  - Click the radio button, not the text label
  - Submit button is typically below options - try (80, 140) or (50, 140)
- For ENTER PASSWORD tasks:
  - Password field 1: x=61, y=78
  - Password field 2 (confirm): x=61, y=140
  - Submit button: x=45, y=166
  - CRITICAL: After clicking a field, you MUST type text next! Don't click again!
- For FOCUS TEXT tasks:
  - Look for a WHITE rectangular input box with a border
  - The textbox can be ANYWHERE on screen - look carefully for the white rectangle
  - Click the CENTER of the white input box to focus it
- For TAB tasks:
  - Tab #1: click at (25, 62)
  - Tab #2: click at (72, 62)
  - Tab #3: click at (114, 62)
  - Tabs are at y=62, NOT y=57 or y=55
- For LINK clicking:
  - Links are blue/purple underlined text - click the CENTER of the link text
  - For SHORT links (2-3 characters like "in", "ut", "nec"): be VERY precise
  - Scan the ENTIRE visible area - links can be ANYWHERE
  - Make sure you're clicking the EXACT word mentioned, not a similar word

TASK WORKFLOW:
- For clicking tasks: find element, click its center
- For text entry tasks: FIRST click the text field, THEN type the text, THEN click Submit
- For password/login tasks with 2 fields: click field1, type, click field2, type, click Submit/Login button
- For collapsible tasks: click header to expand, then click Submit
- After all fields are filled, ALWAYS click the Submit/Login button (don't just press Enter)

CRITICAL: Output ONLY a valid JSON object. No explanations, no text before or after the JSON.

RESPOND WITH JSON (one action at a time):

For clicking: {{"action": "click", "x": <number 0-{width-1}>, "y": <number 0-{height-1}>}}
For typing text: {{"action": "type", "text": "<text>"}}
For Enter key: {{"action": "key", "key": "enter"}}

JSON only:"""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot_b64
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
        )

        # Parse the response
        response_text = response.content[0].text.strip()

        # Try to extract JSON from response
        try:
            # Handle code blocks
            if "```" in response_text:
                match = re.search(r"```(?:json)?\s*(.*?)\s*```", response_text, re.DOTALL)
                if match:
                    response_text = match.group(1)

            # Try to find JSON object or array in the response
            # First attempt: parse as-is
            try:
                action = json.loads(response_text)
                return action
            except json.JSONDecodeError:
                pass

            # Second attempt: find JSON object pattern {...}
            json_match = re.search(r'\{[^{}]*"action"[^{}]*\}', response_text)
            if json_match:
                action = json.loads(json_match.group(0))
                return action

            # Third attempt: find JSON array pattern [...]
            array_match = re.search(r'\[[\s\S]*\]', response_text)
            if array_match:
                action = json.loads(array_match.group(0))
                return action

            return {"action": "done", "error": f"Failed to parse: {response_text[:200]}"}
        except json.JSONDecodeError:
            return {"action": "done", "error": f"Failed to parse: {response_text[:200]}"}

    def _translate_action(
        self,
        vlm_action: Dict[str, Any],
        screen_size: Tuple[int, int]
    ) -> Dict[str, Any]:
        """Translate VLM action to MiniWoB++ action format."""

        width, height = screen_size

        if vlm_action.get("action") == "click":
            x = int(float(vlm_action.get("x", 0)))
            y = int(float(vlm_action.get("y", 0)))
            # Clamp to screen bounds (MiniWoB++ clickable area ends at y=168)
            x = max(0, min(x, width - 1))
            y = max(0, min(y, 168))  # Max y is 168 for MiniWoB++

            return {
                "action_type": 2,  # CLICK_COORDS
                "coords": np.array([x, y], dtype=np.float32),
                "field": 0,
                "key": 0,
                "ref": 0,
                "text": ""
            }

        elif vlm_action.get("action") == "type":
            text = vlm_action.get("text", "")
            return {
                "action_type": 10,  # TYPE_TEXT
                "coords": np.array([0, 0], dtype=np.float32),
                "field": 0,
                "key": 0,
                "ref": 0,
                "text": text
            }

        elif vlm_action.get("action") == "key":
            # Map key names to key indices
            key_name = vlm_action.get("key", "").lower()
            key_map = {
                "enter": 13,
                "tab": 9,
                "escape": 27,
                "backspace": 8,
                "space": 32,
            }
            key_idx = key_map.get(key_name, 0)

            return {
                "action_type": 9,  # PRESS_KEY
                "coords": np.array([0, 0], dtype=np.float32),
                "field": 0,
                "key": key_idx,
                "ref": 0,
                "text": ""
            }

        else:
            # Default: no action (done or error)
            return {
                "action_type": 0,  # NONE
                "coords": np.array([0, 0], dtype=np.float32),
                "field": 0,
                "key": 0,
                "ref": 0,
                "text": ""
            }

    def _extend_episode_time(self, env, timeout_ms: int = 60000) -> dict:
        """Extend the MiniWoB++ JavaScript episode timer and return fresh observation.

        The default MiniWoB++ timer is 10 seconds which is too short for
        VLM-based agents (each API call takes ~5s). This method sets the
        JavaScript timer to a longer value, restarts the episode, and returns
        a fresh observation.

        Returns:
            Fresh observation dict with utterance and screenshot.
        """
        instance = env.unwrapped.instance
        driver = instance.driver

        # Set the episode max time in JavaScript
        driver.execute_script(f'core.EPISODE_MAX_TIME = {timeout_ms};')

        # End current episode and restart with new timer
        driver.execute_script('return core.endEpisode(0);')
        driver.execute_script('core.startEpisodeReal();')

        # Brief wait for episode to start
        time.sleep(0.1)

        # Get fresh observation after restart
        obs, info = instance.get_observation()
        return obs

    def run_single_task(self, task_name: str) -> BenchmarkResult:
        """Run a single MiniWoB++ task."""

        start_time = time.time()
        actions_taken = []
        error = None

        try:
            # Create environment
            env = gymnasium.make(f"miniwob/{task_name}")
            obs, info = env.reset()

            # Extend episode timeout for VLM-based agents (default is 10s, we need 120s)
            # This restarts the episode with a new problem, so get fresh observation
            obs = self._extend_episode_time(env, timeout_ms=120000)

            utterance = obs["utterance"]
            screenshot = obs["screenshot"]
            screen_size = (screenshot.shape[1], screenshot.shape[0])  # (width, height)

            if self.verbose:
                print(f"\nTask: {task_name}")
                print(f"Utterance: {utterance}")
                print(f"Screen size: {screen_size}")

            total_reward = 0
            done = False
            step = 0

            while not done and step < self.max_steps:
                # Get action from VLM
                vlm_action = self._get_vlm_action(
                    screenshot, utterance, screen_size,
                    previous_actions=actions_taken if actions_taken else None
                )
                action_str = json.dumps(vlm_action)
                actions_taken.append(action_str)

                if self.verbose:
                    print(f"  Step {step + 1}: {action_str}")

                # Check if VLM thinks task is done
                if vlm_action.get("action") == "done":
                    if self.verbose:
                        print("  VLM reports task complete")
                    break

                # Translate to MiniWoB++ action
                miniwob_action = self._translate_action(vlm_action, screen_size)

                # Execute action
                obs, reward, terminated, truncated, info = env.step(miniwob_action)
                total_reward += reward
                done = terminated or truncated

                screenshot = obs["screenshot"]
                step += 1

                if done and self.verbose:
                    print(f"  Environment reports done. Reward: {total_reward}")

            env.close()

            time_taken = time.time() - start_time
            success = total_reward > 0

            return BenchmarkResult(
                task_name=task_name,
                success=success,
                reward=total_reward,
                steps=step,
                time_taken=time_taken,
                utterance=utterance,
                actions=actions_taken
            )

        except Exception as e:
            time_taken = time.time() - start_time
            error = str(e)
            if self.verbose:
                print(f"  Error: {error}")

            return BenchmarkResult(
                task_name=task_name,
                success=False,
                reward=0,
                steps=0,
                time_taken=time_taken,
                utterance="",
                error=error,
                actions=actions_taken
            )

    def run_single_task_multiaction(self, task_name: str) -> BenchmarkResult:
        """Run a single MiniWoB++ task using multi-action planning (one API call)."""

        start_time = time.time()
        actions_taken = []
        error = None

        try:
            # Create environment
            env = gymnasium.make(f"miniwob/{task_name}")
            obs, info = env.reset()

            # Extend episode timeout for VLM-based agents (default is 10s, we need 120s)
            obs = self._extend_episode_time(env, timeout_ms=120000)

            utterance = obs["utterance"]
            screenshot = obs["screenshot"]
            screen_size = (screenshot.shape[1], screenshot.shape[0])  # (width, height)

            if self.verbose:
                print(f"\nTask: {task_name} (multi-action mode)")
                print(f"Utterance: {utterance}")
                print(f"Screen size: {screen_size}")

            # Get ALL actions in one API call
            vlm_response = self._get_vlm_action(
                screenshot, utterance, screen_size,
                multi_action=True
            )

            # Parse as list of actions
            if isinstance(vlm_response, list):
                action_plan = vlm_response
            else:
                # Single action returned, wrap in list
                action_plan = [vlm_response]

            if self.verbose:
                print(f"  Planned {len(action_plan)} actions")

            total_reward = 0
            done = False
            step = 0

            # Execute all planned actions
            for vlm_action in action_plan:
                if done:
                    break

                action_str = json.dumps(vlm_action)
                actions_taken.append(action_str)

                if self.verbose:
                    print(f"  Step {step + 1}: {action_str}")

                if vlm_action.get("action") == "done":
                    break

                # Translate to MiniWoB++ action
                miniwob_action = self._translate_action(vlm_action, screen_size)

                # Execute action
                obs, reward, terminated, truncated, info = env.step(miniwob_action)
                total_reward += reward
                done = terminated or truncated

                screenshot = obs["screenshot"]
                step += 1

                if done and self.verbose:
                    print(f"  Environment reports done. Reward: {total_reward}")

            env.close()

            time_taken = time.time() - start_time
            success = total_reward > 0

            return BenchmarkResult(
                task_name=task_name,
                success=success,
                reward=total_reward,
                steps=step,
                time_taken=time_taken,
                utterance=utterance,
                actions=actions_taken
            )

        except Exception as e:
            time_taken = time.time() - start_time
            error = str(e)
            if self.verbose:
                print(f"  Error: {error}")

            return BenchmarkResult(
                task_name=task_name,
                success=False,
                reward=0,
                steps=0,
                time_taken=time_taken,
                utterance="",
                error=error,
                actions=actions_taken
            )

    def run_benchmark(
        self,
        task_list: Optional[List[str]] = None,
        num_episodes: int = 1
    ) -> BenchmarkSummary:
        """Run benchmark on a list of tasks."""

        if task_list is None:
            task_list = self.EASY_TASKS

        results = []

        for task_name in task_list:
            for episode in range(num_episodes):
                if self.verbose and num_episodes > 1:
                    print(f"\n--- Episode {episode + 1}/{num_episodes} ---")

                result = self.run_single_task(task_name)
                results.append(result)

        # Calculate summary statistics
        total = len(results)
        successful = sum(1 for r in results if r.success)

        summary = BenchmarkSummary(
            total_tasks=total,
            successful_tasks=successful,
            success_rate=successful / total if total > 0 else 0,
            avg_reward=sum(r.reward for r in results) / total if total > 0 else 0,
            avg_steps=sum(r.steps for r in results) / total if total > 0 else 0,
            avg_time=sum(r.time_taken for r in results) / total if total > 0 else 0,
            results=results
        )

        return summary

    def print_summary(self, summary: BenchmarkSummary):
        """Print a formatted summary of benchmark results."""

        print("\n" + "=" * 60)
        print("BENCHMARK SUMMARY")
        print("=" * 60)
        print(f"Total tasks:      {summary.total_tasks}")
        print(f"Successful:       {summary.successful_tasks}")
        print(f"Success rate:     {summary.success_rate * 100:.1f}%")
        print(f"Average reward:   {summary.avg_reward:.3f}")
        print(f"Average steps:    {summary.avg_steps:.1f}")
        print(f"Average time:     {summary.avg_time:.2f}s")
        print("-" * 60)
        print("\nPer-task results:")

        for result in summary.results:
            status = "PASS" if result.success else "FAIL"
            print(f"  {status} {result.task_name}: reward={result.reward:.2f}, "
                  f"steps={result.steps}, time={result.time_taken:.2f}s")
            if result.error:
                print(f"      Error: {result.error[:50]}...")

        print("=" * 60)


def main():
    """Run benchmark from command line."""
    import argparse

    parser = argparse.ArgumentParser(description="Run MiniWoB++ benchmark")
    parser.add_argument("--tasks", nargs="+", help="Specific tasks to run")
    parser.add_argument("--preset", choices=["easy", "medium", "all"],
                        default="easy", help="Task preset")
    parser.add_argument("--episodes", type=int, default=1,
                        help="Episodes per task")
    parser.add_argument("--max-steps", type=int, default=10,
                        help="Max steps per episode")
    parser.add_argument("--model", default="claude-opus-4-20250514",
                        help="Model to use")
    parser.add_argument("--quiet", action="store_true",
                        help="Reduce output")

    args = parser.parse_args()

    runner = MiniWoBBenchmarkRunner(
        model=args.model,
        max_steps=args.max_steps,
        verbose=not args.quiet
    )

    if args.tasks:
        task_list = args.tasks
    elif args.preset == "easy":
        task_list = runner.EASY_TASKS
    elif args.preset == "medium":
        task_list = runner.MEDIUM_TASKS
    else:
        task_list = runner.ALL_TASKS

    summary = runner.run_benchmark(task_list, num_episodes=args.episodes)
    runner.print_summary(summary)

    # Save results to JSON
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = f"benchmark_results_{timestamp}.json"

    with open(results_file, "w") as f:
        json.dump({
            "timestamp": timestamp,
            "model": args.model,
            "success_rate": summary.success_rate,
            "results": [
                {
                    "task": r.task_name,
                    "success": r.success,
                    "reward": r.reward,
                    "steps": r.steps,
                    "time": r.time_taken,
                    "utterance": r.utterance,
                    "error": r.error,
                    "actions": r.actions
                }
                for r in summary.results
            ]
        }, f, indent=2)

    print(f"\nResults saved to {results_file}")


if __name__ == "__main__":
    main()
