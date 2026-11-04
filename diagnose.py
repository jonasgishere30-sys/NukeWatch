"""Live connection check: one plain request per endpoint, no retries, and print exactly what came back.

Run on GitHub (Actions → diagnose → Run workflow) because that is where the real requests come from.
Also writes data/diagnostics.json.

    python -m collector.diagnose
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from . import config

GDELT = "https://api.gdeltproject.org/api/v2/doc/doc?"
FP = config.FLASHPOINTS[0]["query"] + " sourcelang:english"


def endpoints():
    e = [
        ("GDELT articles (flashpoint query)", GDELT + urllib.parse.urlencode({"query": FP, "mode": "ArtList", "format": "json", "maxrecords": 5, "timespan": "24h"}), {}),
        ("GDELT volume (flashpoint query)", GDELT + urllib.parse.urlencode({"query": FP, "mode": "TimelineVolRaw", "format": "json", "timespan": "7d"}), {}),
        ("GDELT simple query", GDELT + urllib.parse.urlencode({"query": "nuclear", "mode": "ArtList", "format": "json", "maxrecords": 3, "timespan": "24h"}), {}),
        ("Bluesky public search", "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=nuclear&limit=2", {}),
        ("Reddit JSON (anonymous)", "https://www.reddit.com/r/worldnews/new.json?limit=2", {}),
        ("Reddit RSS (anonymous)", "https://www.reddit.com/r/worldnews/new/.rss", {}),
        ("airplanes.live military", "https://api.airplanes.live/v2/mil", {}),
        ("adsb.fi military", "https://opendata.adsb.fi/api/v2/mil", {}),
        ("US travel advisories", "https://travel.state.gov/_res/rss/TAsTWs.xml", {}),
        ("UK travel advice (Russia)", "https://www.gov.uk/api/content/foreign-travel-advice/russia", {}),
        ("USGS earthquakes", "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson", {}),
        ("IODA outages", "https://api.ioda.inetintel.cc.gatech.edu/v2/outages/summary?" + urllib.parse.urlencode({"from": int(time.time()) - 86400, "until": int(time.time()), "entityType": "country"}), {}),
        ("Wikipedia pageviews", "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/DEFCON/daily/20261001/20261030", {}),
        ("Mastodon #nuclear", "https://mastodon.social/api/v1/timelines/tag/nuclear?limit=2", {}),
        ("Cboe VIX CSV", "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv", {}),
        ("FRED S&P 500 CSV", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500", {}),
        ("Yahoo gold futures", "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?range=5d&interval=1d", {"Accept": "application/json"}),
        ("Stooq gold CSV", "https://stooq.com/q/d/l/?s=xauusd&i=d", {}),
    ]
    from .sources import NGA_URLS
    for i, u in enumerate(NGA_URLS):
        e.append((f"NGA maritime warnings #{i + 1}", u, {"Accept": "application/json", "Referer": "https://msi.nga.mil/NavWarnings"}))
    for name, urls, _ in config.OFFICIAL_FEEDS:
        for i, u in enumerate(urls):
            e.append((f"Feed: {name} #{i + 1}", u, {"Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.5"}))
    return e


def probe(url, headers):
    h = {"User-Agent": config.USER_AGENT, "Accept": "*/*"}
    h.update(headers)
    t0 = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
            body = r.read(4000).decode("utf-8", errors="replace")
            return {"status": r.status, "type": r.headers.get("Content-Type"), "final_url": r.geturl(),
                    "ms": round((time.time() - t0) * 1000), "body": " ".join(body.split())[:300]}
    except urllib.error.HTTPError as e:
        try:
            body = e.read(4000).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            body = ""
        return {"status": e.code, "type": e.headers.get("Content-Type") if e.headers else None,
                "retry_after": e.headers.get("Retry-After") if e.headers else None,
                "ms": round((time.time() - t0) * 1000), "body": " ".join(body.split())[:300]}
    except Exception as e:  # noqa: BLE001
        return {"status": None, "error": f"{type(e).__name__}: {e}", "ms": round((time.time() - t0) * 1000)}


def main():
    results = []
    for name, url, headers in endpoints():
        if name.startswith("GDELT"):
            time.sleep(6)
        r = probe(url, headers)
        r.update({"name": name, "url": url})
        results.append(r)
        flag = "OK " if r.get("status") == 200 else "ERR"
        print(f"{flag} {name}\n    {r.get('status')} {r.get('type') or ''} {r.get('ms')}ms  {url}\n    {r.get('error') or r.get('body')}\n")
    for who, env in (("Bluesky login secrets", ("BSKY_HANDLE", "BSKY_APP_PASSWORD")),
                     ("Reddit API secrets", ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET")),
                     ("NASA FIRMS secret", ("FIRMS_MAP_KEY",))):
        print(f"{who}: {'set' if all(os.environ.get(v) for v in env) else 'NOT set'}")
    os.makedirs("data", exist_ok=True)
    with open("data/diagnostics.json", "w", encoding="utf-8") as f:
        json.dump({"ran": datetime.now(timezone.utc).isoformat(), "results": results}, f, indent=1)


if __name__ == "__main__":
    main()
