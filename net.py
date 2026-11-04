"""Shared HTTP helper: retries with increasing waits, Retry-After support, and errors that say what happened.

Every failure becomes a FetchError whose message includes the HTTP status (if any) and the first part of
the response body, so the dashboard's diagnostics show the real reason instead of just a source name.
"""
import os
import random
import socket
import time
import urllib.error
import urllib.request

from . import config

FIXTURES = os.environ.get("NUKEWATCH_FIXTURES")
RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 524}


class FetchError(Exception):
    def __init__(self, message, status=None, retryable=False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class NotConfigured(Exception):
    """A source that needs a key or account that has not been set up. Not counted as a failure."""


def _snippet(body):
    text = " ".join((body or "").split())
    return text[:180] + ("…" if len(text) > 180 else "")


def fetch(url, fixture=None, headers=None, data=None, timeout=30, attempts=3, base_delay=4.0,
          rate_limit_markers=(), max_delay=60):
    """GET (or POST when data is given) and return the body as text.

    Retries timeouts, connection errors, 429 and 5xx with exponential backoff plus jitter.
    `rate_limit_markers`: phrases in a 200 response that really mean "slow down" (GDELT does this).
    """
    if FIXTURES:
        path = os.path.join(FIXTURES, fixture or "")
        if not fixture or not os.path.exists(path):
            raise FetchError("no fixture file " + str(fixture))
        with open(path, encoding="utf-8") as f:
            return f.read()

    h = {"User-Agent": config.USER_AGENT, "Accept": "*/*", "Accept-Language": "en"}
    if headers:
        h.update(headers)
    last = None
    for attempt in range(1, attempts + 1):
        wait = None
        try:
            req = urllib.request.Request(url, headers=h, data=data)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", errors="replace")
            low = body[:400].lower()
            if any(m in low for m in rate_limit_markers):
                last = FetchError("rate limited: " + _snippet(body), 429, True)
            else:
                return body
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                body = ""
            retryable = e.code in RETRY_STATUSES
            last = FetchError(f"HTTP {e.code} {e.reason}: {_snippet(body)}".strip(), e.code, retryable)
            ra = e.headers.get("Retry-After") if e.headers else None
            if ra and ra.strip().isdigit():
                wait = min(int(ra), max_delay)
        except (socket.timeout, TimeoutError) as e:
            last = FetchError(f"timed out after {timeout}s ({e})", None, True)
        except urllib.error.URLError as e:
            last = FetchError(f"connection failed: {e.reason}", None, True)
        except Exception as e:  # noqa: BLE001
            last = FetchError(f"{type(e).__name__}: {e}", None, False)
        if not last.retryable or attempt == attempts:
            break
        delay = wait if wait is not None else min(max_delay, base_delay * (2 ** (attempt - 1)))
        time.sleep(delay + random.uniform(0, 1.5))
    attempts_note = f" (after {attempt} attempt{'s' if attempt > 1 else ''})"
    raise FetchError(str(last) + attempts_note, last.status, last.retryable)
