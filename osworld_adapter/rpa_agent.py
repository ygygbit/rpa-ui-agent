"""
RPA Agent adapter for OSWorld benchmark.

Wraps our VLM (Anthropic API at custom endpoint) to implement
OSWorld's agent interface: predict(instruction, obs) -> (response, [actions])

Actions are pyautogui code strings that OSWorld's DesktopEnv.step() executes.
"""

import base64
import io
import json
import logging
import math
import re
import time
from typing import Dict, List, Optional, Tuple

from PIL import Image

logger = logging.getLogger("desktopenv.rpa_agent")


class RPAAgent:
    """
    Adapter wrapping our VLM endpoint for OSWorld's agent interface.

    Calls the Anthropic-compatible API at a custom endpoint,
    sends screenshot + instruction, parses JSON action response,
    and translates to pyautogui code strings.
    """

    def __init__(
        self,
        vlm_base_url: str = "http://localhost:23333/api/anthropic",
        vlm_api_key: str = "custom",
        vlm_model: str = "claude-opus-4.6-1m",
        max_tokens: int = 4096,
        temperature: float = 0.1,
        max_trajectory_length: int = 10,
        vlm_max_edge: int = 1344,
        vlm_image_quality: int = 50,
        platform: str = "ubuntu",
        action_space: str = "pyautogui",
        observation_type: str = "screenshot",
        client_password: str = "password",
        enable_taxonomy: bool = False,
        taxonomy_domain: Optional[str] = None,
    ):
        import anthropic

        self.vlm_base_url = vlm_base_url
        self.vlm_model = vlm_model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_trajectory_length = max_trajectory_length
        self.vlm_max_edge = vlm_max_edge
        self.vlm_image_quality = vlm_image_quality
        self.platform = platform
        self.action_space = action_space
        self.observation_type = observation_type
        self.client_password = client_password
        self.enable_taxonomy = enable_taxonomy
        self.taxonomy_domain = taxonomy_domain

        # Anthropic client pointing at custom endpoint
        self.client = anthropic.Anthropic(
            api_key=vlm_api_key,
            base_url=vlm_base_url,
        )

        # Conversation history for multi-turn
        self._history: List[Dict] = []
        self._step_count = 0
        self._scale_factor = 1.0
        self._last_action = {}
        self._repeat_count = 0
        self._action_history = []  # Track recent actions for stuck detection

        # UI Taxonomy pipeline
        self._taxonomy_pipeline = None
        if enable_taxonomy:
            from .ui_taxonomy.integration import UITaxonomyPipeline
            self._taxonomy_pipeline = UITaxonomyPipeline(
                vlm_client=self.client,
                vlm_model=self.vlm_model,
                domain=taxonomy_domain,
                enable_annotation=True,
                max_elements=20,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            logger.info(f"UI Taxonomy enabled (domain={taxonomy_domain})")

        # System prompt adapted for OSWorld Ubuntu environment
        self.system_prompt = self._build_system_prompt()

    def _stream_create(self, **kwargs) -> str:
        """Call the VLM using streaming to work around proxy response-size bug.

        Accepts the same kwargs as client.messages.create() and returns
        the concatenated text content of the response.
        """
        collected_text = []
        try:
            with self.client.messages.stream(**kwargs) as stream:
                for text in stream.text_stream:
                    collected_text.append(text)
        except Exception as e:
            # If we already collected some text, use it (proxy "Response too long" error)
            if collected_text:
                logger.warning(f"Stream ended with error ({e}) but collected {len(collected_text)} chunks, using partial response")
                return "".join(collected_text)
            # Otherwise fall back to non-streaming
            logger.warning(f"Streaming failed ({e}), falling back to non-streaming")
            response = self.client.messages.create(**kwargs)
            return response.content[0].text
        return "".join(collected_text)

    def _build_system_prompt(self) -> str:
        prompt = (
            "You are a GUI automation agent controlling an Ubuntu desktop via screenshots. "
            "Execute one action per response as JSON.\n\n"
            "## Coordinates\n"
            "- (0,0) = top-left of the screenshot image, X increases right, Y increases down.\n"
            "- Give coordinates based on the screenshot image dimensions you see.\n"
            "- Be precise: click the CENTER of buttons/icons, not edges.\n\n"
            "## Response Format\n"
            "Respond with ONLY a JSON block, no other text:\n"
            '```json\n{"reasoning": "Brief analysis", "action": "click", "x": 500, "y": 300}\n```\n\n'
            "## Actions\n"
            '- **click**: `{"action":"click","x":500,"y":300}` - left click\n'
            '- **double_click**: `{"action":"double_click","x":500,"y":300}`\n'
            '- **right_click**: `{"action":"right_click","x":500,"y":300}`\n'
            '- **type**: `{"action":"type","text":"Hello","press_enter":false}` - type into ALREADY focused field\n'
            '- **click_and_type**: `{"action":"click_and_type","x":500,"y":300,"text":"Hello","press_enter":true}` - click a field then type text\n'
            '- **press_key**: `{"action":"press_key","key":"enter"}`\n'
            '- **hotkey**: `{"action":"hotkey","keys":["ctrl","a"]}`\n'
            '- **scroll**: `{"action":"scroll","direction":"down","amount":3,"x":960,"y":540}`\n'
            '- **triple_click**: `{"action":"triple_click","x":500,"y":300}` - select entire line/paragraph\n'
            '- **drag**: `{"action":"drag","start_x":100,"start_y":200,"end_x":300,"end_y":400}`\n'
            '- **wait**: `{"action":"wait","seconds":2}`\n'
            '- **done**: `{"action":"done","summary":"Task completed"}`\n'
            '- **fail**: `{"action":"fail","error":"Cannot complete"}`\n\n'
            "## Ubuntu Desktop Tips\n"
            f"- Password for sudo: '{self.client_password}'\n"
            "- PREFERRED: Use Ctrl+L hotkey to focus address bar, then type URL on next step\n"
            "- OR use click_and_type to click address bar and type URL in one step\n"
            "- Chrome three-dot menu is at top-right corner (~x=1900, y=80)\n"
            "- Keyboard shortcuts: Ctrl+S save, Ctrl+Z undo, Ctrl+Alt+T terminal\n"
            "- File manager: Nautilus, double-click to open files/folders\n"
            "- For LibreOffice: use menu bar at top, Format > Cells for formatting\n"
            "- For GIMP: use tool options, Filters menu for effects\n"
            "- For VS Code: use Ctrl+Shift+P for command palette\n"
            "- To open terminal: Ctrl+Alt+T or click Activities top-left, search 'Terminal'\n"
            "- Chrome settings: navigate directly via chrome://settings, chrome://settings/searchEngines, etc.\n\n"
            "## Strategy Tips\n"
            "- USE KEYBOARD NAVIGATION: Tab to move between elements, Enter to activate, Space to toggle.\n"
            "- If clicking a small icon (three-dot menu, checkbox, etc.) fails, try:\n"
            "  1. Right-click on the element instead to get a context menu\n"
            "  2. Use Tab/Shift+Tab to navigate to it, then press Enter\n"
            "  3. Look for alternative paths (menu bar, keyboard shortcuts, settings URLs)\n"
            "- For Chrome settings: prefer navigating directly to chrome:// URLs over clicking through menus\n"
            "- For file operations: use terminal commands (Ctrl+Alt+T to open terminal)\n"
            "- For text editing: use Ctrl+H for find/replace, Ctrl+G for go-to-line\n"
            "- For selecting text in a field: use triple_click to select all text in that line, or Ctrl+A to select all\n"
            "- For LibreOffice: use menu bar navigation (File, Edit, Format, etc.), not toolbar icons\n"
            "  - To rename a sheet tab: double-click the tab, or right-click > Rename Sheet\n"
            "  - To change font: click the cell first, then use Format > Cells or the font dropdown in toolbar\n"
            "  - To select objects (shapes, images): click directly on them, use Tab to cycle through objects\n"
            "- For GIMP: use menu bar (Filters, Colors, Image, etc.) rather than small toolbar icons\n"
            "  - Prefer Filters > [category] > [filter] path for applying effects\n"
            "  - Use Image > Canvas Size, Image > Scale Image for dimension changes\n"
            "- For VS Code: use Ctrl+Shift+P command palette for settings and commands\n"
            "- For Thunderbird: use right-click context menus on folders/messages for actions\n"
            "- IMPORTANT: If you see no change after your action, your click probably missed. Try a different approach.\n\n"
        )

        # Add taxonomy-specific instructions if enabled
        if self.enable_taxonomy:
            prompt += (
                "## UI Element Detection\n"
                "The screenshot may have numbered bounding boxes [1], [2], etc. marking detected UI elements.\n"
                "A list of detected elements with their types, labels, coordinates, and hierarchy is provided.\n"
                "USE THIS INFORMATION to:\n"
                "- Verify your click target matches the correct element ID\n"
                "- Use the element center coordinates for precise clicking\n"
                "- Understand the UI hierarchy (which elements contain which)\n"
                "- Avoid clicking adjacent elements by checking bounding boxes\n\n"
            )

        prompt += (
            "## Rules\n"
            "1. ONE action per response as JSON block\n"
            "2. Use click_and_type when you need to click a field then type text\n"
            "3. NEVER repeat the exact same action - if something didn't work, try a DIFFERENT approach\n"
            "4. Report done ONLY when the objective is fully achieved\n"
            "5. Be efficient - use keyboard shortcuts and direct URLs when possible\n"
            "6. If an action seems to have no effect, try a completely different strategy\n"
            "7. Prefer keyboard shortcuts over clicking small buttons"
        )

        return prompt

    def reset(self, *args, **kwargs):
        """Reset agent state between tasks."""
        self._history = []
        self._step_count = 0
        self._scale_factor = 1.0
        self._last_action = {}
        self._repeat_count = 0
        self._action_history = []
        if self._taxonomy_pipeline:
            self._taxonomy_pipeline.reset()
        logger.info("RPAAgent reset")

    def _prepare_screenshot(self, obs: Dict) -> Tuple[str, str]:
        """
        Process screenshot from OSWorld observation.

        Resizes to vlm_max_edge (default 1344px) and sends as PNG.
        Coordinates from VLM will need to be scaled back to screen space.
        """
        screenshot_bytes = obs.get("screenshot")
        if screenshot_bytes is None:
            raise ValueError("No screenshot in observation")

        img = Image.open(io.BytesIO(screenshot_bytes))
        if img.mode == "RGBA":
            img = img.convert("RGB")

        orig_w, orig_h = img.size

        # Resize if larger than vlm_max_edge
        max_edge = self.vlm_max_edge
        if max(orig_w, orig_h) > max_edge:
            ratio = max_edge / max(orig_w, orig_h)
            new_w = int(orig_w * ratio)
            new_h = int(orig_h * ratio)
            img = img.resize((new_w, new_h), Image.LANCZOS)
            self._scale_factor = orig_w / new_w  # e.g. 1920/1344 = 1.4286
        else:
            self._scale_factor = 1.0
            new_w, new_h = orig_w, orig_h

        # Re-encode as PNG
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        b64 = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")
        media_type = "image/png"
        size_kb = len(buffer.getvalue()) // 1024

        logger.info(
            f"Screenshot: {orig_w}x{orig_h} -> {new_w}x{new_h}, "
            f"scale={self._scale_factor:.3f}, {media_type}, {size_kb}KB"
        )

        return b64, media_type

    def _parse_vlm_response(self, text: str) -> Optional[Dict]:
        """Parse JSON action from VLM response text."""
        # Try to find JSON in code block
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find bare JSON object
        json_match = re.search(r'(\{\s*"(?:reasoning|action)".*?\})', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try parsing the whole text as JSON
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        return None

    def _is_same_action(self, a: Dict, b: Dict, coord_tolerance: int = 10) -> bool:
        """Check if two actions are effectively the same (with coordinate tolerance)."""
        if not a or not b:
            return False
        if a.get("action") != b.get("action"):
            return False
        # Compare all fields, treating coordinates within tolerance as equal
        coord_keys = {"x", "y", "start_x", "start_y", "end_x", "end_y"}
        for key in set(list(a.keys()) + list(b.keys())):
            if key in coord_keys:
                va = a.get(key)
                vb = b.get(key)
                if va is not None and vb is not None:
                    if abs(int(va) - int(vb)) > coord_tolerance:
                        return False
            elif key == "action":
                continue
            else:
                if a.get(key) != b.get(key):
                    return False
        return True

    def _get_stuck_severity(self) -> int:
        """
        Determine how stuck the agent is based on action history.

        Returns:
            0 = not stuck
            1 = moderately stuck (warn the VLM)
            2 = hopelessly stuck (force break)
        """
        # Check consecutive repeats
        if self._repeat_count >= 4:
            return 2
        if self._repeat_count >= 2:
            return 1

        # Check broader history: if 4+ of last 8 actions target same click area
        # (catches click/escape oscillation patterns)
        if len(self._action_history) >= 8:
            recent = self._action_history[-8:]
            click_actions = [
                a for a in recent
                if a.get("action") in ("click", "double_click", "right_click", "click_and_type")
                and "x" in a and "y" in a
            ]
            if len(click_actions) >= 4:
                # Check if most target the same area (within 30px)
                ref = click_actions[0]
                similar = sum(
                    1 for a in click_actions
                    if abs(int(a.get("x", 0)) - int(ref.get("x", 0))) <= 30
                    and abs(int(a.get("y", 0)) - int(ref.get("y", 0))) <= 30
                )
                if similar >= 4:
                    return 2  # Stuck clicking same area with interleaved other actions

        # Check shorter history: if 3+ of last 5 actions target same area
        if len(self._action_history) >= 5:
            recent = self._action_history[-5:]
            click_actions = [
                a for a in recent
                if a.get("action") in ("click", "double_click", "right_click", "click_and_type")
                and "x" in a and "y" in a
            ]
            if len(click_actions) >= 3:
                ref = click_actions[0]
                similar = sum(
                    1 for a in click_actions
                    if abs(int(a.get("x", 0)) - int(ref.get("x", 0))) <= 30
                    and abs(int(a.get("y", 0)) - int(ref.get("y", 0))) <= 30
                )
                if similar >= 3:
                    return 1  # Getting stuck, warn the VLM

        return 0

    def _action_to_pyautogui(self, action_dict: Dict) -> str:
        """
        Convert our JSON action format to pyautogui code string.

        Scales coordinates from VLM image space to screen space.
        """
        action_type = action_dict.get("action", "").lower()
        sf = self._scale_factor  # VLM space -> screen space

        if action_type == "click":
            x = int(int(action_dict.get("x", 0)) * sf)
            y = int(int(action_dict.get("y", 0)) * sf)
            return f"pyautogui.click({x}, {y})"

        elif action_type == "double_click":
            x = int(int(action_dict.get("x", 0)) * sf)
            y = int(int(action_dict.get("y", 0)) * sf)
            return f"pyautogui.doubleClick({x}, {y})"

        elif action_type == "triple_click":
            x = int(int(action_dict.get("x", 0)) * sf)
            y = int(int(action_dict.get("y", 0)) * sf)
            return f"pyautogui.click({x}, {y}, clicks=3)"

        elif action_type == "right_click":
            x = int(int(action_dict.get("x", 0)) * sf)
            y = int(int(action_dict.get("y", 0)) * sf)
            return f"pyautogui.rightClick({x}, {y})"

        elif action_type == "type":
            text = action_dict.get("text", "")
            press_enter = action_dict.get("press_enter", False)
            # Use repr() for safe string escaping in generated code
            code = f"pyautogui.write({repr(text)}, interval=0.05)"
            if press_enter:
                code += "\ntime.sleep(0.3)\npyautogui.press('enter')"
            return code

        elif action_type == "click_and_type":
            x = int(int(action_dict.get("x", 0)) * sf)
            y = int(int(action_dict.get("y", 0)) * sf)
            text = action_dict.get("text", "")
            press_enter = action_dict.get("press_enter", False)
            # Click, brief pause, select all existing text, then type new text
            code = (
                f"pyautogui.click({x}, {y})\n"
                f"time.sleep(0.5)\n"
                f"pyautogui.hotkey('ctrl', 'a')\n"
                f"time.sleep(0.2)\n"
                f"pyautogui.write({repr(text)}, interval=0.05)"
            )
            if press_enter:
                code += "\ntime.sleep(0.3)\npyautogui.press('enter')"
            return code

        elif action_type == "press_key":
            key = action_dict.get("key", "enter").lower()
            return f"pyautogui.press('{key}')"

        elif action_type == "hotkey":
            keys = action_dict.get("keys", [])
            keys_str = ", ".join(f"'{k}'" for k in keys)
            return f"pyautogui.hotkey({keys_str})"

        elif action_type == "scroll":
            direction = action_dict.get("direction", "down").lower()
            amount = action_dict.get("amount", 3)
            clicks = amount if direction == "up" else -amount
            x = action_dict.get("x")
            y = action_dict.get("y")
            if x is not None and y is not None:
                x = int(int(x) * sf)
                y = int(int(y) * sf)
                return f"pyautogui.scroll({clicks}, x={x}, y={y})"
            return f"pyautogui.scroll({clicks})"

        elif action_type == "drag":
            sx = int(int(action_dict.get("start_x", 0)) * sf)
            sy = int(int(action_dict.get("start_y", 0)) * sf)
            ex = int(int(action_dict.get("end_x", 0)) * sf)
            ey = int(int(action_dict.get("end_y", 0)) * sf)
            return (
                f"pyautogui.moveTo({sx}, {sy})\n"
                f"time.sleep(0.3)\n"
                f"pyautogui.drag({ex-sx}, {ey-sy}, duration=0.5)"
            )

        elif action_type == "wait":
            secs = action_dict.get("seconds", 2)
            return f"time.sleep({secs})"

        elif action_type == "done":
            return "DONE"

        elif action_type == "fail":
            return "FAIL"

        else:
            logger.warning(f"Unknown action type: {action_type}")
            return "WAIT"

    def predict(self, instruction: str, obs: Dict) -> Tuple[str, List[str]]:
        """
        Predict next action given instruction and observation.

        Args:
            instruction: Task instruction text
            obs: OSWorld observation dict with 'screenshot' key (raw bytes)

        Returns:
            (response_text, [pyautogui_code_string])
        """
        self._step_count += 1

        try:
            # Prepare screenshot
            b64_img, media_type = self._prepare_screenshot(obs)

            # === UI Taxonomy: Element Detection (Pass 1) ===
            taxonomy_context = ""
            if self._taxonomy_pipeline:
                try:
                    taxonomy_result = self._taxonomy_pipeline.process_screenshot(
                        b64_img, media_type, self._step_count
                    )
                    if taxonomy_result.annotated_image:
                        b64_img = taxonomy_result.annotated_image
                        media_type = "image/png"  # Annotator outputs PNG
                    taxonomy_context = taxonomy_result.context_string
                    logger.info(
                        f"Taxonomy: {len(taxonomy_result.elements)} elements, "
                        f"context={len(taxonomy_context)} chars"
                    )
                except Exception as e:
                    logger.warning(f"Taxonomy pipeline error (continuing without): {e}")

            # Build user message
            user_text = f"Task: {instruction}"
            user_text += f"\n\n[Step {self._step_count}]"

            # Include accessibility tree if available (truncated)
            a11y_tree = obs.get("accessibility_tree")
            if a11y_tree and isinstance(a11y_tree, str) and len(a11y_tree) > 10:
                # Truncate to ~3000 chars to not bloat the prompt too much
                truncated = a11y_tree[:3000]
                if len(a11y_tree) > 3000:
                    truncated += "\n... (truncated)"
                user_text += f"\n\n## Accessibility Tree (UI elements on screen):\n{truncated}"

            # Inject taxonomy context
            if taxonomy_context:
                user_text += f"\n\n{taxonomy_context}"

            # Add stuck-loop warning if repeating
            # Check both consecutive repeats AND broader history pattern
            stuck_severity = self._get_stuck_severity()
            if stuck_severity >= 2:
                # Force break: hopelessly stuck
                logger.warning(
                    f"Force-breaking stuck loop: severity={stuck_severity}, "
                    f"repeat_count={self._repeat_count}"
                )
                self._history.append({"role": "user", "content": user_text})
                self._history.append({
                    "role": "assistant",
                    "content": '{"action":"fail","error":"Stuck in loop"}'
                })
                return '{"action":"fail","error":"Stuck in loop"}', ["FAIL"]
            elif stuck_severity == 1:
                user_text += (
                    "\n\nCRITICAL: You keep repeating similar actions that are NOT working! "
                    "The screen has NOT changed. You MUST use a COMPLETELY DIFFERENT approach:\n"
                    "- Use keyboard shortcuts (Tab, Enter, Ctrl+L, etc.)\n"
                    "- Navigate via URL bar or terminal command\n"
                    "- Try right-click for context menu\n"
                    "- Use a different path to achieve the same goal\n"
                    "DO NOT click the same area again."
                )

            user_text += "\nAnalyze the screenshot and determine the next action."

            # Build messages with history (sliding window)
            messages = []
            if self._history and self.max_trajectory_length > 0:
                history_window = self._history[-self.max_trajectory_length * 2:]
                messages.extend(history_window)

            # Add current observation
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64_img,
                        }
                    },
                    {
                        "type": "text",
                        "text": user_text,
                    }
                ]
            })

            # === VLM Call: Action Decision (Pass 2) ===
            response_text = self._stream_create(
                model=self.vlm_model,
                max_tokens=self.max_tokens,
                system=self.system_prompt,
                messages=messages,
                temperature=self.temperature,
            )

            logger.info(f"VLM response: {response_text[:200]}")

            # Parse action from response
            action_dict = self._parse_vlm_response(response_text)

            if action_dict is None:
                logger.warning(f"Could not parse action from VLM response: {response_text[:200]}")
                self._history.append({"role": "user", "content": user_text})
                self._history.append({"role": "assistant", "content": response_text})
                return response_text, ["WAIT"]

            # === UI Taxonomy: Snap click to element center (Pass 3) ===
            if self._taxonomy_pipeline and action_dict.get("action") in (
                "click", "double_click", "triple_click", "right_click", "click_and_type"
            ):
                self._snap_to_element(action_dict)

            # Convert to pyautogui code
            pyautogui_code = self._action_to_pyautogui(action_dict)

            # Track repeated actions for stuck-loop detection (with coordinate tolerance)
            action_comparable = {k: v for k, v in action_dict.items() if k != "reasoning"}
            if self._is_same_action(action_comparable, self._last_action):
                self._repeat_count += 1
            else:
                self._repeat_count = 0
            self._last_action = action_comparable

            # Track action history for broader stuck detection
            self._action_history.append(action_comparable)
            if len(self._action_history) > 10:
                self._action_history = self._action_history[-10:]

            # Update conversation history (text only, no images to save memory)
            self._history.append({"role": "user", "content": user_text})
            self._history.append({"role": "assistant", "content": response_text})

            return response_text, [pyautogui_code]

        except Exception as e:
            logger.error(f"RPAAgent.predict error: {e}", exc_info=True)
            return f"Error: {e}", ["WAIT"]

    def _snap_to_element(self, action_dict: Dict):
        """
        Snap click coordinates to the nearest detected element's center.

        Only snaps if a matching element is within 30 pixels of the VLM's
        target coordinates. This improves click precision without overriding
        the VLM's intent.
        """
        if not self._taxonomy_pipeline:
            return

        x = int(action_dict.get("x", 0))
        y = int(action_dict.get("y", 0))

        matched = self._taxonomy_pipeline.knowledge_graph.match_target(x, y)
        if matched is None:
            return

        dist = math.dist((x, y), matched.center)
        if dist < 30:
            old_x, old_y = x, y
            # Snap to element center (in VLM image space, before scaling)
            action_dict["x"] = matched.center[0]
            action_dict["y"] = matched.center[1]
            logger.info(
                f"Taxonomy: snapped ({old_x},{old_y}) -> [{matched.element_id}] "
                f"'{matched.label}' at {matched.center} (dist={dist:.1f}px)"
            )

            # Record click for knowledge graph tracking
            self._taxonomy_pipeline.knowledge_graph.record_click_outcome(
                matched.center[0], matched.center[1],
                matched.element_id
            )
        else:
            logger.debug(
                f"Taxonomy: no snap — nearest element [{matched.element_id}] "
                f"'{matched.label}' at {matched.center} too far (dist={dist:.1f}px)"
            )
