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


# ======================================================================
# Extra signal sources (all free; ones that need a key are skipped without it)
# ======================================================================
import csv
import html as _html
import io
import math


def _haversine(lat1, lon1, lat2, lon2):
    r = math.radians
    a = math.sin(r(lat2 - lat1) / 2) ** 2 + math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(r(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


# ------------------------------------------------ USGS earthquakes near test sites
def seismic_near_test_sites():
    """Shallow quakes near known nuclear test sites can be a test. Most are natural or mine blasts."""
    try:
        js = json.loads(_get("https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson", "usgs_week.json"))
    except Exception as e:  # noqa: BLE001
        return [], str(e)
    out = []
    for f in js.get("features", []):
        lon, lat, depth = (f.get("geometry", {}).get("coordinates") or [None, None, None])[:3]
        if lat is None:
            continue
        for site in config.TEST_SITES:
            d = _haversine(lat, lon, site["lat"], site["lon"])
            if d <= site["radius_km"]:
                p = f.get("properties", {})
                out.append({
                    "site": site["name"], "distance_km": round(d), "mag": p.get("mag"), "depth_km": depth,
                    "shallow": depth is not None and depth <= 5, "place": p.get("place"), "url": p.get("url"),
                    "time": datetime.fromtimestamp((p.get("time") or 0) / 1000, timezone.utc).isoformat(),
                    "lat": lat, "lon": lon,
                })
    out.sort(key=lambda x: x["time"], reverse=True)
    return out, None


# ------------------------------------------------ NGA maritime safety warnings
def nga_warnings():
    """Active NAVAREA / HYDROLANT / HYDROPAC broadcast warnings (missile tests, firing areas, rocket debris)."""
    try:
        js = json.loads(_get("https://msi.nga.mil/api/publications/broadcast-warn?output=json&status=active", "nga_warnings.json"))
    except Exception as e:  # noqa: BLE001
        return [], str(e)
    items = js if isinstance(js, list) else (js.get("broadcast-warn") or js.get("broadcastWarn") or [])
    out = []
    for w in items:
        text = (w.get("text") or "").replace("\n", " ")
        low = text.lower()
        kind = next((k for k, kws in config.NAV_WARNING_TYPES if any(x in low for x in kws)), None)
        if not kind:
            continue
        out.append({
            "id": f"{w.get('navArea', '')} {w.get('msgNumber', '')}/{w.get('msgYear', '')}".strip(),
            "area": w.get("navArea"), "authority": w.get("authority"), "type": kind,
            "issued": w.get("issueDate"), "text": text[:400],
        })
    return out, None


# ------------------------------------------------ IODA internet outages
def internet_outages(countries):
    until = int(time.time())
    url = ("https://api.ioda.inetintel.cc.gatech.edu/v2/outages/summary?"
           + urllib.parse.urlencode({"from": until - 86400, "until": until, "entityType": "country"}))
    try:
        js = json.loads(_get(url, "ioda_summary.json"))
    except Exception as e:  # noqa: BLE001
        return [], str(e)
    out = []
    for row in js.get("data", []) or []:
        ent = row.get("entity") or {}
        code = (ent.get("code") or "").upper()
        if code in countries:
            out.append({"code": code, "name": ent.get("name") or countries[code],
                        "score": round((row.get("scores") or {}).get("overall") or 0),
                        "events": row.get("event_cnt") or 0})
    out.sort(key=lambda x: -x["score"])
    return out, None


# ------------------------------------------------ Wikipedia attention
def wiki_pageviews(article, days=30):
    end = datetime.now(timezone.utc) - timedelta(days=1)
    start = end - timedelta(days=days)
    url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
           + urllib.parse.quote(article, safe="") + f"/daily/{start:%Y%m%d}/{end:%Y%m%d}")
    try:
        js = json.loads(_get(url, "wiki_" + _slug(article) + ".json"))
    except Exception as e:  # noqa: BLE001
        return None, str(e)
    vals = [i.get("views", 0) for i in js.get("items", [])]
    if len(vals) < 8:
        return None, "not enough data"
    last = vals[-1]
    base = sorted(vals[:-1])[len(vals[:-1]) // 2]  # median of earlier days
    return {"article": article.replace("_", " "), "yesterday": last, "median": base,
            "ratio": round(last / base, 2) if base else None, "series": vals[-14:]}, None


# ------------------------------------------------ Markets
def vix():
    try:
        rows = list(csv.DictReader(io.StringIO(_get("https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv", "vix.csv"))))
        closes = [float(r["CLOSE"]) for r in rows[-30:]]
        if len(closes) < 2:
            raise ValueError("not enough VIX data")
    except Exception as e:  # noqa: BLE001
        return None, str(e)
    return {"name": "VIX (fear index)", "last": closes[-1], "change_pct": round((closes[-1] / closes[-2] - 1) * 100, 1),
            "series": closes[-14:]}, None


def stooq(symbol, label):
    try:
        rows = list(csv.DictReader(io.StringIO(_get(f"https://stooq.com/q/d/l/?s={symbol}&i=d", "stooq_" + _slug(symbol) + ".csv"))))
        closes = [float(r["Close"]) for r in rows[-30:] if r.get("Close") not in (None, "", "null")]
        if len(closes) < 2:
            raise ValueError("no data")
    except Exception as e:  # noqa: BLE001
        return None, str(e)
    return {"name": label, "last": closes[-1], "change_pct": round((closes[-1] / closes[-2] - 1) * 100, 2), "series": closes[-14:]}, None


# ------------------------------------------------ Official statements (RSS)
def rss_items(url, name):
    try:
        root = ET.fromstring(_get(url, "rss_" + _slug(name) + ".xml"))
    except Exception as e:  # noqa: BLE001
        return [], str(e)
    out = []
    ns_atom = "{http://www.w3.org/2005/Atom}"
    entries = list(root.iter("item")) or list(root.iter(ns_atom + "entry"))
    for it in entries[:50]:
        title = (it.findtext("title") or it.findtext(ns_atom + "title") or "").strip()
        link = it.findtext("link") or ""
        if not link:
            le = it.find(ns_atom + "link")
            link = le.get("href") if le is not None else ""
        desc = re.sub(r"<[^>]+>", " ", it.findtext("description") or it.findtext(ns_atom + "summary") or "")
        when = it.findtext("pubDate") or it.findtext(ns_atom + "updated") or it.findtext(ns_atom + "published")
        out.append({"title": _html.unescape(title), "url": link.strip(), "summary": _html.unescape(desc.strip())[:300], "time": _parse_any_date(when)})
    return out, None


def _parse_any_date(s):
    if not s:
        return None
    s = s.strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            d = datetime.strptime(s, fmt)
            return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


# ------------------------------------------------ UK Foreign Office travel advice
def fcdo_advice(slug):
    try:
        js = json.loads(_get("https://www.gov.uk/api/content/foreign-travel-advice/" + slug, "fcdo_" + slug + ".json"))
    except Exception as e:  # noqa: BLE001
        return None, str(e)
    d = js.get("details") or {}
    alerts = d.get("alert_status") or []
    return {"country": js.get("title", slug).replace(" travel advice", ""), "updated": js.get("public_updated_at"),
            "change": (d.get("change_description") or "")[:240], "alerts": alerts,
            "avoid_all": any("avoid_all_travel" in a for a in alerts),
            "url": "https://www.gov.uk/foreign-travel-advice/" + slug}, None


# ------------------------------------------------ Mastodon public hashtags
def mastodon_tag(tag, instance="mastodon.social"):
    try:
        js = json.loads(_get(f"https://{instance}/api/v1/timelines/tag/{urllib.parse.quote(tag)}?limit=40", "masto_" + _slug(tag) + ".json"))
    except Exception as e:  # noqa: BLE001
        return [], str(e)
    out = []
    for s in js if isinstance(js, list) else []:
        text = _html.unescape(re.sub(r"<[^>]+>", " ", s.get("content") or "")).strip()
        out.append({"platform": "Mastodon", "text": re.sub(r"\s+", " ", text)[:300], "author": (s.get("account") or {}).get("acct"),
                    "time": s.get("created_at"), "likes": s.get("favourites_count", 0), "reposts": s.get("reblogs_count", 0),
                    "url": s.get("url"), "query": "#" + tag})
    return out, None


# ------------------------------------------------ Telegram public channel previews
def telegram_channel(channel):
    """Reads the public web preview t.me/s/<channel>. Works only for public channels."""
    try:
        page = _get(f"https://t.me/s/{channel}", "tg_" + _slug(channel) + ".html")
    except Exception as e:  # noqa: BLE001
        return [], str(e)
    out = []
    for m in re.finditer(r'data-post="([^"]+)".*?tgme_widget_message_text[^>]*>(.*?)</div>.*?datetime="([^"]+)"', page, re.S):
        text = _html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))
        out.append({"platform": "Telegram", "text": re.sub(r"\s+", " ", text).strip()[:300], "author": channel,
                    "time": _parse_any_date(m.group(3)), "likes": 0, "reposts": 0, "url": "https://t.me/" + m.group(1)})
    return out[-30:], None


# ------------------------------------------------ NASA FIRMS fire hotspots (needs free key)
def firms_hotspots(bbox, key):
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/VIIRS_SNPP_NRT/{bbox}/1"
    try:
        rows = list(csv.DictReader(io.StringIO(_get(url, "firms_" + _slug(bbox) + ".csv"))))
    except Exception as e:  # noqa: BLE001
        return None, str(e)
    return len(rows), None
