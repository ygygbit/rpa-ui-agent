"""Test: Click a DuckDuckGo link and verify navigation happens."""
import sys, json, subprocess, time, websocket

from Xlib.display import Display
from Xlib import X
from Xlib.ext.xtest import fake_input as _xtest_fake_input

d = Display(":99")
root = d.screen().root

def flush():
    d.flush()
    d.sync()

def click_at(x, y):
    """XTEST click at screen coordinates."""
    _xtest_fake_input(d, X.MotionNotify, x=x, y=y)
    flush()
    time.sleep(0.1)
    # Verify cursor
    ptr = root.query_pointer()
    print("  Cursor: (%d, %d) target: (%d, %d)" % (ptr.root_x, ptr.root_y, x, y))
    _xtest_fake_input(d, X.ButtonPress, 1)
    flush()
    time.sleep(0.1)  # 100ms hold
    _xtest_fake_input(d, X.ButtonRelease, 1)
    flush()
    time.sleep(0.1)

# Connect to CDP
cdp_json = subprocess.check_output(["curl", "-s", "http://localhost:9222/json"]).decode()
tabs = json.loads(cdp_json)
ws_url = None
for t in tabs:
    if t.get("type") == "page" and "q=" in t.get("url", ""):
        ws_url = t["webSocketDebuggerUrl"]
        break

ws = websocket.create_connection(ws_url, timeout=5)

def cdp_eval(expr):
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": expr}}))
    while True:
        r = json.loads(ws.recv())
        if "id" in r:
            return r.get("result", {}).get("result", {}).get("value")

# Get viewport info
vp = json.loads(cdp_eval("""JSON.stringify({
    innerWidth: window.innerWidth, innerHeight: window.innerHeight,
    outerWidth: window.outerWidth, outerHeight: window.outerHeight,
    screenX: window.screenX, screenY: window.screenY
})""") or "{}")
top_offset = vp.get("screenY", 0) + (vp.get("outerHeight", 0) - vp.get("innerHeight", 0))
left_offset = vp.get("screenX", 0)  # left border is minimal, ~4px
print("Viewport: %s" % json.dumps(vp))
print("Chrome content starts at screen Y=%d" % top_offset)

# Install event listener (no preventDefault this time)
cdp_eval("""
window.__events = [];
document.addEventListener('click', function(e) {
    window.__events.push({
        type: 'click', x: e.clientX, y: e.clientY,
        tag: e.target.tagName,
        text: (e.target.textContent || '').substring(0, 40),
        href: e.target.href || (e.target.closest && e.target.closest('a') ? e.target.closest('a').href : 'none'),
        isTrusted: e.isTrusted,
        defaultPrevented: e.defaultPrevented
    });
}, true);
'ok'
""")

# Get URL before click
url_before = cdp_eval("window.location.href")
print("\nURL before: %s" % url_before)

# The ad link "Test Any App or Technology" is at viewport (168, 207)
# After DuckDuckGo reload the layout may differ. Let me find the exact position fresh.
link_info = cdp_eval("""
(function() {
    var ol = document.querySelector('ol');
    if (!ol) return 'no ol found';
    var items = ol.querySelectorAll('li');
    var results = [];
    for (var i = 0; i < Math.min(items.length, 5); i++) {
        var links = items[i].querySelectorAll('a');
        for (var j = 0; j < links.length; j++) {
            var rect = links[j].getBoundingClientRect();
            if (rect.top > 0 && rect.top < 900 && rect.width > 50) {
                results.push({
                    text: links[j].textContent.replace(/\\s+/g, ' ').trim().substring(0, 60),
                    href: (links[j].href || '').substring(0, 100),
                    vpX: Math.round(rect.left + rect.width/2),
                    vpY: Math.round(rect.top + rect.height/2)
                });
            }
        }
    }
    return JSON.stringify(results);
})()
""")
result_links = json.loads(link_info or "[]")
print("\nSearch result links:")
for i, rl in enumerate(result_links[:8]):
    sx = rl["vpX"] + left_offset
    sy = rl["vpY"] + top_offset
    print("  %d: '%s' vp=(%d,%d) screen=(%d,%d)" % (i, rl["text"][:50], rl["vpX"], rl["vpY"], sx, sy))
    print("     href=%s" % rl["href"][:80])

# Click the first one (Tricentis ad title)
if result_links:
    target = result_links[1] if len(result_links) > 1 else result_links[0]  # Pick the title link
    sx = target["vpX"] + left_offset
    sy = target["vpY"] + top_offset
    print("\n>>> Clicking: '%s' at screen (%d, %d)" % (target["text"][:40], sx, sy))
    click_at(sx, sy)

    # Wait for navigation
    time.sleep(2.0)

    # Check events (may fail if page navigated away)
    try:
        events_str = cdp_eval("JSON.stringify(window.__events || [])")
        events = json.loads(events_str or "[]")
        print("\nCaptured %d events:" % len(events))
        for ev in events:
            print("  %s" % json.dumps(ev))
    except:
        print("\nCDP eval failed (page may have navigated)")

    # Check URL after
    try:
        url_after = cdp_eval("window.location.href")
        print("\nURL after: %s" % url_after)
        if url_after != url_before:
            print("*** NAVIGATION SUCCESSFUL! ***")
        else:
            print("*** NO NAVIGATION ***")
    except:
        print("\nCDP eval failed - checking if tab changed...")
        ws.close()
        # Re-check tabs
        cdp_json2 = subprocess.check_output(["curl", "-s", "http://localhost:9222/json"]).decode()
        tabs2 = json.loads(cdp_json2)
        for t2 in tabs2:
            if t2.get("type") == "page":
                print("  Tab: %s" % t2.get("url", "?")[:80])
else:
    print("No links found to click")

print("\nDone.")
