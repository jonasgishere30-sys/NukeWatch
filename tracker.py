"""Per-source status + cache with stale fallback.

Each source is fetched through `Tracker.get(...)`:
  * fresh cache (younger than ttl) is reused, so slow-changing data is not requested every 15 minutes;
  * a live fetch that succeeds is saved;
  * a live fetch that fails falls back to the last good result if it is not too old ("stale");
  * otherwise the source is "failed" and the value is None, never an empty list pretending nothing happened.

The cache lives in data/cache/, which the deploy workflow already preserves between runs.
"""
import json
import os
import re
from datetime import datetime, timezone

from .net import FetchError, NotConfigured

STATES = ("ok", "cached", "stale", "failed", "not_configured", "skipped")


def _now():
    return datetime.now(timezone.utc)


class Tracker:
    def __init__(self, cache_dir, use_cache=True):
        self.dir = cache_dir
        self.use_cache = use_cache
        self.status = {}
        os.makedirs(cache_dir, exist_ok=True)

    def _path(self, key):
        return os.path.join(self.dir, re.sub(r"[^A-Za-z0-9_.-]+", "_", key)[:120] + ".json")

    def _load(self, key):
        if not self.use_cache:
            return None
        try:
            with open(self._path(key), encoding="utf-8") as f:
                c = json.load(f)
            c["age_min"] = round((_now() - datetime.fromisoformat(c["saved_at"])).total_seconds() / 60)
            return c
        except (OSError, ValueError, KeyError):
            return None

    def _save(self, key, value):
        if not self.use_cache:
            return
        tmp = self._path(key) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"saved_at": _now().isoformat(), "value": value}, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, self._path(key))

    def get(self, name, fn, ttl_min=0, max_stale_min=24 * 60, essential=False, allow_live=True):
        """fn() returns the value or raises FetchError / NotConfigured / any Exception."""
        cached = self._load(name)
        if cached and cached["age_min"] < ttl_min:
            self.status[name] = {"state": "cached", "age_min": cached["age_min"], "essential": essential,
                                 "last_ok": cached["saved_at"]}
            return cached["value"]
        if not allow_live:
            return self._fallback(name, cached, "skipped: request budget for this scan was used up", essential, max_stale_min, "skipped")
        try:
            value = fn()
        except NotConfigured as e:
            self.status[name] = {"state": "not_configured", "note": str(e), "essential": essential}
            return None
        except FetchError as e:
            return self._fallback(name, cached, str(e), essential, max_stale_min, http=e.status)
        except Exception as e:  # noqa: BLE001  (parser errors: the response format changed)
            return self._fallback(name, cached, f"could not read response ({type(e).__name__}: {e})", essential, max_stale_min)
        self._save(name, value)
        self.status[name] = {"state": "ok", "age_min": 0, "essential": essential, "last_ok": _now().isoformat()}
        return value

    def _fallback(self, name, cached, error, essential, max_stale_min, state_if_none="failed", http=None):
        if cached and cached["age_min"] <= max_stale_min:
            self.status[name] = {"state": "stale", "age_min": cached["age_min"], "error": error, "http": http,
                                 "essential": essential, "last_ok": cached["saved_at"]}
            return cached["value"]
        self.status[name] = {"state": state_if_none, "error": error, "http": http, "essential": essential,
                             "last_ok": cached["saved_at"] if cached else None}
        return None

    def state(self, name):
        return (self.status.get(name) or {}).get("state")

    def has_data(self, name):
        return self.state(name) in ("ok", "cached", "stale")

    def errors(self):
        """Only real failures (failed / stale), with their messages."""
        return {k: v.get("error") for k, v in self.status.items() if v["state"] in ("failed", "stale")}
