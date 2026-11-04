"""Fetchers for every outside data source. Standard library only.

Rules:
  * A fetcher returns real data or RAISES. It never returns an empty list to mean "it failed".
    (An empty list means the service answered and there was genuinely nothing.)
  * Errors are FetchError (network/HTTP, with status + response text) or NotConfigured (needs a key).
  * Set NUKEWATCH_FIXTURES=<folder> to read saved responses instead of the network (offline tests).
"""
import csv
import html as _html
import io
import json
import math
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

from . import config
from .net import FIXTURES, FetchError, NotConfigured, fetch


def _now():
    return datetime.now(timezone.utc)


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:60]


def _json(text, what):
    try:
        return json.loads(text)
    except ValueError:
        raise FetchError(f"{what} did not return JSON: " + " ".join(text.split())[:180])


# ===================================================================== GDELT
# GDELT asks for at most one request every 5 seconds and throttles shared cloud IPs (like GitHub's) harder.
# So: space requests, retry with backoff, cap requests per scan, and let the cache serve slow-changing data.
_gstate = {"last": 0.0, "used": 0}
GDELT_MARKERS = ("please limit requests", "limit requests to one every", "too many requests")


def gdelt_budget_left():
    return FIXTURES is not None or _gstate["used"] < config.GDELT_MAX_REQUESTS


def _gdelt(params, fixture):
    if not FIXTURES:
        wait = config.GDELT_SPACING_S - (time.time() - _gstate["last"])
        if wait > 0:
            time.sleep(wait)
    _gstate["used"] += 1
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode(params)
    try:
        text = fetch(url, fixture, timeout=45, attempts=3, base_delay=12, rate_limit_markers=GDELT_MARKERS, max_delay=60)
    finally:
        _gstate["last"] = time.time()
    text = text.strip()
    if not text:
        return {}
    if not text.startswith("{"):
        # GDELT answers bad queries with HTTP 200 and a plain-text explanation.
        raise FetchError("GDELT rejected the query: " + " ".join(text.split())[:200])
    return json.loads(text)


def _gtime(s):
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def gdelt_articles(query, timespan="24h", maxrecords=75, english=True):
    q = query + (" sourcelang:english" if english else "")
    js = _gdelt({"query": q, "mode": "ArtList", "format": "json", "maxrecords": maxrecords,
                 "timespan": timespan, "sort": "DateDesc"}, "gdelt_art_" + _slug(query) + ".json")
    out, seen = [], set()
    for a in js.get("articles", []) or []:
        title = (a.get("title") or "").strip()
        key = title.lower()[:80]
        if not title or key in seen:
            continue
        seen.add(key)
        out.append({"title": title, "url": a.get("url"), "image": a.get("socialimage") or None,
                    "source": a.get("domain"), "country": a.get("sourcecountry"), "time": _gtime(a.get("seendate"))})
    return out


def gdelt_volume(query, timespan="7d", english=True):
    """{'last24': n, 'daily_avg': x} from GDELT's raw volume timeline."""
    q = query + (" sourcelang:english" if english else "")
    js = _gdelt({"query": q, "mode": "TimelineVolRaw", "format": "json", "timespan": timespan},
                "gdelt_vol_" + _slug(query) + ".json")
    tl = js.get("timeline") or []
    data = tl[0].get("data", []) if tl else []
    cutoff = _now() - timedelta(hours=24)
    last = prev = 0
    first = None
    for p in data:
        t = _gtime(p.get("date"))
        if not t:
            continue
        dt = datetime.fromisoformat(t)
        first = first or dt
        if dt >= cutoff:
            last += p.get("value", 0)
        else:
            prev += p.get("value", 0)
    days_prev = max(1.0, (cutoff - first).total_seconds() / 86400) if first else 1.0
    return {"last24": last, "daily_avg": round(prev / days_prev, 2)}


# ============================================================ Military aircraft
def military_aircraft():
    errors = []
    for fixture, url in (("airplanes_live_mil.json", "https://api.airplanes.live/v2/mil"),
                         ("adsbfi_mil.json", "https://opendata.adsb.fi/api/v2/mil")):
        try:
            js = _json(fetch(url, fixture, attempts=2), url.split("/")[2])
            return {"feed": url.split("/")[2], "ac": js.get("ac") or js.get("aircraft") or []}
        except FetchError as e:
            errors.append(f"{url.split('/')[2]}: {e}")
    raise FetchError(" | ".join(errors))


def classify_aircraft(raw):
    out = []
    for a in raw:
        t = (a.get("t") or "").upper()
        for cat, types in config.AIRCRAFT_TYPES.items():
            if t in types and a.get("lat") is not None and a.get("lon") is not None:
                alt = a.get("alt_baro")
                out.append({"hex": a.get("hex"), "callsign": (a.get("flight") or "").strip() or a.get("r") or a.get("hex"),
                            "reg": a.get("r"), "type": types[t], "code": t, "category": cat,
                            "lat": round(a["lat"], 3), "lon": round(a["lon"], 3),
                            "alt": alt if isinstance(alt, (int, float)) else None, "ground": alt == "ground",
                            "speed": round(a["gs"]) if isinstance(a.get("gs"), (int, float)) else None,
                            "track": round(a["track"]) if isinstance(a.get("track"), (int, float)) else None,
                            "seen": a.get("seen")})
                break
    return out


# ============================================== State Dept travel advisories
def travel_advisories():
    root = ET.fromstring(fetch("https://travel.state.gov/_res/rss/TAsTWs.xml", "travel_advisories.xml"))
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        desc = re.sub(r"<[^>]+>", " ", item.findtext("description") or "")
        m = re.search(r"Level\s*(\d)", title)
        out.append({"country": title.split(" - ")[0].strip(), "title": title, "level": int(m.group(1)) if m else None,
                    "ordered_departure": bool(re.search(r"ordered departure", desc, re.I)),
                    "url": item.findtext("link"), "time": _parse_any_date(item.findtext("pubDate"))})
    if not out:
        raise FetchError("advisory feed returned no items (format may have changed)")
    return out


# ===================================================================== Bluesky
_bsky = {}


def _bsky_auth():
    handle, pw = os.environ.get("BSKY_HANDLE"), os.environ.get("BSKY_APP_PASSWORD")
    if not (handle and pw) or FIXTURES:
        return None
    if "jwt" not in _bsky:
        body = json.dumps({"identifier": handle, "password": pw}).encode()
        try:
            sess = _json(fetch("https://bsky.social/xrpc/com.atproto.server.createSession", None,
                               headers={"Content-Type": "application/json"}, data=body, attempts=2), "Bluesky login")
        except FetchError as e:
            raise FetchError("Bluesky login failed (check BSKY_HANDLE / BSKY_APP_PASSWORD secrets): " + str(e), e.status)
        _bsky["jwt"] = sess["accessJwt"]
    return _bsky["jwt"]


def bluesky_search(query, limit=100):
    jwt = _bsky_auth()
    params = urllib.parse.urlencode({"q": query, "limit": limit, "sort": "latest"})
    if jwt:
        url, headers = "https://bsky.social/xrpc/app.bsky.feed.searchPosts?" + params, {"Authorization": "Bearer " + jwt}
    else:
        url, headers = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?" + params, {}
    try:
        js = _json(fetch(url, "bsky_" + _slug(query) + ".json", headers=headers, attempts=2), "Bluesky")
    except FetchError as e:
        if not jwt and e.status in (401, 403):
            raise NotConfigured("Bluesky no longer allows anonymous search. Add BSKY_HANDLE and BSKY_APP_PASSWORD "
                                "(an app password) as GitHub Actions secrets.")
        raise
    out = []
    for p in js.get("posts", []):
        rec, author = p.get("record") or {}, p.get("author") or {}
        rkey = (p.get("uri") or "").rsplit("/", 1)[-1]
        out.append({"platform": "Bluesky", "text": (rec.get("text") or "")[:300], "author": author.get("handle"),
                    "time": rec.get("createdAt"), "likes": p.get("likeCount", 0), "reposts": p.get("repostCount", 0),
                    "url": f"https://bsky.app/profile/{author.get('handle')}/post/{rkey}", "query": query})
    return out


# ===================================================================== Reddit
_reddit = {}


def _reddit_token():
    cid, secret = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if not (cid and secret) or FIXTURES:
        return None
    if "token" not in _reddit:
        import base64
        auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
        js = _json(fetch("https://www.reddit.com/api/v1/access_token", None, data=b"grant_type=client_credentials",
                         headers={"Authorization": "Basic " + auth, "Content-Type": "application/x-www-form-urlencoded"},
                         attempts=2), "Reddit login")
        if "access_token" not in js:
            raise FetchError("Reddit login failed: " + json.dumps(js)[:160])
        _reddit["token"] = js["access_token"]
    return _reddit["token"]


def reddit_new(sub):
    token = _reddit_token()
    if token:
        url, headers = f"https://oauth.reddit.com/r/{sub}/new?limit=100", {"Authorization": "Bearer " + token}
    else:
        url, headers = f"https://www.reddit.com/r/{sub}/new.json?limit=100", {}
    try:
        js = _json(fetch(url, f"reddit_{sub}.json", headers=headers, attempts=2), "Reddit")
    except FetchError as e:
        if not token and e.status in (401, 403, 429):
            raise NotConfigured("Reddit blocks anonymous requests from cloud servers like GitHub's. "
                                "Add REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET secrets from a Reddit API app.")
        raise
    out = []
    for c in js.get("data", {}).get("children", []):
        d = c.get("data", {})
        out.append({"platform": "Reddit", "text": d.get("title", ""), "author": "r/" + sub,
                    "time": datetime.fromtimestamp(d.get("created_utc", 0), timezone.utc).isoformat(),
                    "likes": d.get("score", 0), "reposts": d.get("num_comments", 0),
                    "url": "https://www.reddit.com" + d.get("permalink", "")})
    return out


# ================================================================== Mastodon
def mastodon_tag(tag, instance="mastodon.social"):
    js = _json(fetch(f"https://{instance}/api/v1/timelines/tag/{urllib.parse.quote(tag)}?limit=40",
                     "masto_" + _slug(tag) + ".json", attempts=2), "Mastodon")
    out = []
    for s in js if isinstance(js, list) else []:
        text = _html.unescape(re.sub(r"<[^>]+>", " ", s.get("content") or "")).strip()
        out.append({"platform": "Mastodon", "text": re.sub(r"\s+", " ", text)[:300], "author": (s.get("account") or {}).get("acct"),
                    "time": s.get("created_at"), "likes": s.get("favourites_count", 0), "reposts": s.get("reblogs_count", 0),
                    "url": s.get("url"), "query": "#" + tag})
    return out


# ================================================================== Telegram
def telegram_channel(channel):
    page = fetch(f"https://t.me/s/{channel}", "tg_" + _slug(channel) + ".html", attempts=2)
    out = []
    for m in re.finditer(r'data-post="([^"]+)".*?tgme_widget_message_text[^>]*>(.*?)</div>.*?datetime="([^"]+)"', page, re.S):
        text = _html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))
        out.append({"platform": "Telegram", "text": re.sub(r"\s+", " ", text).strip()[:300], "author": channel,
                    "time": _parse_any_date(m.group(3)), "likes": 0, "reposts": 0, "url": "https://t.me/" + m.group(1)})
    return out[-30:]


# ======================================================= USGS earthquakes
def _haversine(lat1, lon1, lat2, lon2):
    r = math.radians
    a = math.sin(r(lat2 - lat1) / 2) ** 2 + math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(r(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def seismic_near_test_sites():
    js = _json(fetch("https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson", "usgs_week.json"), "USGS")
    out = []
    for f in js.get("features", []):
        lon, lat, depth = (f.get("geometry", {}).get("coordinates") or [None, None, None])[:3]
        if lat is None:
            continue
        for site in config.TEST_SITES:
            d = _haversine(lat, lon, site["lat"], site["lon"])
            if d <= site["radius_km"]:
                p = f.get("properties", {})
                out.append({"site": site["name"], "distance_km": round(d), "mag": p.get("mag"), "depth_km": depth,
                            "shallow": depth is not None and depth <= 5, "place": p.get("place"), "url": p.get("url"),
                            "time": datetime.fromtimestamp((p.get("time") or 0) / 1000, timezone.utc).isoformat(),
                            "lat": lat, "lon": lon})
    out.sort(key=lambda x: x["time"], reverse=True)
    return out


# ================================================== NGA maritime warnings
NGA_URLS = [
    "https://msi.nga.mil/api/publications/broadcast-warn?output=json&status=active",
    "https://msi.nga.mil/api/publications/broadcast-warn?status=active&output=json&includeCancels=false",
]


def nga_warnings():
    errors = []
    js = None
    for i, url in enumerate(NGA_URLS):
        try:
            js = _json(fetch(url, "nga_warnings.json" if i == 0 else None, attempts=2,
                             headers={"Accept": "application/json", "Referer": "https://msi.nga.mil/NavWarnings"}), "NGA")
            break
        except FetchError as e:
            errors.append(str(e))
            if FIXTURES:
                break
    if js is None:
        raise FetchError(" | ".join(errors))
    if isinstance(js, list):
        items = js
    else:
        items = js.get("broadcast-warn") or js.get("broadcastWarn") or js.get("warnings") or []
        if not items and js:
            raise FetchError("NGA response format changed; top-level keys: " + ", ".join(list(js)[:8]))
    out = []
    for w in items:
        text = (w.get("text") or "").replace("\n", " ")
        low = text.lower()
        kind = next((k for k, kws in config.NAV_WARNING_TYPES if any(x in low for x in kws)), None)
        if kind:
            out.append({"id": f"{w.get('navArea', '')} {w.get('msgNumber', '')}/{w.get('msgYear', '')}".strip(),
                        "area": w.get("navArea"), "authority": w.get("authority"), "type": kind,
                        "issued": w.get("issueDate"), "text": text[:400]})
    return {"total_active": len(items), "relevant": out}


# ================================================== IODA internet outages
def internet_outages(countries):
    until = int(time.time())
    url = ("https://api.ioda.inetintel.cc.gatech.edu/v2/outages/summary?"
           + urllib.parse.urlencode({"from": until - 86400, "until": until, "entityType": "country"}))
    js = _json(fetch(url, "ioda_summary.json", timeout=60), "IODA")
    out = []
    for row in js.get("data", []) or []:
        ent = row.get("entity") or {}
        code = (ent.get("code") or "").upper()
        if code in countries:
            out.append({"code": code, "name": ent.get("name") or countries[code],
                        "score": round((row.get("scores") or {}).get("overall") or 0), "events": row.get("event_cnt") or 0})
    out.sort(key=lambda x: -x["score"])
    return out


# ================================================== Wikipedia attention
def wiki_pageviews(article, days=30):
    end = _now() - timedelta(days=1)
    start = end - timedelta(days=days)
    url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
           + urllib.parse.quote(article, safe="") + f"/daily/{start:%Y%m%d}/{end:%Y%m%d}")
    js = _json(fetch(url, "wiki_" + _slug(article) + ".json", attempts=2), "Wikipedia")
    vals = [i.get("views", 0) for i in js.get("items", [])]
    if len(vals) < 8:
        raise FetchError(f"only {len(vals)} days of Wikipedia data for {article}")
    last, earlier = vals[-1], sorted(vals[:-1])
    base = earlier[len(earlier) // 2]
    return {"article": article.replace("_", " "), "yesterday": last, "median": base,
            "ratio": round(last / base, 2) if base else None, "series": vals[-14:]}


# =========================================================== Markets
def _series_result(label, closes, src):
    closes = [c for c in closes if c is not None]
    if len(closes) < 2:
        raise FetchError(f"{src}: not enough data points")
    return {"name": label, "last": round(closes[-1], 2), "change_pct": round((closes[-1] / closes[-2] - 1) * 100, 2),
            "series": [round(c, 2) for c in closes[-14:]], "via": src}


def fred(series_id, label):
    """St. Louis Fed public CSV (no key)."""
    text = fetch(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}", "fred_" + _slug(series_id) + ".csv", attempts=2)
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len(rows[0]) < 2:
        raise FetchError("FRED: unexpected CSV: " + text[:120])
    closes = []
    for r in rows[1:][-40:]:
        try:
            closes.append(float(r[1]))
        except (ValueError, IndexError):
            continue
    return _series_result(label, closes, "FRED " + series_id)


def yahoo(symbol, label):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(symbol) + "?range=1mo&interval=1d"
    js = _json(fetch(url, "yahoo_" + _slug(symbol) + ".json", attempts=2, headers={"Accept": "application/json"}), "Yahoo")
    res = ((js.get("chart") or {}).get("result") or [None])[0]
    if not res:
        raise FetchError("Yahoo: " + json.dumps((js.get("chart") or {}).get("error"))[:160])
    closes = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    return _series_result(label, closes, "Yahoo " + symbol)


def stooq(symbol, label):
    text = fetch(f"https://stooq.com/q/d/l/?s={symbol}&i=d", "stooq_" + _slug(symbol) + ".csv", attempts=2)
    if not text.lower().startswith("date"):
        raise FetchError("Stooq: " + " ".join(text.split())[:140])
    rows = list(csv.DictReader(io.StringIO(text)))
    return _series_result(label, [float(r["Close"]) for r in rows[-30:] if r.get("Close") not in (None, "", "null")], "Stooq " + symbol)


def cboe_vix():
    rows = list(csv.DictReader(io.StringIO(fetch("https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv", "vix.csv"))))
    return _series_result("VIX (fear index)", [float(r["CLOSE"]) for r in rows[-30:]], "Cboe")


def market(label, providers):
    """Try each provider in order; return the first that works."""
    errors = []
    for kind, sym in providers:
        try:
            if kind == "fred":
                return fred(sym, label)
            if kind == "yahoo":
                return yahoo(sym, label)
            if kind == "stooq":
                return stooq(sym, label)
            if kind == "cboe":
                return cboe_vix()
        except FetchError as e:
            errors.append(f"{kind}:{sym} → {e}")
            if FIXTURES:
                continue
    raise FetchError(" | ".join(errors))


# =================================================== Official statements
def _parse_any_date(s):
    if not s:
        return None
    s = s.strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S"):
        try:
            d = datetime.strptime(s, fmt)
            return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()
        except ValueError:
            continue
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def _parse_feed(text):
    stripped = text.lstrip()
    if not stripped.startswith("<"):
        raise FetchError("not an RSS/Atom feed: " + " ".join(stripped.split())[:140])
    root = ET.fromstring(stripped)
    atom = "{http://www.w3.org/2005/Atom}"
    entries = list(root.iter("item")) or list(root.iter(atom + "entry"))
    if root.tag.lower() == "html" or (not entries and "<html" in stripped[:500].lower()):
        raise FetchError("got a web page instead of a feed")
    out = []
    for it in entries[:50]:
        title = (it.findtext("title") or it.findtext(atom + "title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if not link:
            le = it.find(atom + "link")
            link = le.get("href") if le is not None else ""
        desc = re.sub(r"<[^>]+>", " ", it.findtext("description") or it.findtext(atom + "summary") or "")
        when = it.findtext("pubDate") or it.findtext(atom + "updated") or it.findtext(atom + "published")
        out.append({"title": _html.unescape(title), "url": link, "summary": _html.unescape(desc.strip())[:300],
                    "time": _parse_any_date(when)})
    return out


def official_feed(name, urls):
    """Try each candidate URL for a feed until one parses."""
    errors = []
    for i, url in enumerate(urls):
        try:
            return {"items": _parse_feed(fetch(url, "rss_" + _slug(name) + ".xml" if i == 0 else None, attempts=2,
                                               headers={"Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.5"})),
                    "url": url}
        except (FetchError, ET.ParseError) as e:
            errors.append(f"{url} → {e}")
            if FIXTURES:
                break
    raise FetchError(" | ".join(errors))


# =============================================== UK Foreign Office advice
def fcdo_advice(slug):
    js = _json(fetch("https://www.gov.uk/api/content/foreign-travel-advice/" + slug, "fcdo_" + slug + ".json", attempts=2), "GOV.UK")
    d = js.get("details") or {}
    alerts = d.get("alert_status") or []
    return {"country": js.get("title", slug).replace(" travel advice", ""), "updated": js.get("public_updated_at"),
            "change": (d.get("change_description") or "")[:240], "alerts": alerts,
            "avoid_all": any("avoid_all_travel" in a for a in alerts),
            "url": "https://www.gov.uk/foreign-travel-advice/" + slug}


# =========================================== NASA FIRMS fire hotspots
def firms_hotspots(bbox):
    key = os.environ.get("FIRMS_MAP_KEY")
    if not key and not FIXTURES:
        raise NotConfigured("Add a free NASA FIRMS MAP_KEY as the FIRMS_MAP_KEY secret to track fires in conflict zones.")
    text = fetch(f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/VIIRS_SNPP_NRT/{bbox}/1",
                 "firms_" + _slug(bbox) + ".csv", attempts=2)
    if "latitude" not in text[:200]:
        raise FetchError("FIRMS: " + " ".join(text.split())[:140])
    return len(list(csv.DictReader(io.StringIO(text))))
