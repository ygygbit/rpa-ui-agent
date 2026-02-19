"""Dump all links from the DuckDuckGo page with their DOM positions."""
import sys, json, subprocess, websocket

cdp_json = subprocess.check_output(["curl", "-s", "http://localhost:9222/json"]).decode()
tabs = json.loads(cdp_json)
ws_url = None
for t in tabs:
    if t.get("type") == "page" and "q=" in t.get("url", ""):
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

# Dump all links
print("=== All visible <a> elements ===")
val = cdp_eval("""
(function() {
    var all = document.querySelectorAll('a');
    var out = [];
    for (var i = 0; i < all.length; i++) {
        var a = all[i];
        var rect = a.getBoundingClientRect();
        if (rect.width < 5 || rect.height < 5) continue;
        if (rect.top < -100 || rect.top > 900) continue;
        var h = a.href || '';
        var t = a.textContent.replace(/\\s+/g, ' ').trim().substring(0, 60);
        out.push(i + '| top=' + Math.round(rect.top) + ' left=' + Math.round(rect.left) + ' w=' + Math.round(rect.width) + ' h=' + Math.round(rect.height) + ' text=' + t + ' || href=' + h.substring(0, 100));
    }
    return out.join('\\n');
})()
""")
print(val or "No links found")

# Also check what the first few result blocks look like
print("\n=== Search result structure ===")
val2 = cdp_eval("""
(function() {
    // Try to find the main results container
    var containers = ['#links', '#web_content_wrapper', '.results', '[data-testid="mainline"]', 'section', 'ol', '.react-results--main'];
    var out = [];
    for (var i = 0; i < containers.length; i++) {
        var el = document.querySelector(containers[i]);
        if (el) {
            out.push('Found: ' + containers[i] + ' children=' + el.children.length);
            // Get first few children
            for (var j = 0; j < Math.min(el.children.length, 3); j++) {
                var child = el.children[j];
                out.push('  child[' + j + ']: tag=' + child.tagName + ' class=' + (child.className || '').substring(0, 50));
                var links = child.querySelectorAll('a');
                for (var k = 0; k < Math.min(links.length, 2); k++) {
                    var rect = links[k].getBoundingClientRect();
                    out.push('    a: text=' + links[k].textContent.replace(/\\s+/g, ' ').trim().substring(0, 50) + ' href=' + (links[k].href || '').substring(0, 80) + ' top=' + Math.round(rect.top));
                }
            }
        }
    }
    if (out.length === 0) out.push('No known containers found');
    return out.join('\\n');
})()
""")
print(val2 or "No structure found")

# Also check body scrollHeight and document title
print("\n=== Page info ===")
val3 = cdp_eval("document.title + ' | scrollH=' + document.body.scrollHeight + ' scrollT=' + document.documentElement.scrollTop")
print(val3 or "No page info")

ws.close()
