#!/usr/bin/env python
"""
UI automation helper for Claude Code skills.
Provides simple CLI commands for mouse, keyboard, and screen operations.
"""

import argparse
import base64
import json
import sys
import time
from pathlib import Path

# Lazy imports to avoid loading everything
def get_screen():
    import mss
    return mss.mss()

def get_mouse():
    import ctypes

    class Mouse:
        user32 = ctypes.windll.user32

        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP = 0x0004
        MOUSEEVENTF_RIGHTDOWN = 0x0008
        MOUSEEVENTF_RIGHTUP = 0x0010
        MOUSEEVENTF_WHEEL = 0x0800

        @classmethod
        def get_position(cls):
            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
            pt = POINT()
            cls.user32.GetCursorPos(ctypes.byref(pt))
            return pt.x, pt.y

        @classmethod
        def move(cls, x, y):
            cls.user32.SetCursorPos(int(x), int(y))

        @classmethod
        def click(cls, x=None, y=None, button='left', clicks=1):
            if x is not None and y is not None:
                cls.move(x, y)
                time.sleep(0.05)

            if button == 'left':
                down, up = cls.MOUSEEVENTF_LEFTDOWN, cls.MOUSEEVENTF_LEFTUP
            else:
                down, up = cls.MOUSEEVENTF_RIGHTDOWN, cls.MOUSEEVENTF_RIGHTUP

            for _ in range(clicks):
                cls.user32.mouse_event(down, 0, 0, 0, 0)
                time.sleep(0.05)
                cls.user32.mouse_event(up, 0, 0, 0, 0)
                if clicks > 1:
                    time.sleep(0.1)

        @classmethod
        def scroll(cls, amount):
            cls.user32.mouse_event(cls.MOUSEEVENTF_WHEEL, 0, 0, int(amount * 120), 0)

        @classmethod
        def drag(cls, x1, y1, x2, y2, duration=0.5):
            cls.move(x1, y1)
            time.sleep(0.1)
            cls.user32.mouse_event(cls.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)

            steps = 20
            for i in range(1, steps + 1):
                cx = x1 + (x2 - x1) * i / steps
                cy = y1 + (y2 - y1) * i / steps
                cls.move(int(cx), int(cy))
                time.sleep(duration / steps)

            cls.user32.mouse_event(cls.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    return Mouse

def cmd_screenshot(args):
    """Capture screenshot."""
    sct = get_screen()
    monitor = sct.monitors[1]  # Primary monitor

    img = sct.grab(monitor)

    # Save to file
    output = args.output or "screenshot.png"
    from PIL import Image
    im = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
    im.save(output)

    result = {
        "file": output,
        "width": img.width,
        "height": img.height
    }

    if args.base64:
        import io
        buffer = io.BytesIO()
        im.save(buffer, format="PNG")
        result["base64"] = base64.standard_b64encode(buffer.getvalue()).decode()

    print(json.dumps(result))

def cmd_click(args):
    """Click at coordinates."""
    Mouse = get_mouse()

    clicks = 2 if args.double else 1
    button = 'right' if args.right else 'left'

    Mouse.click(args.x, args.y, button=button, clicks=clicks)
    print(json.dumps({"action": "click", "x": args.x, "y": args.y, "button": button, "clicks": clicks}))

def cmd_move(args):
    """Move mouse."""
    Mouse = get_mouse()
    Mouse.move(args.x, args.y)
    print(json.dumps({"action": "move", "x": args.x, "y": args.y}))

def cmd_type(args):
    """Type text."""
    import ctypes

    # Use SendInput for more reliable typing
    text = args.text

    # Simple approach using SendKeys via PowerShell
    import subprocess
    # Escape special chars for SendKeys
    escaped = text.replace('{', '{{').replace('}', '}}').replace('+', '{+}').replace('^', '{^}').replace('%', '{%}').replace('~', '{~}')
    if args.enter:
        escaped += '{ENTER}'

    subprocess.run([
        'powershell', '-Command',
        f'Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait("{escaped}")'
    ], capture_output=True)

    print(json.dumps({"action": "type", "text": text, "enter": args.enter}))

def cmd_key(args):
    """Press a key."""
    import subprocess

    key_map = {
        'enter': '{ENTER}', 'tab': '{TAB}', 'escape': '{ESC}', 'esc': '{ESC}',
        'backspace': '{BS}', 'delete': '{DEL}', 'space': ' ',
        'up': '{UP}', 'down': '{DOWN}', 'left': '{LEFT}', 'right': '{RIGHT}',
        'home': '{HOME}', 'end': '{END}', 'pageup': '{PGUP}', 'pagedown': '{PGDN}',
        'f1': '{F1}', 'f2': '{F2}', 'f3': '{F3}', 'f4': '{F4}', 'f5': '{F5}',
        'f6': '{F6}', 'f7': '{F7}', 'f8': '{F8}', 'f9': '{F9}', 'f10': '{F10}',
        'f11': '{F11}', 'f12': '{F12}',
    }

    key = args.key.lower()
    sendkey = key_map.get(key, key)

    subprocess.run([
        'powershell', '-Command',
        f'Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait("{sendkey}")'
    ], capture_output=True)

    print(json.dumps({"action": "key", "key": args.key}))

def cmd_hotkey(args):
    """Press hotkey combination."""
    import subprocess

    # Build SendKeys string
    mods = {'ctrl': '^', 'alt': '%', 'shift': '+'}
    combo = ''
    for k in args.keys[:-1]:
        combo += mods.get(k.lower(), '')
    combo += args.keys[-1]

    subprocess.run([
        'powershell', '-Command',
        f'Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait("{combo}")'
    ], capture_output=True)

    print(json.dumps({"action": "hotkey", "keys": args.keys}))

def cmd_drag(args):
    """Drag from one point to another."""
    Mouse = get_mouse()
    Mouse.drag(args.x1, args.y1, args.x2, args.y2)
    print(json.dumps({"action": "drag", "from": [args.x1, args.y1], "to": [args.x2, args.y2]}))

def cmd_scroll(args):
    """Scroll."""
    Mouse = get_mouse()
    Mouse.scroll(args.amount)
    print(json.dumps({"action": "scroll", "amount": args.amount}))

def cmd_position(args):
    """Get mouse position."""
    Mouse = get_mouse()
    x, y = Mouse.get_position()
    print(json.dumps({"x": x, "y": y}))

def cmd_analyze(args):
    """Capture and analyze screen with vision model."""
    import anthropic

    # Capture screenshot
    sct = get_screen()
    monitor = sct.monitors[1]
    img = sct.grab(monitor)

    from PIL import Image
    import io
    im = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
    buffer = io.BytesIO()
    im.save(buffer, format="PNG")
    img_base64 = base64.standard_b64encode(buffer.getvalue()).decode()

    # Call vision API
    client = anthropic.Anthropic(
        api_key="Powered by Agent Maestro",
        base_url="http://localhost:23333/api/anthropic"
    )

    prompt = args.prompt or "Describe what you see on this screen."

    response = client.messages.create(
        model="claude-opus-4.6-1m",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": img_base64
                    }
                },
                {"type": "text", "text": prompt}
            ]
        }]
    )

    print(response.content[0].text)

def cmd_find(args):
    """Find element coordinates on screen."""
    import anthropic

    # Capture screenshot
    sct = get_screen()
    monitor = sct.monitors[1]
    img = sct.grab(monitor)

    from PIL import Image
    import io
    im = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
    buffer = io.BytesIO()
    im.save(buffer, format="PNG")
    img_base64 = base64.standard_b64encode(buffer.getvalue()).decode()

    # Call vision API
    client = anthropic.Anthropic(
        api_key="Powered by Agent Maestro",
        base_url="http://localhost:23333/api/anthropic"
    )

    prompt = f"""Find this UI element: "{args.element}"

Screen dimensions: {img.width}x{img.height} pixels.

Return ONLY a JSON object with the CENTER coordinates:
{{"found": true, "x": <number>, "y": <number>, "element": "<description>"}}

Or if not found:
{{"found": false, "reason": "<why not found>"}}"""

    response = client.messages.create(
        model="claude-opus-4.6-1m",
        max_tokens=256,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": img_base64
                    }
                },
                {"type": "text", "text": prompt}
            ]
        }]
    )

    print(response.content[0].text)


def main():
    parser = argparse.ArgumentParser(description="UI automation helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Screenshot
    p = subparsers.add_parser("screenshot", help="Capture screenshot")
    p.add_argument("-o", "--output", help="Output file")
    p.add_argument("--base64", action="store_true", help="Include base64 in output")
    p.set_defaults(func=cmd_screenshot)

    # Click
    p = subparsers.add_parser("click", help="Click at coordinates")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.add_argument("--right", action="store_true", help="Right click")
    p.add_argument("--double", action="store_true", help="Double click")
    p.set_defaults(func=cmd_click)

    # Move
    p = subparsers.add_parser("move", help="Move mouse")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.set_defaults(func=cmd_move)

    # Type
    p = subparsers.add_parser("type", help="Type text")
    p.add_argument("text")
    p.add_argument("--enter", action="store_true", help="Press enter after")
    p.set_defaults(func=cmd_type)

    # Key
    p = subparsers.add_parser("key", help="Press key")
    p.add_argument("key")
    p.set_defaults(func=cmd_key)

    # Hotkey
    p = subparsers.add_parser("hotkey", help="Press hotkey combo")
    p.add_argument("keys", nargs="+")
    p.set_defaults(func=cmd_hotkey)

    # Drag
    p = subparsers.add_parser("drag", help="Drag")
    p.add_argument("x1", type=int)
    p.add_argument("y1", type=int)
    p.add_argument("x2", type=int)
    p.add_argument("y2", type=int)
    p.set_defaults(func=cmd_drag)

    # Scroll
    p = subparsers.add_parser("scroll", help="Scroll (positive=up)")
    p.add_argument("amount", type=int)
    p.set_defaults(func=cmd_scroll)

    # Position
    p = subparsers.add_parser("position", help="Get mouse position")
    p.set_defaults(func=cmd_position)

    # Analyze
    p = subparsers.add_parser("analyze", help="Analyze screen with vision")
    p.add_argument("-p", "--prompt", help="Custom prompt")
    p.set_defaults(func=cmd_analyze)

    # Find
    p = subparsers.add_parser("find", help="Find element on screen")
    p.add_argument("element", help="Element description")
    p.set_defaults(func=cmd_find)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
