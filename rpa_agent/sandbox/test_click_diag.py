"""Diagnostic: Test what happens when we XTEST-click on a Chrome link."""
import sys
sys.path.insert(0, "/app/rpa_agent/sandbox")
sys.path.insert(0, "/app")

import time
import json
import subprocess

from Xlib.display import Display
from Xlib import X, XK
from Xlib.ext.xtest import fake_input as _xtest_fake_input

display_str = ":99"
d = Display(display_str)
root = d.screen().root

def flush():
    d.flush()
    d.sync()

def move_to(x, y):
    _xtest_fake_input(d, X.MotionNotify, x=x, y=y)
    flush()

def get_cursor():
    ptr = root.query_pointer()
    return ptr.root_x, ptr.root_y

def click_at(x, y, hold_time=0.08):
    move_to(x, y)
    time.sleep(0.1)
    cx, cy = get_cursor()
    print("  Cursor after move: (%d, %d) target: (%d, %d)" % (cx, cy, x, y))
    _xtest_fake_input(d, X.ButtonPress, 1)
    flush()
    time.sleep(hold_time)
    _xtest_fake_input(d, X.ButtonRelease, 1)
    flush()
    time.sleep(0.1)

import websocket

cdp_json = subprocess.check_output(["curl", "-s", "http://localhost:9222/json"]).decode()
tabs = json.loads(cdp_json)
ws_url = None
for tab in tabs:
    title = tab.get("title", "").lower()
    url = tab.get("url", "").lower()
    if tab.get("type") == "page" and "duckduckgo" in url and "q=" in url:
        ws_url = tab["webSocketDebuggerUrl"]
        print("Found tab: %s" % tab.get("title", ""))
        break

if not ws_url:
    print("ERROR: Could not find DDG search results tab")
    print("Available tabs:")
    for t in tabs:
        print("  %s: %s" % (t.get("type", "?"), t.get("url", "?")[:80]))
    sys.exit(1)

print("Connecting to CDP: " + ws_url)
ws = websocket.create_connection(ws_url, timeout=5)
msg_id = 1

def cdp_send(method, params=None):
    global msg_id
    msg = {"id": msg_id, "method": method}
    if params:
        msg["params"] = params
    ws.send(json.dumps(msg))
    msg_id += 1
    target_id = msg_id - 1
    while True:
        raw = ws.recv()
        result = json.loads(raw)
        if "id" in result and result["id"] == target_id:
            return result

def cdp_eval(expression):
    """Evaluate JS and return the value."""
    result = cdp_send("Runtime.evaluate", {"expression": expression})
    inner = result.get("result", {}).get("result", {})
    return inner.get("value")

# Step 1: Get viewport info
print("\n--- Step 1: Get Chrome viewport offset ---")
viewport_str = cdp_eval("""JSON.stringify({
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
    outerWidth: window.outerWidth,
    outerHeight: window.outerHeight,
    screenX: window.screenX,
    screenY: window.screenY,
    devicePixelRatio: window.devicePixelRatio
})""")
viewport = json.loads(viewport_str or "{}")
print("  Viewport: " + json.dumps(viewport, indent=2))

chrome_top_offset = viewport.get("screenY", 0) + (viewport.get("outerHeight", 0) - viewport.get("innerHeight", 0))
chrome_left_offset = viewport.get("screenX", 0) + (viewport.get("outerWidth", 0) - viewport.get("innerWidth", 0))
print("  Chrome content area starts at screen Y = %d, X = %d" % (chrome_top_offset, chrome_left_offset))

# Step 2: Find all visible links with bounding rects
print("\n--- Step 2: Find link elements and their positions ---")
links_str = cdp_eval("""
(function() {
    var all = document.querySelectorAll('a');
    var results = [];
    for (var i = 0; i < all.length; i++) {
        var rect = all[i].getBoundingClientRect();
        if (rect.width > 10 && rect.height > 5 && rect.top > 0 && rect.top < 800) {
            results.push({
                text: all[i].textContent.replace(/\\s+/g, ' ').trim().substring(0, 80),
                href: all[i].href.substring(0, 120),
                top: Math.round(rect.top),
                bottom: Math.round(rect.bottom),
                left: Math.round(rect.left),
                right: Math.round(rect.right),
                centerX: Math.round(rect.left + rect.width/2),
                centerY: Math.round(rect.top + rect.height/2)
            });
        }
    }
    return JSON.stringify(results);
})()
""")
links = json.loads(links_str or "[]")
print("  Found %d visible links:" % len(links))
for i, link in enumerate(links[:10]):
    print("  Link %d: text='%s'" % (i, link.get("text", "?")[:60]))
    print("    href=%s" % link.get("href", "?")[:80])
    print("    viewport: top=%d bottom=%d left=%d right=%d center=(%d,%d)" % (
        link.get("top", 0), link.get("bottom", 0),
        link.get("left", 0), link.get("right", 0),
        link.get("centerX", 0), link.get("centerY", 0)
    ))
    # Calculate screen coords
    sx = link["centerX"] + chrome_left_offset
    sy = link["centerY"] + chrome_top_offset
    print("    screen coords: (%d, %d)" % (sx, sy))

# Step 3: Add click event listeners
print("\n--- Step 3: Add click event listener ---")
listener_result = cdp_eval("""
window.__clicked_events = [];
document.addEventListener('mousedown', function(e) {
    window.__clicked_events.push({
        type: 'mousedown', x: e.clientX, y: e.clientY,
        target: e.target.tagName,
        isTrusted: e.isTrusted
    });
}, true);
document.addEventListener('mouseup', function(e) {
    window.__clicked_events.push({
        type: 'mouseup', x: e.clientX, y: e.clientY,
        isTrusted: e.isTrusted
    });
}, true);
document.addEventListener('click', function(e) {
    window.__clicked_events.push({
        type: 'click', x: e.clientX, y: e.clientY,
        target: e.target.tagName + '|' + (e.target.className || '').substring(0, 30),
        href: e.target.href || (e.target.closest && e.target.closest('a') ? e.target.closest('a').href : 'none'),
        isTrusted: e.isTrusted
    });
}, true);
'listeners_installed'
""")
print("  Result: %s" % listener_result)

# Step 4: Find a real search result link (not DDG internal) and click it
print("\n--- Step 4: Click a search result link ---")
target_link = None
for link in links:
    href = link.get("href", "")
    # Skip DuckDuckGo internal links - we want external result links
    if "duckduckgo.com" in href or not href:
        continue
    target_link = link
    break

# If no external link found, list what we have and try broader search
if not target_link:
    print("  No external links found in first 13 results")
    print("  Trying to find result links with different selectors...")
    deeper_str = cdp_eval("""
    (function() {
        // DuckDuckGo result links often have data-testid or specific classes
        var selectors = ['a[href]:not([href*="duckduckgo"])', 'article a', '[data-result] a', 'h2 a', '.result a'];
        var results = [];
        for (var s = 0; s < selectors.length; s++) {
            var links = document.querySelectorAll(selectors[s]);
            for (var i = 0; i < links.length; i++) {
                var rect = links[i].getBoundingClientRect();
                if (rect.width > 10 && rect.height > 5 && rect.top > 100 && rect.top < 800) {
                    results.push({
                        selector: selectors[s],
                        text: links[i].textContent.replace(/\\s+/g, ' ').trim().substring(0, 80),
                        href: links[i].href.substring(0, 120),
                        top: Math.round(rect.top),
                        centerX: Math.round(rect.left + rect.width/2),
                        centerY: Math.round(rect.top + rect.height/2)
                    });
                }
            }
        }
        return JSON.stringify(results);
    })()
    """)
    deeper_links = json.loads(deeper_str or "[]")
    print("  Found %d deeper links:" % len(deeper_links))
    for i, dl in enumerate(deeper_links[:15]):
        print("    [%s] '%s' href=%s center=(%d,%d)" % (
            dl.get("selector", "?"), dl.get("text", "?")[:50],
            dl.get("href", "?")[:60], dl.get("centerX", 0), dl.get("centerY", 0)
        ))
    # Pick first external link
    for dl in deeper_links:
        if "duckduckgo.com" not in dl.get("href", ""):
            target_link = dl
            break

if target_link:
    # Convert viewport coordinates to screen coordinates
    screen_x = target_link["centerX"] + chrome_left_offset
    screen_y = target_link["centerY"] + chrome_top_offset
    print("  Target: '%s'" % target_link.get("text", "?")[:60])
    print("  Viewport pos: (%d, %d)" % (target_link["centerX"], target_link["centerY"]))
    print("  Screen pos: (%d, %d)" % (screen_x, screen_y))

    click_at(screen_x, screen_y, hold_time=0.1)
    time.sleep(1.0)

    # Check events
    print("\n--- Step 5: Check captured events ---")
    events_str = cdp_eval("JSON.stringify(window.__clicked_events)")
    events = json.loads(events_str or "[]")
    print("  Captured %d events:" % len(events))
    for ev in events:
        print("    %s" % json.dumps(ev))

    # Check URL
    current_url = cdp_eval("window.location.href")
    print("\n  Current URL: %s" % current_url)
else:
    print("  No suitable link found to click")
    print("  Links available: %d" % len(links))

ws.close()
print("\nDone.")
