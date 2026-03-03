"""
VLM Coordinate Accuracy Test — with pre-resize fix.

Resizes the screenshot BEFORE drawing the grid overlay, then draws grid
labels in original screen coordinates.  This matches what the VLM API
internally sees, eliminating the ~30% coordinate offset.
"""

import json
import requests
import base64
import io
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image, ImageDraw, ImageFont
from rpa_agent.vlm import VLMClient
from rpa_agent.agent import GUIAgent

SANDBOX_URL = "http://localhost:8000"


def get_screenshot() -> Image.Image:
    """Capture screenshot from sandbox."""
    resp = requests.get(f"{SANDBOX_URL}/screenshot", params={"format": "png"})
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content))


def test_vlm_accuracy():
    """Run the VLM coordinate accuracy test with pre-resize fix."""

    # Ground truth from CDP (obtained via docker exec)
    chrome_offset = 143
    raw_elements = [
        {"name": "DuckDuckGo search box", "desc": "the main search input text field in the center of the DuckDuckGo page", "vpX": 939, "vpY": 453, "w": 556, "h": 32},
        {"name": "DuckDuckGo logo", "desc": "the DuckDuckGo logo/icon image above the search box", "vpX": 949, "vpY": 255, "w": 200, "h": 160},
        {"name": "Menu button (top right)", "desc": "the hamburger menu button in the top-right corner of the page", "vpX": 1817, "vpY": 59, "w": 32, "h": 32},
        {"name": "Customize button (bottom right)", "desc": "the 'Customize' button in the bottom-right area of the page", "vpX": 1810, "vpY": 857, "w": 125, "h": 32},
    ]

    # Convert to screen coordinates
    elements = []
    for el in raw_elements:
        screen_x = el["vpX"]
        screen_y = el["vpY"] + chrome_offset
        if screen_y < 1080 and screen_y > 0:
            elements.append({
                "name": el["name"],
                "desc": el["desc"],
                "screenX": screen_x,
                "screenY": screen_y,
                "w": el["w"],
                "h": el["h"],
            })

    print(f"Chrome browser chrome height: {chrome_offset}px")
    print(f"\nGround truth elements ({len(elements)} visible on screen):")
    for i, el in enumerate(elements):
        print(f"  {i+1}. {el['name']}")
        print(f"     Screen: ({el['screenX']}, {el['screenY']}), size: {el['w']}x{el['h']}")

    # Capture screenshot
    print("\nCapturing screenshot...")
    img = get_screenshot()
    original_w, original_h = img.size
    print(f"Screenshot size: {img.size}")

    # Apply the SAME resize logic as agent._capture_screenshot
    max_edge = 1344
    scale_factor = 1.0
    vlm_img = img
    if max(original_w, original_h) > max_edge:
        scale_factor = max_edge / max(original_w, original_h)
        new_w = round(original_w * scale_factor)
        new_h = round(original_h * scale_factor)
        vlm_img = img.resize((new_w, new_h), Image.LANCZOS)
        print(f"Resized for VLM: {vlm_img.size} (scale={scale_factor:.4f})")
    else:
        print("No resize needed")

    # Draw grid overlay using agent's method (with original_size)
    grid_img = GUIAgent._draw_coordinate_grid(
        vlm_img, original_size=(original_w, original_h)
    )

    # Save for reference
    img.save("test_vlm_raw.png")
    grid_img.save("test_vlm_grid_fixed.png")
    print(f"Saved test_vlm_raw.png and test_vlm_grid_fixed.png")
    print(f"Grid image size: {grid_img.size}")

    # Encode grid image for VLM
    buffer = io.BytesIO()
    grid_img.save(buffer, format="PNG", optimize=True)
    base64_img = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")

    # Initialize VLM client
    vlm = VLMClient()
    print(f"\nVLM model: {vlm.config.model}")
    print(f"VLM endpoint: {vlm.config.base_url or 'official Anthropic API'}")

    # Test each element
    results = []
    for i, el in enumerate(elements):
        print(f"\n{'='*60}")
        print(f"Testing element {i+1}/{len(elements)}: {el['name']}")
        print(f"Ground truth screen coords: ({el['screenX']}, {el['screenY']})")

        prompt = f"""Look at this screenshot with a coordinate grid overlay.
The grid has labeled lines every 100 pixels. Labels appear at the top, bottom, left, and right edges.
The screen dimensions are {original_w}x{original_h}.

Find the EXACT pixel coordinates of: {el['desc']}

Steps:
1. Find the element visually
2. Look at the nearest VERTICAL grid lines (numbers at top/bottom edges) to determine X
3. Look at the nearest HORIZONTAL grid lines (numbers at left/right edges) to determine Y
4. Interpolate between the two nearest grid lines on each axis

Respond with ONLY a JSON object:
{{"x": <number>, "y": <number>, "reasoning": "<how you determined x and y from the grid lines>"}}"""

        try:
            response = vlm.client.messages.create(
                model=vlm.config.model,
                max_tokens=500,
                system="You are a coordinate estimation specialist. Given a screenshot with a labeled coordinate grid overlay, determine exact pixel coordinates of specified elements by reading the grid line labels. Respond with only JSON.",
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": base64_img
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }],
                temperature=0.0
            )

            vlm_text = response.content[0].text.strip()
            print(f"VLM raw response: {vlm_text[:200]}")

            # Parse JSON
            json_text = vlm_text
            if "```" in json_text:
                start = json_text.find("{")
                end = json_text.rfind("}") + 1
                if start >= 0 and end > start:
                    json_text = json_text[start:end]
            elif not json_text.startswith("{"):
                start = json_text.find("{")
                end = json_text.rfind("}") + 1
                if start >= 0 and end > start:
                    json_text = json_text[start:end]

            vlm_coords = json.loads(json_text)
            vlm_x = vlm_coords["x"]
            vlm_y = vlm_coords["y"]

            dx = vlm_x - el["screenX"]
            dy = vlm_y - el["screenY"]
            distance = (dx**2 + dy**2) ** 0.5

            # Check hit
            el_left = el["screenX"] - el["w"] // 2
            el_right = el["screenX"] + el["w"] // 2
            el_top = el["screenY"] - el["h"] // 2
            el_bottom = el["screenY"] + el["h"] // 2
            hit = (el_left <= vlm_x <= el_right) and (el_top <= vlm_y <= el_bottom)

            result = {
                "element": el["name"],
                "ground_truth": {"x": el["screenX"], "y": el["screenY"]},
                "vlm_estimate": {"x": vlm_x, "y": vlm_y},
                "error": {"dx": dx, "dy": dy, "distance": round(distance, 1)},
                "hit_element": hit,
                "element_size": {"w": el["w"], "h": el["h"]},
                "reasoning": vlm_coords.get("reasoning", "")
            }
            results.append(result)

            status = "HIT" if hit else "MISS"
            print(f"  VLM estimate: ({vlm_x}, {vlm_y})")
            print(f"  Error: dx={dx:+d}, dy={dy:+d}, distance={distance:.1f}px")
            print(f"  Element bbox: ({el_left},{el_top}) to ({el_right},{el_bottom})")
            print(f"  --> {status}")

        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                "element": el["name"],
                "ground_truth": {"x": el["screenX"], "y": el["screenY"]},
                "error_msg": str(e)
            })

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY (with pre-resize fix)")
    print(f"{'='*60}")

    valid_results = [r for r in results if "vlm_estimate" in r]
    if valid_results:
        hits = sum(1 for r in valid_results if r["hit_element"])
        avg_dx = sum(r["error"]["dx"] for r in valid_results) / len(valid_results)
        avg_dy = sum(r["error"]["dy"] for r in valid_results) / len(valid_results)
        avg_dist = sum(r["error"]["distance"] for r in valid_results) / len(valid_results)
        max_dist = max(r["error"]["distance"] for r in valid_results)

        print(f"Elements tested: {len(results)}")
        print(f"Valid VLM responses: {len(valid_results)}")
        print(f"Hit rate: {hits}/{len(valid_results)} ({100*hits/len(valid_results):.0f}%)")
        print(f"Average X error: {avg_dx:+.1f}px")
        print(f"Average Y error: {avg_dy:+.1f}px")
        print(f"Average distance error: {avg_dist:.1f}px")
        print(f"Max distance error: {max_dist:.1f}px")

        print(f"\nPer-element breakdown:")
        fmt = "{:<35} {:>12} {:>12} {:>12} {:>6} {:>4}"
        print(fmt.format("Element", "Truth", "VLM", "Error", "Dist", "Hit"))
        print("-" * 85)
        for r in valid_results:
            gt = r["ground_truth"]
            ve = r["vlm_estimate"]
            err = r["error"]
            hit_str = "YES" if r["hit_element"] else "NO"
            print(fmt.format(
                r["element"][:34],
                f"({gt['x']:>4},{gt['y']:>4})",
                f"({ve['x']:>4},{ve['y']:>4})",
                f"({err['dx']:>+4},{err['dy']:>+4})",
                f"{err['distance']:>5.1f}",
                hit_str
            ))

        # Analyze systematic offset
        all_dx = [r["error"]["dx"] for r in valid_results]
        all_dy = [r["error"]["dy"] for r in valid_results]
        dx_std = (sum((d - avg_dx)**2 for d in all_dx) / len(all_dx)) ** 0.5
        dy_std = (sum((d - avg_dy)**2 for d in all_dy) / len(all_dy)) ** 0.5

        print(f"\nOffset analysis:")
        print(f"  X offset: mean={avg_dx:+.1f}px, std={dx_std:.1f}px")
        print(f"  Y offset: mean={avg_dy:+.1f}px, std={dy_std:.1f}px")

        if abs(avg_dx) > 20 or abs(avg_dy) > 20:
            print(f"\n  ** SYSTEMATIC OFFSET STILL PRESENT: ({avg_dx:+.0f}, {avg_dy:+.0f}) **")
        elif avg_dist > 50:
            print(f"\n  ** MODERATE RANDOM ERROR: avg {avg_dist:.0f}px **")
        else:
            print(f"\n  ** ACCURACY SIGNIFICANTLY IMPROVED! (avg error {avg_dist:.0f}px) **")

    # Save results
    with open("test_vlm_accuracy_results_fixed.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nDetailed results saved to test_vlm_accuracy_results_fixed.json")


if __name__ == "__main__":
    test_vlm_accuracy()
