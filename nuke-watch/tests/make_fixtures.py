"""Writes fake API responses (same shape as the real ones) for the offline test."""
import json, os, re, sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collector import config
from collector.sources import _slug
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
os.makedirs(D, exist_ok=True)
now = datetime.now(timezone.utc)
g = lambda dt: dt.strftime("%Y%m%dT%H%M%SZ")
def w(name, obj):
    with open(os.path.join(D, name), "w") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))
titles = ["TEST headline: officials warn of nuclear threat", "TEST headline: drone strike reported", "TEST headline: troops deploy for drills",
          "TEST headline: talks stall amid tension", "TEST headline: missile test reported", "TEST headline: attack on depot"]
for fp in config.FLASHPOINTS + [{"query": config.GOV_PREP_QUERY}, {"query": config.NUCLEAR_NEWS_QUERY}]:
    arts = [{"url": f"https://example.com/{i}", "title": f"{titles[i % 6]} ({fp.get('short','x')} {i})", "seendate": g(now - timedelta(minutes=37 * i)),
             "socialimage": "", "domain": "example.com", "language": "English", "sourcecountry": "United States"} for i in range(12)]
    w("gdelt_art_" + _slug(fp["query"]) + ".json", {"articles": arts})
    pts = [{"date": g(now - timedelta(minutes=15 * k)), "value": 3 + (k % 5) + (4 if k < 96 else 0)} for k in range(672)]
    w("gdelt_vol_" + _slug(fp["query"]) + ".json", {"timeline": [{"series": "Article Count", "data": pts[::-1]}]})
ac = [{"hex": "ae0001", "flight": "TEST01 ", "t": "E6", "lat": 33.2, "lon": -150.1, "alt_baro": 31000, "gs": 400, "track": 90},
      {"hex": "ae0002", "flight": "TEST02 ", "t": "K35R", "lat": 52.1, "lon": -32.3, "alt_baro": 28000, "gs": 430, "track": 270},
      {"hex": "ae0003", "flight": "TEST03 ", "t": "B52", "lat": 61.0, "lon": -38.0, "alt_baro": 33000, "gs": 460, "track": 45},
      {"hex": "ae0004", "flight": "TEST04 ", "t": "R135", "lat": 57.0, "lon": 19.0, "alt_baro": 32000, "gs": 420, "track": 180},
      {"hex": "ae0005", "flight": "TEST05 ", "t": "C17", "lat": 40.0, "lon": -80.0, "alt_baro": 30000, "gs": 420, "track": 180}]
w("airplanes_live_mil.json", {"ac": ac, "now": 0})
w("travel_advisories.xml", f"""<?xml version="1.0"?><rss><channel>
<item><title>Testland - Level 4: Do Not Travel</title><link>https://travel.state.gov/test</link><description>Ordered departure of non-emergency staff.</description><pubDate>{now.strftime('%a, %d %b %Y %H:%M:%S')} GMT</pubDate></item>
<item><title>Otherland - Level 2: Exercise Increased Caution</title><link>https://travel.state.gov/test2</link><description>x</description><pubDate>{now.strftime('%a, %d %b %Y %H:%M:%S')} GMT</pubDate></item>
</channel></rss>""")
for q in config.BLUESKY_QUERIES:
    w("bsky_" + _slug(q) + ".json", {"posts": [{"uri": f"at://did:x/app.bsky.feed.post/{i}", "author": {"handle": "test.bsky.social"},
        "record": {"text": f"TEST post about {q} #{i}", "createdAt": (now - timedelta(minutes=9 * i)).isoformat()}, "likeCount": i, "repostCount": 1} for i in range(10)]})
for s in config.REDDIT_SUBS:
    w(f"reddit_{s}.json", {"data": {"children": [{"data": {"title": f"TEST nuclear missile thread {s}", "created_utc": now.timestamp(), "score": 50, "num_comments": 9, "permalink": f"/r/{s}/test"}}]}})
print("fixtures written to", D)
