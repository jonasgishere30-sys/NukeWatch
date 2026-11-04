"""One scan: fetch every source, score it, write data/latest.json + data/history.json.

Run from the project folder:   python -m collector.run

Missing data is never treated as "nothing happened":
  * every source gets a status (ok / cached / stale / failed / not_configured / skipped) in latest.json["sources"];
  * failed sources fall back to their last good result (marked stale, with its age) when one exists;
  * if too few flashpoints have news data, the index is reported as insufficient instead of a low score.
"""
import json
import os
import statistics
from datetime import datetime, timezone, timedelta

from . import config, sources
from .net import FIXTURES
from .tracker import Tracker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
LEVELS = ["BASELINE", "WATCH", "ELEVATED", "HIGH", "SEVERE"]
RUNG_POINTS = {1: 1, 2: 3, 3: 6, 4: 12, 5: 18, 6: 40}


def now():
    return datetime.now(timezone.utc)


def load(name, default):
    try:
        with open(os.path.join(DATA, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(name, obj):
    os.makedirs(DATA, exist_ok=True)
    tmp = os.path.join(DATA, name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, os.path.join(DATA, name))


def clamp(v, a, b):
    return max(a, min(b, v))


def rung_for(titles):
    lower = [t.lower() for t in titles]
    hits = {r: sum(1 for t in lower if any(k in t for k in kws)) for r, kws in config.RUNG_KEYWORDS.items()}
    need = max(config.MIN_HITS, round(0.08 * len(lower)))
    rung = 1
    for r in sorted(hits):
        if hits[r] >= need:
            rung = max(rung, r)
    return rung, hits


def active_exercises(t):
    out = []
    for ex in config.EXERCISES:
        try:
            s = datetime.fromisoformat(ex["start"]).replace(tzinfo=timezone.utc)
            e = datetime.fromisoformat(ex["end"]).replace(tzinfo=timezone.utc) + timedelta(days=1)
        except (KeyError, ValueError):
            continue
        if s <= t <= e:
            out.append(ex)
    return out


def baseline(history, key, min_samples=48):
    vals = [h[key] for h in history if isinstance(h.get(key), (int, float))]
    return statistics.median(vals) if len(vals) >= min_samples else None


def main():
    t = now()
    prev = load("latest.json", {})
    history = load("history.json", [])
    tr = Tracker(os.path.join(DATA, "cache"), use_cache=not FIXTURES)
    gd = sources.gdelt_budget_left  # GDELT budget check (cache serves the rest)

    # ---- 1. flashpoint news (essential, highest GDELT priority) ------------------------------
    fp_news = {}
    for fp in config.FLASHPOINTS:
        fp_news[fp["id"]] = tr.get("news:" + fp["id"], lambda q=fp["query"]: sources.gdelt_articles(q, "24h", 75),
                                   ttl_min=10, max_stale_min=6 * 60, essential=True, allow_live=gd())
    nuc = tr.get("volume:nuclear", lambda: sources.gdelt_volume(config.NUCLEAR_NEWS_QUERY), ttl_min=120, max_stale_min=48 * 60, allow_live=gd())
    fp_vol = {}
    for fp in config.FLASHPOINTS:
        fp_vol[fp["id"]] = tr.get("volume:" + fp["id"], lambda q=fp["query"]: sources.gdelt_volume(q),
                                  ttl_min=180, max_stale_min=48 * 60, allow_live=gd())
    prep_arts = tr.get("news:gov", lambda: sources.gdelt_articles(config.GOV_PREP_QUERY, "3d", 50), ttl_min=30, max_stale_min=24 * 60, allow_live=gd())
    prep_vol = tr.get("volume:gov", lambda: sources.gdelt_volume(config.GOV_PREP_QUERY), ttl_min=180, max_stale_min=48 * 60, allow_live=gd())

    flashpoints, news = [], []
    for fp in config.FLASHPOINTS:
        arts, vol = fp_news[fp["id"]], fp_vol[fp["id"]]
        st = tr.status.get("news:" + fp["id"], {})
        prev_fp = next((p for p in prev.get("flashpoints", []) if p["id"] == fp["id"]), None)
        if arts is None:
            rung, hits, rung_name = None, {}, "No data"
        else:
            rung, hits = rung_for([a["title"] for a in arts])
            rung_name = config.RUNGS[rung - 1]
        ratio = round(vol["last24"] / vol["daily_avg"], 2) if vol and vol.get("daily_avg") else None
        stories = vol["last24"] if vol else (len(arts) if arts is not None else None)
        flashpoints.append({
            "id": fp["id"], "name": fp["name"], "short": fp["short"], "nukes": fp["nukes"],
            "lat": fp["lat"], "lon": fp["lon"], "zoom": fp["zoom"], "countries": fp["countries"],
            "rung": rung, "rung_name": rung_name, "hits": hits, "stories_24h": stories, "volume_ratio": ratio,
            "trend": "↑" if ratio and ratio > 1.25 else "↓" if ratio and ratio < 0.8 else "→" if ratio else "",
            "prev_rung": prev_fp.get("rung") if prev_fp else None,
            "data_state": st.get("state"), "data_age_min": st.get("age_min"),
        })
        for a in (arts or [])[:15]:
            news.append(dict(a, flashpoint=fp["id"]))
    news.sort(key=lambda a: a.get("time") or "", reverse=True)
    nuclear_ratio = round(nuc["last24"] / nuc["daily_avg"], 2) if nuc and nuc.get("daily_avg") else None
    prep_ratio = round(prep_vol["last24"] / prep_vol["daily_avg"], 2) if prep_vol and prep_vol.get("daily_avg") else None
    for a in prep_arts or []:
        low = a["title"].lower()
        a["type"] = next((name for name, kws in config.GOV_PREP_TYPES if any(k in low for k in kws)), "Preparedness")

    # ---- 2. topic radar (cached for hours; refreshed as budget allows) ------------------------
    topics = []
    for name, q in config.TOPIC_QUERIES:
        v = tr.get("topic:" + name, lambda q=q: sources.gdelt_volume(q), ttl_min=180, max_stale_min=48 * 60, allow_live=gd())
        topics.append({"name": name, "last24": v["last24"] if v else None, "daily_avg": v["daily_avg"] if v else None,
                       "ratio": round(v["last24"] / v["daily_avg"], 2) if v and v.get("daily_avg") else None,
                       "state": tr.state("topic:" + name)})

    # ---- 3. government & diplomatic -----------------------------------------------------------
    advisories = tr.get("advisories", sources.travel_advisories, ttl_min=30, max_stale_min=48 * 60)
    week_ago = (t - timedelta(days=7)).isoformat()
    level4 = [a for a in advisories or [] if a["level"] == 4]
    recent_l4 = [a for a in level4 if (a["time"] or "") >= week_ago]
    ordered = [a for a in advisories or [] if a["ordered_departure"]]
    fcdo = []
    for slug in config.FCDO_SLUGS:
        r = tr.get("fcdo:" + slug, lambda s=slug: sources.fcdo_advice(s), ttl_min=120, max_stale_min=72 * 60)
        if r:
            fcdo.append(r)
    fcdo.sort(key=lambda x: x.get("updated") or "", reverse=True)
    fcdo_recent_avoid = [f for f in fcdo if f["avoid_all"] and (f["updated"] or "") >= week_ago]

    # ---- 4. aircraft ----------------------------------------------------------------------------
    ac = tr.get("aircraft", sources.military_aircraft, ttl_min=0, max_stale_min=60, essential=True)
    aircraft = sources.classify_aircraft(ac["ac"]) if ac else []
    counts = {c: sum(1 for a in aircraft if a["category"] == c and not a["ground"]) for c in config.AIRCRAFT_TYPES} if ac else None
    ac_live = tr.state("aircraft") == "ok"

    # ---- 5. social ---------------------------------------------------------------------------------
    hour_ago = (t - timedelta(hours=1)).isoformat()
    posts, bsky_rate, bsky_ok = [], 0, True
    for q in config.BLUESKY_QUERIES:
        ps = tr.get("bluesky:" + q, lambda q=q: sources.bluesky_search(q, 100), ttl_min=0, max_stale_min=60)
        if ps is None:
            bsky_ok = False
            if tr.state("bluesky:" + q) == "not_configured":
                for q2 in config.BLUESKY_QUERIES[1:]:  # one note is enough
                    tr.status.pop("bluesky:" + q2, None)
                tr.status["bluesky"] = tr.status.pop("bluesky:" + q)
                break
            continue
        bsky_rate += sum(1 for p in ps if (p["time"] or "") >= hour_ago)
        posts += ps
    reddit_hits = 0
    for sub in config.REDDIT_SUBS:
        ps = tr.get("reddit:" + sub, lambda s=sub: sources.reddit_new(s), ttl_min=0, max_stale_min=60)
        if ps is None and tr.state("reddit:" + sub) == "not_configured":
            note = tr.status["reddit:" + sub].get("note")
            for s2 in config.REDDIT_SUBS:
                tr.status.pop("reddit:" + s2, None)
            tr.status["reddit"] = {"state": "not_configured", "note": note, "essential": False}
            break
        for p in ps or []:
            if any(k in p["text"].lower() for k in config.REDDIT_TERMS):
                reddit_hits += 1
                posts.append(dict(p, query="keyword match"))
    masto_count, masto_ok = 0, False
    for tag in config.MASTODON_TAGS:
        ps = tr.get("mastodon:" + tag, lambda g=tag: sources.mastodon_tag(g), ttl_min=0, max_stale_min=60)
        if ps is None:
            continue
        masto_ok = True
        masto_count += sum(1 for p in ps if (p["time"] or "") >= hour_ago)
        posts += [p for p in ps if any(k in p["text"].lower() for k in config.REDDIT_TERMS)]
    tg_hits = 0
    for ch in config.TELEGRAM_CHANNELS:
        for p in tr.get("telegram:" + ch, lambda c=ch: sources.telegram_channel(c), ttl_min=0, max_stale_min=60) or []:
            if any(k in p["text"].lower() for k in config.TELEGRAM_KEYWORDS):
                tg_hits += 1
                posts.append(dict(p, query="keyword match"))
    seen, top_posts = set(), []
    for p in sorted(posts, key=lambda p: (p.get("likes", 0) + 2 * p.get("reposts", 0)), reverse=True):
        if p["text"][:80] not in seen:
            seen.add(p["text"][:80])
            top_posts.append(p)
    top_posts = top_posts[:12]

    # ---- 6. physical-world signals --------------------------------------------------------------
    seismic = tr.get("seismic", sources.seismic_near_test_sites, ttl_min=15, max_stale_min=24 * 60)
    nav = tr.get("nav_warnings", sources.nga_warnings, ttl_min=60, max_stale_min=48 * 60)
    navwarn = nav["relevant"] if nav else None
    outages = tr.get("internet_outages", lambda: sources.internet_outages(config.OUTAGE_COUNTRIES), ttl_min=15, max_stale_min=6 * 60)
    fires = []
    for name, bbox in config.FIRMS_AREAS:
        n = tr.get("firms:" + name, lambda b=bbox: sources.firms_hotspots(b), ttl_min=60, max_stale_min=24 * 60)
        if tr.state("firms:" + name) == "not_configured":
            tr.status["firms"] = tr.status.pop("firms:" + name)
            for n2, _ in config.FIRMS_AREAS:
                tr.status.pop("firms:" + n2, None)
            break
        if n is not None:
            fires.append({"area": name, "hotspots_24h": n})

    # ---- 7. attention, markets, statements ----------------------------------------------------
    attention = []
    for art in config.WIKI_ARTICLES:
        r = tr.get("wikipedia:" + art, lambda a=art: sources.wiki_pageviews(a), ttl_min=360, max_stale_min=72 * 60)
        if r:
            attention.append(r)
    attention.sort(key=lambda a: -(a["ratio"] or 0))
    markets = []
    for label, providers in config.MARKETS:
        m = tr.get("market:" + label, lambda l=label, p=providers: sources.market(l, p), ttl_min=60, max_stale_min=72 * 60)
        if m:
            markets.append(m)
    statements = []
    for name, urls, domain in config.OFFICIAL_FEEDS:
        feed = tr.get("feed:" + name, lambda n=name, u=urls: sources.official_feed(n, u), ttl_min=30, max_stale_min=48 * 60)
        items = feed["items"] if feed else None
        if items is None and domain and gd():
            # Fallback: the agency's own pages as indexed by GDELT news search.
            items = tr.get("feed-via-news:" + name, lambda d=domain: sources.gdelt_articles("domainis:" + d, "3d", 25, english=False),
                           ttl_min=120, max_stale_min=48 * 60, allow_live=gd())
            if items is not None:
                tr.status["feed:" + name]["note"] = "feed failed; using the agency's pages found by news search instead"
                items = [dict(i, summary="") for i in items]
        for it in items or []:
            low = (it["title"] + " " + it.get("summary", "")).lower()
            hit = [k for k in config.OFFICIAL_KEYWORDS if k in low]
            if hit:
                statements.append(dict(it, source=name, matched=hit[:4]))
    statements.sort(key=lambda x: x.get("time") or "", reverse=True)

    # ---- history & baselines (only live measurements feed baselines) --------------------------
    snap = {"t": t.isoformat()}
    if ac_live:
        snap.update({k: counts[k] for k in counts})
    if bsky_ok and tr.state("bluesky:" + config.BLUESKY_QUERIES[0]) == "ok":
        snap["bsky"] = bsky_rate
    if masto_ok:
        snap["masto"] = masto_count
    if nav and tr.state("nav_warnings") == "ok":
        snap["missile_warn"] = sum(1 for w in navwarn if w["type"] == "Missile / rocket")
    history.append(snap)
    history = history[-config.HISTORY_MAX:]
    try:
        days_of_history = (t - datetime.fromisoformat(history[0]["t"])).total_seconds() / 86400
    except (ValueError, KeyError, IndexError):
        days_of_history = 0

    # ---- score ------------------------------------------------------------------------------------
    exercises = active_exercises(t)
    affected = {c for ex in exercises for c in ex.get("affects", [])}
    rated = [f for f in flashpoints if f["rung"] is not None]
    insufficient = len(rated) < config.MIN_FLASHPOINT_COVERAGE
    breakdown = []

    top = max(rated, key=lambda f: (f["rung"], f["stories_24h"] or 0)) if rated else None
    pol = RUNG_POINTS[top["rung"]] + 0.5 * sum(RUNG_POINTS[f["rung"]] for f in rated if f is not top) if top else 0
    missing_fp = [f["short"] for f in flashpoints if f["rung"] is None]
    breakdown.append({"name": "Political flashpoints", "max": 40, "pts": round(min(40, pol)),
                      "coverage": "none" if not rated else "partial" if missing_fp else "full",
                      "why": ", ".join(f"{f['short']} rung {f['rung']}" for f in sorted(rated, key=lambda f: -f["rung"])[:3])
                             + (f"; no news data for {', '.join(missing_fp)}" if missing_fp else "")})

    strat, notes = 0.0, []
    if counts is None:
        notes.append("aircraft feeds unavailable")
    else:
        for cat in ("command", "bomber", "tanker", "airlift"):
            b = baseline(history[:-1], cat)
            if b is None:
                notes.append(f"{cat}: building baseline")
                continue
            r = counts.get(cat, 0) / max(b, 1)
            pts = clamp((r - 1.3) * (5 if cat == "airlift" else 10), 0, 5 if cat == "airlift" else 10)
            strat += pts / 2 if cat in affected else pts
            notes.append(f"{cat} {counts.get(cat, 0)} vs normal {b:g}")
    breakdown.append({"name": "Strategic forces", "max": 30, "pts": round(strat),
                      "coverage": "none" if counts is None else "full" if ac_live else "partial",
                      "why": "; ".join(notes) + ("; exercise down-weighting on" if affected else "")})

    sig, sig_notes, sig_missing = 0.0, [], []
    shallow = [q for q in seismic or [] if q["shallow"] and (q["time"] or "") >= (t - timedelta(days=2)).isoformat()]
    if seismic is None:
        sig_missing.append("seismic")
    elif shallow:
        sig += 5
        sig_notes.append(f"shallow quake near {shallow[0]['site']}")
    if navwarn is None:
        sig_missing.append("maritime warnings")
    else:
        mw = sum(1 for w in navwarn if w["type"] == "Missile / rocket")
        b_mw = baseline(history[:-1], "missile_warn")
        if b_mw is not None and mw > b_mw * 1.5 + 1:
            sig += 3
        sig_notes.append(f"{mw} active missile/rocket sea warnings" + (f" (normal {b_mw:g})" if b_mw is not None else ""))
    if outages is None:
        sig_missing.append("internet outages")
    else:
        big = [o for o in outages if o["score"] >= 1000]
        if big:
            sig += min(2, len(big))
            sig_notes.append("internet outages: " + ", ".join(o["name"] for o in big[:3]))
    breakdown.append({"name": "Command & signals", "max": 10, "pts": round(min(sig, 10)),
                      "coverage": "none" if len(sig_missing) == 3 else "partial" if sig_missing else "full",
                      "why": "; ".join(sig_notes or ["No unusual seismic, maritime or internet signals"])
                             + (f"; unavailable: {', '.join(sig_missing)}" if sig_missing else "")})

    ns, ns_missing = 0.0, []
    if nuclear_ratio is None:
        ns_missing.append("nuclear news volume")
    else:
        ns += clamp((nuclear_ratio - 1) * 8, 0, 6)
    b_bsky = baseline(history[:-1], "bsky")
    bsky_ratio = round(bsky_rate / max(b_bsky, 1), 2) if b_bsky is not None and "bsky" in snap else None
    if bsky_ratio:
        ns += clamp((bsky_ratio - 1) * 4, 0, 4)
    hot_topics = [x for x in topics if x["ratio"] and x["ratio"] >= 1.8]
    ns += min(2, len(hot_topics))
    if not any(x["ratio"] is not None for x in topics):
        ns_missing.append("topic radar")
    breakdown.append({"name": "News & social", "max": 10, "pts": round(min(ns, 10)),
                      "coverage": "none" if len(ns_missing) == 2 else "partial" if ns_missing else "full",
                      "why": (f"Nuclear news {nuclear_ratio}× its 7-day average" if nuclear_ratio else "Nuclear news volume unavailable")
                             + (f"; Bluesky {bsky_ratio}×" if bsky_ratio else "")
                             + (f"; spiking topics: {', '.join(x['name'] for x in hot_topics)}" if hot_topics else "")
                             + (f"; unavailable: {', '.join(ns_missing)}" if ns_missing else "")})

    civ, civ_missing = 0.0, []
    if advisories is None:
        civ_missing.append("US travel advisories")
    else:
        civ += clamp(len(recent_l4) * 2, 0, 4) + clamp(len(ordered), 0, 3)
    if prep_ratio:
        civ += clamp((prep_ratio - 1) * 4, 0, 3)
    hot_wiki = [a for a in attention if a["ratio"] and a["ratio"] >= 2]
    civ += min(2, len(hot_wiki)) + min(3, 1.5 * len(fcdo_recent_avoid))
    if not fcdo:
        civ_missing.append("UK travel advice")
    vixm = next((m for m in markets if m["name"].startswith("VIX")), None)
    if vixm and (vixm["change_pct"] >= 20 or vixm["last"] >= 35):
        civ += 1
    breakdown.append({"name": "Civilian & diplomatic", "max": 10, "pts": round(min(civ, 10)),
                      "coverage": "partial" if civ_missing else "full",
                      "why": (f"{len(recent_l4)} new Level-4 advisories this week; {len(ordered)} ordered departures listed" if advisories is not None else "")
                             + (f"; preparedness news {prep_ratio}× normal" if prep_ratio else "")
                             + (f"; Wikipedia spikes: {', '.join(a['article'] for a in hot_wiki[:3])}" if hot_wiki else "")
                             + (f"; UK 'avoid all travel' updated for {', '.join(f['country'] for f in fcdo_recent_avoid[:3])}" if fcdo_recent_avoid else "")
                             + (f"; unavailable: {', '.join(civ_missing)}" if civ_missing else "")})

    raw_score = int(clamp(sum(b["pts"] for b in breakdown), 0, 100))
    score = None if insufficient else raw_score
    level = None if insufficient else 1 if score < 20 else 2 if score < 40 else 3 if score < 60 else 4 if score < 80 else 5
    statuses = list(tr.status.values())
    n_failed = sum(1 for s in statuses if s["state"] == "failed")
    n_stale = sum(1 for s in statuses if s["state"] == "stale")
    confidence = "NONE" if insufficient else "LOW" if days_of_history < 3 or n_failed > 6 else "MEDIUM" if days_of_history < 14 or n_failed else "HIGH"

    # ---- summary ---------------------------------------------------------------------------------
    if insufficient:
        headline = "Not enough data to rate the situation right now."
        parts = [f"Only {len(rated)} of {len(flashpoints)} flashpoints have news data this scan, so no index is given. "
                 "This is a data problem, not a sign that things are calm. See Data sources for details."]
    else:
        headline = {1: "Calm. No unusual signals.",
                    2: "Tense but stable. No sign that nuclear forces are changing posture.",
                    3: "Elevated. Several warning signs are moving at the same time.",
                    4: "High. Nuclear forces may be changing posture.",
                    5: "Severe. Many strategic warning signs at once."}[level]
        if level == 2 and strat >= 5:
            headline = "Tense. Some unusual military flight activity."
        parts = [f"The index is {score} ({LEVELS[level - 1]})."]
        if top:
            parts.append(f"The biggest political driver is {top['name']}, at rung {top['rung']} ({top['rung_name'].lower()})"
                         + (f", based on {top['stories_24h']} news reports in 24 hours." if top["stories_24h"] is not None else "."))
    if counts is not None:
        parts.append(f"Visible military aircraft: {counts['command']} command, {counts['bomber']} bomber, "
                     f"{counts['tanker']} tanker and {counts['recon']} recon"
                     + (" (from the last good scan)." if not ac_live else "."))
    else:
        parts.append("Military flight data is unavailable this scan.")
    if nuclear_ratio:
        parts.append(f"Nuclear-related news is at {nuclear_ratio}× its 7-day average.")
    if advisories is not None:
        parts.append(f"{len(recent_l4)} {'country was' if len(recent_l4) == 1 else 'countries were'} given or re-issued a Level 4 "
                     "(Do Not Travel) advisory this week." if recent_l4 else "No new Level-4 travel advisories this week.")
    if n_failed or n_stale:
        parts.append(f"{n_failed} sources failed and {n_stale} are showing older data.")

    changed = []
    if prev.get("score") is not None and score is not None and prev["score"] != score:
        changed.append(f"Index {'up' if score > prev['score'] else 'down'} from {prev['score']} to {score}")
    for f in flashpoints:
        if f["prev_rung"] and f["rung"] and f["prev_rung"] != f["rung"]:
            changed.append(f"{f['name']} moved from rung {f['prev_rung']} to {f['rung']}")
    for q in shallow[:1]:
        changed.append(f"Shallow M{q['mag']} quake {q['distance_km']} km from {q['site']}")
    for x in hot_topics[:2]:
        changed.append(f"News about '{x['name'].lower()}' at {x['ratio']}× normal")
    for a in hot_wiki[:1]:
        changed.append(f"Wikipedia views of '{a['article']}' at {a['ratio']}× normal")
    for f in flashpoints:
        if f["volume_ratio"] and f["volume_ratio"] > 1.5:
            changed.append(f"{f['name']}: news volume {f['volume_ratio']}× normal")
    if not changed:
        changed.append("No major changes since the last scan")

    out = {
        "updated": t.isoformat(),
        "score": score, "raw_score": raw_score, "level": level, "level_name": LEVELS[level - 1] if level else "INSUFFICIENT DATA",
        "confidence": confidence, "insufficient": insufficient,
        "coverage": {"flashpoints_rated": len(rated), "flashpoints_total": len(flashpoints),
                     "failed": n_failed, "stale": n_stale,
                     "not_configured": sum(1 for s in statuses if s["state"] == "not_configured")},
        "breakdown": breakdown,
        "summary": {"headline": headline, "text": " ".join(parts), "changed": changed[:7]},
        "flashpoints": flashpoints,
        "news": news[:60],
        "nuclear_news_ratio": nuclear_ratio,
        "gov": {"prep_news": (prep_arts or [])[:20], "prep_ratio": prep_ratio, "available": advisories is not None,
                "level4": [{"country": a["country"], "time": a["time"], "url": a["url"]} for a in level4],
                "recent_level4": recent_l4, "ordered_departures": ordered},
        "aircraft": {"feed": ac["feed"] if ac else None, "counts": counts, "tracks": aircraft, "live": ac_live},
        "social": {"posts": top_posts, "bluesky_per_hour": bsky_rate if "bsky" in snap else None,
                   "bluesky_ratio": bsky_ratio, "reddit_hits": reddit_hits},
        "social_extra": {"mastodon_per_hour": masto_count if masto_ok else None, "telegram_hits": tg_hits},
        "exercises": exercises,
        "topics": topics, "topic_articles": {},
        "seismic": (seismic or [])[:15] if seismic is not None else None,
        "nav_warnings": navwarn[:25] if navwarn is not None else None,
        "nav_total_active": nav["total_active"] if nav else None,
        "outages": outages, "attention": attention, "markets": markets, "statements": statements[:25],
        "fcdo": fcdo, "fires": fires,
        "history_days": round(days_of_history, 1),
        "sources": tr.status,
        "gdelt_requests_used": sources._gstate["used"],
        "errors": tr.errors(),
    }
    if score is not None:
        history[-1]["score"] = score
    out["score_history"] = [h["score"] for h in history[-200:] if h.get("score") is not None]
    save("latest.json", out)
    save("history.json", history)
    print(f"score {score} ({out['level_name']}) · {len(rated)}/{len(flashpoints)} flashpoints rated · "
          f"{len(news)} articles · {len(aircraft)} aircraft · GDELT requests {sources._gstate['used']} · "
          f"failed {n_failed} · stale {n_stale}")
    for k, v in sorted(tr.status.items()):
        if v["state"] in ("failed", "stale", "not_configured", "skipped"):
            print(f"  [{v['state']}] {k}: {v.get('error') or v.get('note')}")


if __name__ == "__main__":
    main()
