"""
VLM Coordinate Accuracy Test.

Tests whether the VLM correctly estimates UI element coordinates from
grid-overlaid screenshots by comparing VLM responses against CDP ground truth.
"""

import json
import requests
import base64
import io
import sys
import os
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image, ImageDraw, ImageFont
from rpa_agent.vlm import VLMClient, VLMConfig, SystemPrompts

SANDBOX_URL = "http://localhost:8000"


def get_screenshot() -> Image.Image:
    """Capture screenshot from sandbox."""
    resp = requests.get(f"{SANDBOX_URL}/screenshot", params={"format": "png"})
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content))


def draw_coordinate_grid(img: Image.Image, spacing: int = 100) -> Image.Image:
    """Draw a coordinate grid overlay - identical to agent._draw_coordinate_grid()."""
    img = img.copy()
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size

    try:
        font = ImageFont.truetype("arial.ttf", 11)
    except OSError:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
        except OSError:
            font = ImageFont.load_default()

    grid_color = (255, 0, 0, 50)
    major_grid_color = (255, 0, 0, 90)
    label_bg = (0, 0, 0, 160)
    label_fg = (255, 255, 0)

    for x in range(spacing, w, spacing):
        is_major = (x % 500 == 0)
        color = major_grid_color if is_major else grid_color
        line_width = 2 if is_major else 1
        draw.line([(x, 0), (x, h)], fill=color, width=line_width)
        label = str(x)
        bbox = font.getbbox(label)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.rectangle([x - tw // 2 - 2, 0, x + tw // 2 + 2, th + 4], fill=label_bg)
        draw.text((x - tw // 2, 1), label, fill=label_fg, font=font)
        draw.rectangle([x - tw // 2 - 2, h - th - 5, x + tw // 2 + 2, h], fill=label_bg)
        draw.text((x - tw // 2, h - th - 2), label, fill=label_fg, font=font)

    for y in range(spacing, h, spacing):
        is_major = (y % 500 == 0)
        color = major_grid_color if is_major else grid_color
        line_width = 2 if is_major else 1
        draw.line([(0, y), (w, y)], fill=color, width=line_width)
        label = str(y)
        bbox = font.getbbox(label)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.rectangle([0, y - th // 2 - 2, tw + 4, y + th // 2 + 2], fill=label_bg)
        draw.text((2, y - th // 2), label, fill=label_fg, font=font)
        draw.rectangle([w - tw - 5, y - th // 2 - 2, w, y + th // 2 + 2], fill=label_bg)
        draw.text((w - tw - 3, y - th // 2), label, fill=label_fg, font=font)

    cross_size = 4
    cross_color = (255, 255, 0, 80)
    for x in range(spacing, w, spacing):
        for y in range(spacing, h, spacing):
            draw.line([(x - cross_size, y), (x + cross_size, y)], fill=cross_color, width=1)
            draw.line([(x, y - cross_size), (x, y + cross_size)], fill=cross_color, width=1)

    return img.convert("RGB")


def test_vlm_accuracy():
    """Run the VLM coordinate accuracy test."""

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
        # Only include elements visible on screen (y < 1080)
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
    print(f"Screenshot size: {img.size}")

    # Draw grid overlay
    grid_img = draw_coordinate_grid(img)

    # Save both for reference
    img.save("test_vlm_raw.png")
    grid_img.save("test_vlm_grid.png")
    print("Saved test_vlm_raw.png and test_vlm_grid.png")

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
The screen dimensions are 1920x1080.

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

            # Check if VLM coord would hit the element's bounding box on screen
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
    print("SUMMARY")
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
            hit = "YES" if r["hit_element"] else "NO"
            print(fmt.format(
                r["element"][:34],
                f"({gt['x']:>4},{gt['y']:>4})",
                f"({ve['x']:>4},{ve['y']:>4})",
                f"({err['dx']:>+4},{err['dy']:>+4})",
                f"{err['distance']:>5.1f}",
                hit
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
            print(f"\n  ** SYSTEMATIC OFFSET DETECTED: ({avg_dx:+.0f}, {avg_dy:+.0f}) **")
        elif avg_dist > 50:
            print(f"\n  ** HIGH RANDOM ERROR: avg {avg_dist:.0f}px **")
        else:
            print(f"\n  Accuracy is GOOD (avg error {avg_dist:.0f}px)")

    # Save results
    with open("test_vlm_accuracy_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nDetailed results saved to test_vlm_accuracy_results.json")


if __name__ == "__main__":
    test_vlm_accuracy()
