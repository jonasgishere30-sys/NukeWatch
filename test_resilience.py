"""Checks the failure paths: retries/backoff, rate-limit detection, stale fallback, and 'insufficient data'.

Run:  python tests/test_resilience.py
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.pop("NUKEWATCH_FIXTURES", None)

from collector import net  # noqa: E402
from collector.tracker import Tracker  # noqa: E402

net.time.sleep = lambda s: None  # don't actually wait during tests
calls = {}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        calls[self.path] = calls.get(self.path, 0) + 1
        n = calls[self.path]
        if self.path == "/flaky":          # 429 twice, then OK
            if n < 3:
                self.send_response(429); self.send_header("Retry-After", "1"); self.end_headers(); self.wfile.write(b"slow down"); return
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}'); return
        if self.path == "/gdelt-limit":    # 200 with GDELT's rate-limit text every time
            self.send_response(200); self.end_headers(); self.wfile.write(b"Please limit requests to one every 5 seconds"); return
        if self.path == "/forbidden":
            self.send_response(403); self.end_headers(); self.wfile.write(b"<html>Access Denied by policy</html>"); return
        self.send_response(404); self.end_headers()


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_port}"
ok = True


def check(cond, label):
    global ok
    print(("PASS " if cond else "FAIL ") + label)
    ok &= bool(cond)


# 1. retries recover from 429
body = net.fetch(base + "/flaky", attempts=3)
check(body == '{"ok":true}' and calls["/flaky"] == 3, "retries 429 twice, then succeeds on the 3rd attempt")

# 2. GDELT-style rate limit inside a 200 response is detected, retried and reported
try:
    net.fetch(base + "/gdelt-limit", attempts=3, rate_limit_markers=("please limit requests",))
    check(False, "GDELT rate-limit text raises")
except net.FetchError as e:
    check(calls["/gdelt-limit"] == 3 and "rate limited" in str(e) and "3 attempts" in str(e), "GDELT rate-limit text is retried and reported: " + str(e)[:80])

# 3. 403 is not retried and the error keeps the status + body text
try:
    net.fetch(base + "/forbidden", attempts=3)
except net.FetchError as e:
    check(calls["/forbidden"] == 1 and e.status == 403 and "Access Denied" in str(e), "403 fails fast with status and body: " + str(e)[:80])

# 4. tracker: live ok → cached → stale on failure → failed when no cache
tmp = tempfile.mkdtemp()
tr = Tracker(tmp)
v = tr.get("src", lambda: [1, 2, 3])
check(v == [1, 2, 3] and tr.state("src") == "ok", "first fetch is live 'ok'")
tr2 = Tracker(tmp)
v = tr2.get("src", lambda: (_ for _ in ()).throw(net.FetchError("HTTP 503 down", 503)), ttl_min=0)
check(v == [1, 2, 3] and tr2.state("src") == "stale" and "503" in tr2.status["src"]["error"], "failure falls back to last good result, marked stale with the error")
v = tr2.get("never", lambda: (_ for _ in ()).throw(net.FetchError("HTTP 500", 500)))
check(v is None and tr2.state("never") == "failed", "failure with no cache is 'failed' and returns None (not an empty list)")
v = tr2.get("nokey", lambda: (_ for _ in ()).throw(net.NotConfigured("needs a key")))
check(v is None and tr2.state("nokey") == "not_configured" and "nokey" not in tr2.errors(), "missing key is 'not_configured', not counted as an error")
shutil.rmtree(tmp)

# 5. full scan with every source down → insufficient data, no crash, no fake score
work = pathlib.Path(tempfile.mkdtemp())
shutil.copytree(ROOT / "collector", work / "collector")
empty = work / "empty_fixtures"
empty.mkdir()
env = dict(os.environ, NUKEWATCH_FIXTURES=str(empty))
r = subprocess.run([sys.executable, "-m", "collector.run"], cwd=work, env=env, capture_output=True, text=True)
d = json.loads((work / "data/latest.json").read_text()) if r.returncode == 0 else {}
check(r.returncode == 0, "scan survives every source failing")
check(d.get("insufficient") is True and d.get("score") is None and d.get("level_name") == "INSUFFICIENT DATA",
      "index reports INSUFFICIENT DATA instead of a low score")
check(all(f["rung"] is None and f["rung_name"] == "No data" for f in d.get("flashpoints", [])), "flashpoints without news show 'No data', not rung 1")
check(len(d.get("errors", {})) > 20 and all(d["errors"].values()), "every failed source is listed with its error message")
shutil.rmtree(work)

srv.shutdown()
print("\nALL PASSED" if ok else "\nSOME CHECKS FAILED")
sys.exit(0 if ok else 1)
