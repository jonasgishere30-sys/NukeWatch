import functools
import json
import pathlib
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from playwright.sync_api import sync_playwright

root = pathlib.Path(sys.argv[1]).resolve()
data = json.loads((root / "data/latest.json").read_text())
server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(SimpleHTTPRequestHandler, directory=str(root)))
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{server.server_port}/"
output = pathlib.Path("test-results")
output.mkdir(exist_ok=True)
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for label, width in (("desktop", 1440), ("mobile", 390)):
                page = browser.new_page(viewport={"width": width, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("https://server.arcgisonline.com/**", lambda route: route.abort())
                page.route("https://fonts.googleapis.com/**", lambda route: route.abort())
                page.route("https://fonts.gstatic.com/**", lambda route: route.abort())
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_function("document.getElementById('score').textContent !== '–'", timeout=30000)
                page.wait_for_function("document.querySelectorAll('.leaflet-overlay-pane path').length >= 177", timeout=30000)
                assert page.locator("#score").inner_text() == str(data["score"])
                assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(11, 11, 11)"
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert page.locator("#error-bar").is_hidden()
                for section in ("topics", "markets", "attention", "statements", "seismic"):
                    assert page.locator("#" + section).inner_text().strip(), section
                for path in ("assets/style.css", "assets/app.js", "countries.geojson", "data/latest.json"):
                    response = page.request.get(url + path)
                    assert response.status == 200, (path, response.status)
                page.screenshot(path=str(output / (label + ".png")), full_page=True)
                assert not errors, errors
                page.close()
        finally:
            browser.close()
finally:
    server.shutdown()
    server.server_close()
print("Desktop/mobile styling, dashboard rendering, local assets, and real Leaflet country polygons passed. External tile availability was not tested.")
