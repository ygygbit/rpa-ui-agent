#!/usr/bin/env python3
"""
XTEST Input Diagnostic Script

Tests whether python-xlib XTEST keyboard events work for Chrome web content.
This is the critical test that determines whether we can eliminate CDP for typing.

Run inside the Docker container:
    python3 /app/rpa_agent/sandbox/test_xtest_input.py
"""

import json
import time
import urllib.request
from Xlib.display import Display
from Xlib import X, XK
from Xlib.ext.xtest import fake_input

# ============================================================
# XTEST helpers
# ============================================================

display = Display(':99')
root = display.screen().root


def _sync():
    """Flush display buffer. Uses flush() instead of sync() to avoid BadRRModeError on Xvfb."""
    display.flush()
    time.sleep(0.003)


# Shift-required characters
SHIFT_CHARS = set('~!@#$%^&*()_+{}|:"<>?ABCDEFGHIJKLMNOPQRSTUVWXYZ')

# Special character to keysym name mapping
CHAR_TO_KEYSYM = {
    ' ': 'space',
    '\t': 'Tab',
    '\n': 'Return',
    '!': 'exclam',
    '@': 'at',
    '#': 'numbersign',
    '$': 'dollar',
    '%': 'percent',
    '^': 'asciicircum',
    '&': 'ampersand',
    '*': 'asterisk',
    '(': 'parenleft',
    ')': 'parenright',
    '-': 'minus',
    '_': 'underscore',
    '=': 'equal',
    '+': 'plus',
    '[': 'bracketleft',
    ']': 'bracketright',
    '{': 'braceleft',
    '}': 'braceright',
    '\\': 'backslash',
    '|': 'bar',
    ';': 'semicolon',
    ':': 'colon',
    "'": 'apostrophe',
    '"': 'quotedbl',
    ',': 'comma',
    '.': 'period',
    '<': 'less',
    '>': 'greater',
    '/': 'slash',
    '?': 'question',
    '`': 'grave',
    '~': 'asciitilde',
}


def char_to_keycode(char):
    """Convert a character to (keycode, needs_shift)."""
    needs_shift = char in SHIFT_CHARS

    # Try keysym name mapping first
    if char in CHAR_TO_KEYSYM:
        keysym = XK.string_to_keysym(CHAR_TO_KEYSYM[char])
    else:
        # For regular letters/digits, use the character directly
        keysym = XK.string_to_keysym(char)

    if keysym == 0:
        # Fallback: try lowercase version
        keysym = XK.string_to_keysym(char.lower())
        if keysym == 0:
            print(f"  WARNING: No keysym for char '{char}'")
            return None, False

    keycode = display.keysym_to_keycode(keysym)
    if keycode == 0:
        # Try the unshifted version
        keysym_lower = XK.string_to_keysym(char.lower())
        keycode = display.keysym_to_keycode(keysym_lower)
        if keycode == 0:
            print(f"  WARNING: No keycode for char '{char}' (keysym={keysym})")
            return None, False

    return keycode, needs_shift


def xtest_move(x, y):
    """Move mouse to absolute position via XTEST."""
    fake_input(display, X.MotionNotify, x=x, y=y)
    _sync()


def xtest_click(x, y, button=1):
    """Click at position via XTEST."""
    xtest_move(x, y)
    time.sleep(0.05)
    fake_input(display, X.ButtonPress, button)
    _sync()
    time.sleep(0.02)
    fake_input(display, X.ButtonRelease, button)
    _sync()


def xtest_key(keycode, shift=False):
    """Press and release a key via XTEST."""
    shift_keycode = display.keysym_to_keycode(XK.XK_Shift_L)
    if shift:
        fake_input(display, X.KeyPress, shift_keycode)
        _sync()
    fake_input(display, X.KeyPress, keycode)
    _sync()
    time.sleep(0.01)
    fake_input(display, X.KeyRelease, keycode)
    _sync()
    if shift:
        fake_input(display, X.KeyRelease, shift_keycode)
        _sync()


def xtest_type(text):
    """Type a string via XTEST key events."""
    for char in text:
        keycode, needs_shift = char_to_keycode(char)
        if keycode is not None:
            xtest_key(keycode, shift=needs_shift)
            time.sleep(0.02)


def xtest_press_enter():
    """Press Enter via XTEST."""
    keycode = display.keysym_to_keycode(XK.XK_Return)
    xtest_key(keycode)


def xtest_press_escape():
    """Press Escape via XTEST."""
    keycode = display.keysym_to_keycode(XK.XK_Escape)
    xtest_key(keycode)


def xtest_hotkey(*keysyms):
    """Press a key combination via XTEST (e.g. Ctrl+A, Ctrl+L)."""
    keycodes = [display.keysym_to_keycode(ks) for ks in keysyms]
    for kc in keycodes:
        fake_input(display, X.KeyPress, kc)
        _sync()
    time.sleep(0.02)
    for kc in reversed(keycodes):
        fake_input(display, X.KeyRelease, kc)
        _sync()


# ============================================================
# CDP helpers
# ============================================================

CDP_PORT = 9222


def cdp_get_ws_url():
    """Get WebSocket URL for active Chrome tab."""
    try:
        data = urllib.request.urlopen(f'http://127.0.0.1:{CDP_PORT}/json', timeout=2).read()
        tabs = json.loads(data)
        # Prefer data: or http/https pages
        for tab in tabs:
            if tab.get('type') == 'page' and 'webSocketDebuggerUrl' in tab:
                url = tab.get('url', '')
                if url.startswith('data:') or url.startswith('http') or url == 'about:blank':
                    return tab['webSocketDebuggerUrl']
        return None
    except Exception as e:
        print(f"  CDP error: {e}")
        return None


def cdp_navigate(url):
    """Navigate Chrome to URL via CDP. Reconnects to the new page target."""
    import websocket
    ws_url = cdp_get_ws_url()
    if not ws_url:
        print("  ERROR: No CDP target for navigation")
        return
    ws = websocket.create_connection(ws_url, timeout=5)
    ws.send(json.dumps({
        'id': 1, 'method': 'Page.navigate',
        'params': {'url': url}
    }))
    for _ in range(20):
        r = json.loads(ws.recv())
        if r.get('id') == 1:
            break
    ws.close()
    time.sleep(2)  # Wait for page to load


def cdp_eval(expression):
    """Evaluate JS expression via CDP and return the value."""
    import websocket
    ws_url = cdp_get_ws_url()
    if not ws_url:
        return None
    try:
        ws = websocket.create_connection(ws_url, timeout=5)
        msg = json.dumps({
            'id': 1,
            'method': 'Runtime.evaluate',
            'params': {'expression': expression, 'returnByValue': True}
        })
        ws.send(msg)
        deadline = time.time() + 5
        while time.time() < deadline:
            resp = json.loads(ws.recv())
            if resp.get('id') == 1:
                ws.close()
                return resp.get('result', {}).get('result', {}).get('value')
        ws.close()
        return None
    except Exception as e:
        print(f"  CDP eval error: {e}")
        return None


# ============================================================
# Tests
# ============================================================

def test_mouse_accuracy():
    """Test XTEST mouse move accuracy."""
    print("\n=== Test 1: Mouse Move Accuracy ===")
    test_points = [
        (100, 100), (960, 540), (1800, 100),
        (100, 1000), (1800, 1000), (500, 300),
        (1400, 700), (960, 100), (960, 1000),
        (1, 1),
    ]
    all_ok = True
    for target_x, target_y in test_points:
        xtest_move(target_x, target_y)
        time.sleep(0.05)
        ptr = root.query_pointer()
        actual_x, actual_y = ptr.root_x, ptr.root_y
        drift = abs(actual_x - target_x) + abs(actual_y - target_y)
        status = "OK" if drift == 0 else f"DRIFT={drift}"
        if drift != 0:
            all_ok = False
        print(f"  Target ({target_x:4d},{target_y:4d}) -> Actual ({actual_x:4d},{actual_y:4d}) [{status}]")
    print(f"  Result: {'PASS' if all_ok else 'FAIL'}")
    return all_ok


def test_keyboard_address_bar():
    """Test XTEST typing in Chrome address bar."""
    print("\n=== Test 2: XTEST Keyboard in Address Bar ===")

    # Focus address bar with Ctrl+L
    xtest_hotkey(XK.XK_Control_L, XK.XK_l)
    time.sleep(0.3)

    # Type a URL
    test_url = "about:blank"
    xtest_type(test_url)
    time.sleep(0.2)
    xtest_press_enter()
    time.sleep(1.0)

    # Verify navigation
    current_url = cdp_eval("window.location.href")
    print(f"  Typed: {test_url}")
    print(f"  Current URL: {current_url}")
    ok = current_url == "about:blank"
    print(f"  Result: {'PASS' if ok else 'FAIL'}")
    return ok


def test_keyboard_web_content():
    """Test XTEST typing in a web page text input — THE CRITICAL TEST."""
    print("\n=== Test 3: XTEST Keyboard in Chrome Web Content (CRITICAL) ===")

    # Navigate via CDP (avoids needing to type special chars like < in address bar)
    html = '<html><body><input id="t" type="text" style="width:600px;height:60px;font-size:24px;margin:50px" autofocus></body></html>'
    cdp_navigate(f'data:text/html,{html}')

    # Click on the input field to focus it
    # Chrome toolbar is ~85px, input has margin:50px, so input top is ~135px in screen coords
    # Input is 60px tall, so center is ~165px. Using generous coords.
    xtest_click(350, 170)
    time.sleep(0.3)

    # Verify focus
    active = cdp_eval('document.activeElement ? document.activeElement.tagName + " id=" + (document.activeElement.id || "none") : "null"')
    print(f"  Active element: {active}")

    # Clear any existing content
    xtest_hotkey(XK.XK_Control_L, XK.XK_a)
    time.sleep(0.1)
    kc_del = display.keysym_to_keycode(XK.XK_Delete)
    xtest_key(kc_del)
    time.sleep(0.1)

    # Type test text
    test_text = "hello world 123"
    print(f"  Typing via XTEST: '{test_text}'")
    xtest_type(test_text)
    time.sleep(0.5)

    # Read value from the input via CDP
    value = cdp_eval('document.getElementById("t").value')
    print(f"  Input value via CDP: '{value}'")

    ok = value == test_text
    print(f"  Result: {'PASS' if ok else 'FAIL'}")

    if not ok and value:
        print(f"  Expected length: {len(test_text)}, Got length: {len(value)}")
        for i, (expected, actual) in enumerate(zip(test_text, value)):
            if expected != actual:
                print(f"  Mismatch at position {i}: expected '{expected}' got '{actual}'")

    return ok


def test_keyboard_special_chars():
    """Test XTEST typing of special characters in web content."""
    print("\n=== Test 4: XTEST Special Characters ===")

    # Navigate to clean test page via CDP
    html = '<html><body><input id="t" type="text" style="width:800px;height:60px;font-size:24px;margin:50px" autofocus></body></html>'
    cdp_navigate(f'data:text/html,{html}')

    # Click to focus
    xtest_click(400, 170)
    time.sleep(0.3)

    # Clear
    xtest_hotkey(XK.XK_Control_L, XK.XK_a)
    time.sleep(0.1)
    kc_del = display.keysym_to_keycode(XK.XK_Delete)
    xtest_key(kc_del)
    time.sleep(0.1)

    test_text = "Test@123 Hello-World! (ok)"
    print(f"  Typing: '{test_text}'")
    xtest_type(test_text)
    time.sleep(0.5)

    value = cdp_eval('document.getElementById("t").value')
    print(f"  Got:    '{value}'")

    ok = value == test_text
    print(f"  Result: {'PASS' if ok else 'FAIL'}")
    return ok


def test_keyboard_url_typing():
    """Test typing a URL in Chrome web content input."""
    print("\n=== Test 5: URL Typing in Web Content ===")

    html = '<html><body><input id="t" type="text" style="width:800px;height:60px;font-size:24px;margin:50px" autofocus></body></html>'
    cdp_navigate(f'data:text/html,{html}')

    xtest_click(400, 170)
    time.sleep(0.3)

    test_text = "https://duckduckgo.com/search?q=hello+world"
    print(f"  Typing: '{test_text}'")
    xtest_type(test_text)
    time.sleep(0.5)

    value = cdp_eval('document.getElementById("t").value')
    print(f"  Got:    '{value}'")

    ok = value == test_text
    print(f"  Result: {'PASS' if ok else 'FAIL'}")
    return ok


# ============================================================
# Main
# ============================================================

if __name__ == '__main__':
    print("XTEST Input Diagnostic")
    print("=" * 50)

    # Ensure Chrome is running
    try:
        ws_url = cdp_get_ws_url()
        if ws_url:
            print(f"Chrome CDP available: {ws_url[:60]}...")
        else:
            print("WARNING: Chrome not detected via CDP. Start Chrome first.")
    except Exception:
        print("WARNING: Cannot reach Chrome CDP.")

    results = {}
    results['mouse_accuracy'] = test_mouse_accuracy()
    results['address_bar'] = test_keyboard_address_bar()
    results['web_content'] = test_keyboard_web_content()
    results['special_chars'] = test_keyboard_special_chars()
    results['url_typing'] = test_keyboard_url_typing()

    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    for test_name, passed in results.items():
        print(f"  {test_name:20s}: {'PASS' if passed else 'FAIL'}")

    all_passed = all(results.values())
    print(f"\nOverall: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")

    if results['web_content']:
        print("\n>>> XTEST keyboard WORKS for Chrome web content.")
        print(">>> CDP can be ELIMINATED for typing.")
    else:
        print("\n>>> XTEST keyboard FAILS for Chrome web content.")
        print(">>> CDP fallback must be RETAINED for typing.")
