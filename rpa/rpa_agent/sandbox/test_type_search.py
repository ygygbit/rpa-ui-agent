"""Test: Click DuckDuckGo search box and type text, verify with CDP."""
import sys, json, subprocess, time, websocket

from Xlib.display import Display
from Xlib import X, XK
from Xlib.ext.xtest import fake_input as _xtest_fake_input

d = Display(":99")
root = d.screen().root

def flush():
    d.flush()
    d.sync()

def move_to(x, y):
    _xtest_fake_input(d, X.MotionNotify, x=x, y=y)
    flush()

def click_at(x, y):
    move_to(x, y)
    time.sleep(0.1)
    ptr = root.query_pointer()
    print("  Cursor: (%d, %d)" % (ptr.root_x, ptr.root_y))
    _xtest_fake_input(d, X.ButtonPress, 1)
    flush()
    time.sleep(0.1)
    _xtest_fake_input(d, X.ButtonRelease, 1)
    flush()
    time.sleep(0.2)

def type_char(char):
    """Type a single character via XTEST."""
    # For simple ASCII, map to keysym
    if char == ' ':
        keysym = XK.XK_space
    elif char.isalpha():
        keysym = XK.string_to_keysym(char.lower())
    elif char.isdigit():
        keysym = XK.string_to_keysym(char)
    else:
        # Special chars
        mapping = {
            '.': 'period', ',': 'comma', '/': 'slash',
            ':': 'colon', '-': 'minus', '_': 'underscore',
            "'": 'apostrophe',
        }
        name = mapping.get(char)
        if name:
            keysym = XK.string_to_keysym(name)
        else:
            print("  Unknown char: %r" % char)
            return

    keycode = d.keysym_to_keycode(keysym)
    if keycode == 0:
        print("  No keycode for char: %r" % char)
        return

    needs_shift = char.isupper() or char in '~!@#$%%^&*()_+{}|:"<>?'
    shift_kc = d.keysym_to_keycode(XK.XK_Shift_L)

    if needs_shift:
        _xtest_fake_input(d, X.KeyPress, shift_kc)
        flush()
    _xtest_fake_input(d, X.KeyPress, keycode)
    flush()
    time.sleep(0.01)
    _xtest_fake_input(d, X.KeyRelease, keycode)
    flush()
    if needs_shift:
        _xtest_fake_input(d, X.KeyRelease, shift_kc)
        flush()

def type_string(text):
    for ch in text:
        type_char(ch)
        time.sleep(0.02)

# Connect to CDP
cdp_json = subprocess.check_output(["curl", "-s", "http://localhost:9222/json"]).decode()
tabs = json.loads(cdp_json)
ws_url = None
for t in tabs:
    if t.get("type") == "page" and "duckduckgo" in t.get("url", ""):
        ws_url = t["webSocketDebuggerUrl"]
        break

if not ws_url:
    print("No DDG tab found")
    sys.exit(1)

ws = websocket.create_connection(ws_url, timeout=5)

def cdp_eval(expr):
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": expr}}))
    while True:
        r = json.loads(ws.recv())
        if "id" in r:
            return r.get("result", {}).get("result", {}).get("value")

# First navigate back to DDG homepage
print("Navigating to DuckDuckGo homepage...")
cdp_eval("window.location.href = 'https://duckduckgo.com/'")
time.sleep(3)

# Re-check - page navigated, need new CDP connection
ws.close()
time.sleep(1)
cdp_json = subprocess.check_output(["curl", "-s", "http://localhost:9222/json"]).decode()
tabs = json.loads(cdp_json)
ws_url = None
for t in tabs:
    if t.get("type") == "page" and "duckduckgo" in t.get("url", ""):
        ws_url = t["webSocketDebuggerUrl"]
        break

ws = websocket.create_connection(ws_url, timeout=5)

# Get viewport offset
vp = json.loads(cdp_eval("""JSON.stringify({
    innerWidth: window.innerWidth, innerHeight: window.innerHeight,
    outerWidth: window.outerWidth, outerHeight: window.outerHeight,
    screenX: window.screenX, screenY: window.screenY
})""") or "{}")
top_offset = vp.get("screenY", 0) + (vp.get("outerHeight", 0) - vp.get("innerHeight", 0))
print("Chrome content area starts at screen Y=%d" % top_offset)

# Find the search box
search_info = cdp_eval("""
(function() {
    var input = document.querySelector('input[name="q"], input[type="text"], input[placeholder*="Search"]');
    if (!input) return 'no input found';
    var rect = input.getBoundingClientRect();
    return JSON.stringify({
        tag: input.tagName,
        name: input.name,
        placeholder: input.placeholder,
        type: input.type,
        top: Math.round(rect.top),
        bottom: Math.round(rect.bottom),
        left: Math.round(rect.left),
        right: Math.round(rect.right),
        centerX: Math.round(rect.left + rect.width/2),
        centerY: Math.round(rect.top + rect.height/2),
        width: Math.round(rect.width),
        height: Math.round(rect.height)
    });
})()
""")
print("\nSearch box info: %s" % search_info)

if search_info and search_info != "no input found":
    box = json.loads(search_info)
    # Convert to screen coords
    screen_x = box["centerX"]  # screenX is 0 for maximized window
    screen_y = box["centerY"] + top_offset
    print("Search box at screen: (%d, %d)" % (screen_x, screen_y))

    # Step 1: Click the search box
    print("\n--- Step 1: Click search box ---")
    click_at(screen_x, screen_y)
    time.sleep(0.5)

    # Check if it's focused
    focused = cdp_eval("document.activeElement.tagName + '|name=' + (document.activeElement.name || '') + '|type=' + (document.activeElement.type || '')")
    print("  Active element after click: %s" % focused)

    # Step 2: Type text
    print("\n--- Step 2: Type 'hello world' ---")
    type_string("hello world")
    time.sleep(0.5)

    # Check the value
    value = cdp_eval("document.querySelector('input[name=q]') ? document.querySelector('input[name=q]').value : 'input not found'")
    print("  Input value after typing: '%s'" % value)

    # Step 3: Press Enter
    print("\n--- Step 3: Press Enter ---")
    enter_kc = d.keysym_to_keycode(XK.XK_Return)
    _xtest_fake_input(d, X.KeyPress, enter_kc)
    flush()
    time.sleep(0.01)
    _xtest_fake_input(d, X.KeyRelease, enter_kc)
    flush()
    time.sleep(2)

    # Check URL
    ws.close()
    time.sleep(0.5)
    cdp_json = subprocess.check_output(["curl", "-s", "http://localhost:9222/json"]).decode()
    tabs = json.loads(cdp_json)
    for t in tabs:
        if t.get("type") == "page" and "duckduckgo" in t.get("url", ""):
            print("  Tab URL: %s" % t["url"][:80])
else:
    print("Search box not found!")

print("\nDone.")
