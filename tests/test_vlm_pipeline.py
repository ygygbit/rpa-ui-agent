"""
VLM Coordinate Accuracy Test — Full Pipeline.

Simulates the complete agent pipeline:
1. Capture screenshot (1920x1080)
2. Resize to 1344x756 for VLM
3. Draw grid with original-coordinate labels
4. Send to VLM, get image-pixel coordinates back
5. RESCALE coordinates back to 1920x1080 screen space
6. Compare against CDP ground truth
"""

import json
import requests
import base64
import io
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image
from rpa_agent.vlm import VLMClient
from rpa_agent.agent import GUIAgent

SANDBOX_URL = "http://localhost:8000"


def get_screenshot() -> Image.Image:
    resp = requests.get(f"{SANDBOX_URL}/screenshot", params={"format": "png"})
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content))


def test_full_pipeline():
    # Ground truth from CDP
    chrome_offset = 143
    raw_elements = [
        {"name": "DuckDuckGo search box", "desc": "the main search input text field in the center of the DuckDuckGo page", "vpX": 939, "vpY": 453, "w": 556, "h": 32},
        {"name": "DuckDuckGo logo", "desc": "the DuckDuckGo logo/icon image above the search box", "vpX": 949, "vpY": 255, "w": 200, "h": 160},
        {"name": "Menu button (top right)", "desc": "the hamburger menu button in the top-right corner of the page", "vpX": 1817, "vpY": 59, "w": 32, "h": 32},
        {"name": "Customize button (bottom right)", "desc": "the 'Customize' button in the bottom-right area of the page", "vpX": 1810, "vpY": 857, "w": 125, "h": 32},
    ]

    elements = []
    for el in raw_elements:
        sy = el["vpY"] + chrome_offset
        if 0 < sy < 1080:
            elements.append({**el, "screenX": el["vpX"], "screenY": sy})

    # Capture
    img = get_screenshot()
    original_w, original_h = img.size
    print(f"Screenshot: {img.size}")

    # Resize (same as agent)
    max_edge = 1344
    scale_down = max_edge / max(original_w, original_h)
    new_w = round(original_w * scale_down)
    new_h = round(original_h * scale_down)
    vlm_img = img.resize((new_w, new_h), Image.LANCZOS)
    print(f"Resized for VLM: {vlm_img.size} (scale_down={scale_down:.4f})")

    # Inverse scale for rescaling VLM coords back
    scale_up = 1.0 / scale_down
    print(f"Rescale factor: {scale_up:.4f}")

    # Draw grid with original-coordinate labels
    grid_img = GUIAgent._draw_coordinate_grid(vlm_img, original_size=(original_w, original_h))

    # Encode
    buffer = io.BytesIO()
    grid_img.save(buffer, format="PNG", optimize=True)
    base64_img = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")

    vlm = VLMClient()
    print(f"VLM: {vlm.config.model} @ {vlm.config.base_url}")

    results = []
    for i, el in enumerate(elements):
        print(f"\n{'='*60}")
        print(f"Element {i+1}: {el['name']}")
        print(f"Ground truth: ({el['screenX']}, {el['screenY']})")

        prompt = f"""Look at this screenshot with a coordinate grid overlay.
The grid has labeled lines every 100 pixels. Labels at the top, bottom, left, right edges.
Screen dimensions: {original_w}x{original_h}.

Find the EXACT pixel coordinates of: {el['desc']}

Use the grid lines to determine coordinates. Respond with ONLY JSON:
{{"x": <number>, "y": <number>, "reasoning": "<brief>"}}"""

        try:
            response = vlm.client.messages.create(
                model=vlm.config.model,
                max_tokens=500,
                system="You are a coordinate estimation specialist. Determine exact pixel coordinates of elements using the grid overlay labels. Respond with only JSON.",
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64_img}},
                    {"type": "text", "text": prompt}
                ]}],
                temperature=0.0
            )

            vlm_text = response.content[0].text.strip()
            # Parse JSON
            json_text = vlm_text
            start = json_text.find("{")
            end = json_text.rfind("}") + 1
            if start >= 0 and end > start:
                json_text = json_text[start:end]
            vlm_coords = json.loads(json_text)

            raw_x, raw_y = vlm_coords["x"], vlm_coords["y"]
            # RESCALE to screen space
            scaled_x = round(raw_x * scale_up)
            scaled_y = round(raw_y * scale_up)

            dx = scaled_x - el["screenX"]
            dy = scaled_y - el["screenY"]
            dist = (dx**2 + dy**2) ** 0.5

            # Hit check
            el_left = el["screenX"] - el["w"] // 2
            el_right = el["screenX"] + el["w"] // 2
            el_top = el["screenY"] - el["h"] // 2
            el_bottom = el["screenY"] + el["h"] // 2
            hit = (el_left <= scaled_x <= el_right) and (el_top <= scaled_y <= el_bottom)

            print(f"  VLM raw:    ({raw_x}, {raw_y})")
            print(f"  Rescaled:   ({scaled_x}, {scaled_y})")
            print(f"  Error:      dx={dx:+d}, dy={dy:+d}, dist={dist:.1f}px")
            print(f"  Hit:        {'YES' if hit else 'NO'}")

            results.append({
                "element": el["name"],
                "truth": (el["screenX"], el["screenY"]),
                "vlm_raw": (raw_x, raw_y),
                "rescaled": (scaled_x, scaled_y),
                "error": (dx, dy),
                "distance": round(dist, 1),
                "hit": hit,
            })

        except Exception as e:
            print(f"  ERROR: {e}")

    # Summary
    valid = [r for r in results if "rescaled" in r]
    if valid:
        hits = sum(r["hit"] for r in valid)
        avg_dx = sum(r["error"][0] for r in valid) / len(valid)
        avg_dy = sum(r["error"][1] for r in valid) / len(valid)
        avg_dist = sum(r["distance"] for r in valid) / len(valid)

        print(f"\n{'='*60}")
        print(f"FULL PIPELINE RESULTS")
        print(f"{'='*60}")
        print(f"Hit rate: {hits}/{len(valid)} ({100*hits/len(valid):.0f}%)")
        print(f"Avg error: dx={avg_dx:+.1f}, dy={avg_dy:+.1f}, dist={avg_dist:.1f}px")
        print()
        fmt = "{:<30} {:>12} {:>12} {:>12} {:>6} {:>4}"
        print(fmt.format("Element", "Truth", "Rescaled", "Error", "Dist", "Hit"))
        print("-" * 80)
        for r in valid:
            print(fmt.format(
                r["element"][:29],
                f"({r['truth'][0]:>4},{r['truth'][1]:>4})",
                f"({r['rescaled'][0]:>4},{r['rescaled'][1]:>4})",
                f"({r['error'][0]:>+4},{r['error'][1]:>+4})",
                f"{r['distance']:>5.1f}",
                "YES" if r["hit"] else "NO"
            ))


if __name__ == "__main__":
    test_full_pipeline()
