"""Fetchers for each live data source. Standard library only.

Every fetcher returns plain dicts/lists and never raises: on failure it returns
an empty result plus an error string, so one broken source never stops a scan.

Set NUKEWATCH_FIXTURES=<folder> to read saved responses instead of the network
(used by the offline test).
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

from . import config

FIXTURES = os.environ.get("NUKEWATCH_FIXTURES")
_last_gdelt = [0.0]


def _get(url, name, headers=None, data=None, timeout=30):
    """HTTP GET/POST returning text. `name` is the fixture file used offline."""
    if FIXTURES:
        path = os.path.join(FIXTURES, name)
        if not os.path.exists(path):
            raise IOError("no fixture " + name)
        with open(path, encoding="utf-8") as f:
            return f.read()
    h = {"User-Agent": config.USER_AGENT, "Accept": "*/*"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _now():
    return datetime.now(timezone.utc)


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:60]


# ---------------------------------------------------------------- GDELT news
def _gdelt(params, name):
    """GDELT allows about one request every 5 seconds."""
    if not FIXTURES:
        wait = 5.5 - (time.time() - _last_gdelt[0])
        if wait > 0:
            time.sleep(wait)
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode(params)
    try:
        text = _get(url, name)
    finally:
        _last_gdelt[0] = time.time()
    text = text.strip()
    if not text.startswith("{"):
        raise ValueError("GDELT: " + text[:120])
    return json.loads(text)


def gdelt_articles(query, timespan="24h", maxrecords=75, english=True):
    q = query + (" sourcelang:english" if english else "")
    try:
        js = _gdelt({"query": q, "mode": "ArtList", "format": "json", "maxrecords": maxrecords,
                     "timespan": timespan, "sort": "DateDesc"}, "gdelt_art_" + _slug(query) + ".json")
    except Exception as e:  # noqa: BLE001
        return [], str(e)
    out, seen = [], set()
    for a in js.get("articles", []) or []:
        title = (a.get("title") or "").strip()
        key = title.lower()[:80]
        if not title or key in seen:
            continue
        seen.add(key)
        out.append({
            "title": title,
            "url": a.get("url"),
            "image": a.get("socialimage") or None,
            "source": a.get("domain"),
            "country": a.get("sourcecountry"),
            "time": _gdelt_time(a.get("seendate")),
        })
    return out, None


def gdelt_volume(query, timespan="7d", english=True):
    """Returns (last_24h_count, daily_average_over_previous_days) from GDELT's volume timeline."""
    q = query + (" sourcelang:english" if english else "")
    try:
        js = _gdelt({"query": q, "mode": "TimelineVolRaw", "format": "json", "timespan": timespan},
                    "gdelt_vol_" + _slug(query) + ".json")
        data = js["timeline"][0]["data"]
    except Exception as e:  # noqa: BLE001
        return None, None, str(e)
    cutoff = _now() - timedelta(hours=24)
    last, prev = 0, 0
    first = None
    for p in data:
        t = _gdelt_time(p.get("date"))
        if not t:
            continue
        dt = datetime.fromisoformat(t)
        first = first or dt
        if dt >= cutoff:
            last += p.get("value", 0)
        else:
            prev += p.get("value", 0)
    days_prev = max(1.0, (cutoff - first).total_seconds() / 86400) if first else 1.0
    return last, prev / days_prev, None


def _gdelt_time(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return None


# ------------------------------------------------------- Military aircraft
def military_aircraft():
    """ADS-B military feeds (readsb format). Tries airplanes.live, then adsb.fi."""
    errors = []
    for name, url in (("airplanes_live_mil.json", "https://api.airplanes.live/v2/mil"),
                      ("adsbfi_mil.json", "https://opendata.adsb.fi/api/v2/mil")):
        try:
            js = json.loads(_get(url, name))
            return js.get("ac") or js.get("aircraft") or [], url.split("/")[2], None
        except Exception as e:  # noqa: BLE001
            errors.append(f"{url.split('/')[2]}: {e}")
    return [], None, "; ".join(errors)


def classify_aircraft(raw):
    out = []
    for a in raw:
        t = (a.get("t") or "").upper()
        for cat, types in config.AIRCRAFT_TYPES.items():
            if t in types and a.get("lat") is not None and a.get("lon") is not None:
                alt = a.get("alt_baro")
                out.append({
                    "hex": a.get("hex"),
                    "callsign": (a.get("flight") or "").strip() or a.get("r") or a.get("hex"),
                    "reg": a.get("r"),
                    "type": types[t],
                    "code": t,
                    "category": cat,
                    "lat": round(a["lat"], 3),
                    "lon": round(a["lon"], 3),
                    "alt": alt if isinstance(alt, (int, float)) else None,
                    "ground": alt == "ground",
                    "speed": round(a["gs"]) if isinstance(a.get("gs"), (int, float)) else None,
                    "track": round(a["track"]) if isinstance(a.get("track"), (int, float)) else None,
                    "seen": a.get("seen"),
                })
                break
    return out


# ------------------------------------------------- State Dept travel advisories
def travel_advisories():
    try:
        root = ET.fromstring(_get("https://travel.state.gov/_res/rss/TAsTWs.xml", "travel_advisories.xml"))
    except Exception as e:  # noqa: BLE001
        return [], str(e)
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        desc = re.sub(r"<[^>]+>", " ", item.findtext("description") or "")
        m = re.search(r"Level\s*(\d)", title)
        pub = item.findtext("pubDate")
        try:
            when = datetime.strptime(pub.strip()[:25], "%a, %d %b %Y %H:%M:%S").replace(tzinfo=timezone.utc).isoformat()
        except Exception:  # noqa: BLE001
            when = None
        out.append({
            "country": title.split(" - ")[0].strip(),
            "title": title,
            "level": int(m.group(1)) if m else None,
            "ordered_departure": bool(re.search(r"ordered departure", desc, re.I)),
            "url": item.findtext("link"),
            "time": when,
        })
    return out, None


# --------------------------------------------------------------- Bluesky
def bluesky_search(query, limit=100):
    """Uses an app password if BSKY_HANDLE / BSKY_APP_PASSWORD are set (recommended)."""
    headers, base = {}, "https://public.api.bsky.app"
    handle, pw = os.environ.get("BSKY_HANDLE"), os.environ.get("BSKY_APP_PASSWORD")
    try:
        if handle and pw and not FIXTURES:
            body = json.dumps({"identifier": handle, "password": pw}).encode()
            sess = json.loads(_get("https://bsky.social/xrpc/com.atproto.server.createSession", "bsky_session.json",
                                   headers={"Content-Type": "application/json"}, data=body))
            headers["Authorization"] = "Bearer " + sess["accessJwt"]
            base = "https://bsky.social"
        url = base + "/xrpc/app.bsky.feed.searchPosts?" + urllib.parse.urlencode({"q": query, "limit": limit, "sort": "latest"})
        js = json.loads(_get(url, "bsky_" + _slug(query) + ".json", headers=headers))
    except Exception as e:  # noqa: BLE001
        return [], str(e)
    out = []
    for p in js.get("posts", []):
        rec = p.get("record") or {}
        author = p.get("author") or {}
        rkey = (p.get("uri") or "").rsplit("/", 1)[-1]
        out.append({
            "platform": "Bluesky",
            "text": (rec.get("text") or "")[:300],
            "author": author.get("handle"),
            "time": rec.get("createdAt"),
            "likes": p.get("likeCount", 0),
            "reposts": p.get("repostCount", 0),
            "url": f"https://bsky.app/profile/{author.get('handle')}/post/{rkey}",
        })
    return out, None


# ---------------------------------------------------------------- Reddit
def reddit_new(sub):
    try:
        js = json.loads(_get(f"https://www.reddit.com/r/{sub}/new.json?limit=100", f"reddit_{sub}.json"))
    except Exception as e:  # noqa: BLE001
        return [], str(e)
    out = []
    for c in js.get("data", {}).get("children", []):
        d = c.get("data", {})
        out.append({
            "platform": "Reddit",
            "text": d.get("title", ""),
            "author": "r/" + sub,
            "time": datetime.fromtimestamp(d.get("created_utc", 0), timezone.utc).isoformat(),
            "likes": d.get("score", 0),
            "reposts": d.get("num_comments", 0),
            "url": "https://www.reddit.com" + d.get("permalink", ""),
        })
    return out, None
