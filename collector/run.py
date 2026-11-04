"""One scan: fetch every source, score it, write data/latest.json + data/history.json.

Run from the project folder:   python -m collector.run
"""
import json
import os
import statistics
from datetime import datetime, timezone, timedelta

from . import config, sources

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
    need = max(config.MIN_HITS, round(0.08 * len(lower)))  # at least 3 headlines and 8% of coverage
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
    if len(vals) < min_samples:
        return None
    return statistics.median(vals)


def main():
    t = now()
    errors = {}
    prev = load("latest.json", {})
    history = load("history.json", [])

    # ---- flashpoints & news ------------------------------------------------
    flashpoints, news = [], []
    for fp in config.FLASHPOINTS:
        arts, err = sources.gdelt_articles(fp["query"], "24h", 75)
        if err:
            errors["news:" + fp["id"]] = err
        last24, daily_avg, verr = sources.gdelt_volume(fp["query"], "7d")
        if verr:
            errors["volume:" + fp["id"]] = verr
        rung, hits = rung_for([a["title"] for a in arts])
        ratio = (last24 / daily_avg) if (last24 is not None and daily_avg) else None
        prev_fp = next((p for p in prev.get("flashpoints", []) if p["id"] == fp["id"]), None)
        trend = "↑" if ratio and ratio > 1.25 else "↓" if ratio and ratio < 0.8 else "→"
        flashpoints.append({
            "id": fp["id"], "name": fp["name"], "short": fp["short"], "nukes": fp["nukes"],
            "lat": fp["lat"], "lon": fp["lon"], "zoom": fp["zoom"], "countries": fp["countries"],
            "rung": rung, "rung_name": config.RUNGS[rung - 1], "hits": hits,
            "stories_24h": last24 if last24 is not None else len(arts),
            "volume_ratio": round(ratio, 2) if ratio else None, "trend": trend,
            "prev_rung": prev_fp["rung"] if prev_fp else None,
            "latest": arts[0]["time"] if arts else None,
        })
        for a in arts[:15]:
            a["flashpoint"] = fp["id"]
            news.append(a)
    news.sort(key=lambda a: a.get("time") or "", reverse=True)

    nuc_last, nuc_avg, err = sources.gdelt_volume(config.NUCLEAR_NEWS_QUERY, "7d")
    if err:
        errors["volume:nuclear"] = err
    nuclear_ratio = round(nuc_last / nuc_avg, 2) if nuc_last is not None and nuc_avg else None

    # ---- government & civil defense ---------------------------------------
    prep_arts, err = sources.gdelt_articles(config.GOV_PREP_QUERY, "3d", 50)
    if err:
        errors["news:gov"] = err
    for a in prep_arts:
        low = a["title"].lower()
        a["type"] = next((name for name, kws in config.GOV_PREP_TYPES if any(k in low for k in kws)), "Preparedness")
    prep_last, prep_avg, err = sources.gdelt_volume(config.GOV_PREP_QUERY, "7d")
    if err:
        errors["volume:gov"] = err
    prep_ratio = round(prep_last / prep_avg, 2) if prep_last is not None and prep_avg else None

    advisories, err = sources.travel_advisories()
    if err:
        errors["advisories"] = err
    week_ago = (t - timedelta(days=7)).isoformat()
    level4 = [a for a in advisories if a["level"] == 4]
    recent_l4 = [a for a in level4 if (a["time"] or "") >= week_ago]
    ordered = [a for a in advisories if a["ordered_departure"]]

    # ---- aircraft -----------------------------------------------------------
    raw, feed, err = sources.military_aircraft()
    if err:
        errors["aircraft"] = err
    aircraft = sources.classify_aircraft(raw)
    counts = {c: sum(1 for a in aircraft if a["category"] == c and not a["ground"]) for c in config.AIRCRAFT_TYPES}

    # ---- social -------------------------------------------------------------
    posts, bsky_rate = [], 0
    hour_ago = (t - timedelta(hours=1)).isoformat()
    for q in config.BLUESKY_QUERIES:
        ps, err = sources.bluesky_search(q, 100)
        if err:
            errors["bluesky"] = err
            break
        bsky_rate += sum(1 for p in ps if (p["time"] or "") >= hour_ago)
        for p in ps:
            p["query"] = q
        posts += ps
    reddit_hits = 0
    for sub in config.REDDIT_SUBS:
        ps, err = sources.reddit_new(sub)
        if err:
            errors["reddit:" + sub] = err
            continue
        for p in ps:
            low = p["text"].lower()
            if any(k in low for k in config.REDDIT_TERMS):
                reddit_hits += 1
                p["query"] = "keyword match"
                posts.append(p)
    # Mastodon public hashtags
    masto_count = 0
    for tag in config.MASTODON_TAGS:
        ps, err = sources.mastodon_tag(tag)
        if err:
            errors["mastodon"] = err
            break
        recent = [p for p in ps if (p["time"] or "") >= hour_ago]
        masto_count += len(recent)
        posts += [p for p in ps if any(k in p["text"].lower() for k in config.REDDIT_TERMS)]
    # Telegram public channels (configure in config.TELEGRAM_CHANNELS)
    tg_hits = 0
    for ch in config.TELEGRAM_CHANNELS:
        ps, err = sources.telegram_channel(ch)
        if err:
            errors["telegram:" + ch] = err
            continue
        for p in ps:
            if any(k in p["text"].lower() for k in config.TELEGRAM_KEYWORDS):
                tg_hits += 1
                p["query"] = "keyword match"
                posts.append(p)

    # ---- extra signals --------------------------------------------------------
    topics = []
    for name, q in config.TOPIC_QUERIES:
        last24, avg, err = sources.gdelt_volume(q, "7d")
        if err:
            errors["topic:" + name] = err
            continue
        topics.append({"name": name, "last24": last24, "daily_avg": round(avg, 1) if avg else None,
                       "ratio": round(last24 / avg, 2) if avg else None})
    topic_arts = {}
    for name, q in config.TOPIC_QUERIES[:3]:
        arts, err = sources.gdelt_articles(q, "24h", 10)
        if not err:
            topic_arts[name] = arts[:5]

    seismic, err = sources.seismic_near_test_sites()
    if err:
        errors["seismic"] = err
    navwarn, err = sources.nga_warnings()
    if err:
        errors["nav_warnings"] = err
    outages, err = sources.internet_outages(config.OUTAGE_COUNTRIES)
    if err:
        errors["internet_outages"] = err

    attention = []
    for art in config.WIKI_ARTICLES:
        r, err = sources.wiki_pageviews(art)
        if err:
            errors["wikipedia"] = err
            continue
        attention.append(r)
    attention.sort(key=lambda a: -(a["ratio"] or 0))

    markets = []
    m, err = sources.vix()
    if err:
        errors["market:vix"] = err
    else:
        markets.append(m)
    for sym, label in config.MARKETS:
        m, err = sources.stooq(sym, label)
        if err:
            errors["market:" + sym] = err
        else:
            markets.append(m)

    statements = []
    for name, url in config.OFFICIAL_FEEDS:
        items, err = sources.rss_items(url, name)
        if err:
            errors["feed:" + name] = err
            continue
        for it in items:
            low = (it["title"] + " " + it["summary"]).lower()
            hit = [k for k in config.OFFICIAL_KEYWORDS if k in low]
            if hit:
                it["source"] = name
                it["matched"] = hit[:4]
                statements.append(it)
    statements.sort(key=lambda x: x.get("time") or "", reverse=True)

    fcdo = []
    for slug in config.FCDO_SLUGS:
        r, err = sources.fcdo_advice(slug)
        if err:
            errors["fcdo"] = err
            continue
        fcdo.append(r)
    fcdo.sort(key=lambda x: x.get("updated") or "", reverse=True)
    fcdo_recent_avoid = [f for f in fcdo if f["avoid_all"] and (f["updated"] or "") >= week_ago]

    fires = []
    fkey = os.environ.get("FIRMS_MAP_KEY")
    if fkey:
        for name, bbox in config.FIRMS_AREAS:
            n, err = sources.firms_hotspots(bbox, fkey)
            if err:
                errors["firms"] = err
            else:
                fires.append({"area": name, "hotspots_24h": n})

    seen, uniq = set(), []
    for p in sorted(posts, key=lambda p: (p.get("likes", 0) + 2 * p.get("reposts", 0)), reverse=True):
        k = p["text"][:80]
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    top_posts = uniq[:12]

    # ---- history & baselines ------------------------------------------------
    snap = {"t": t.isoformat(), "command": counts["command"], "bomber": counts["bomber"],
            "tanker": counts["tanker"], "recon": counts["recon"], "bsky": bsky_rate if "bluesky" not in errors else None,
            "reddit": reddit_hits, "masto": masto_count if "mastodon" not in errors else None,
            "airlift": counts.get("airlift", 0),
            "missile_warn": sum(1 for w in navwarn if w["type"] == "Missile / rocket") if "nav_warnings" not in errors else None,
            "fires": {f["area"]: f["hotspots_24h"] for f in fires} or None}
    history.append(snap)
    history = history[-config.HISTORY_MAX:]
    days_of_history = 0
    if history:
        try:
            days_of_history = (t - datetime.fromisoformat(history[0]["t"])).total_seconds() / 86400
        except ValueError:
            pass

    # ---- score ----------------------------------------------------------------
    exercises = active_exercises(t)
    affected = {c for ex in exercises for c in ex.get("affects", [])}
    breakdown = []

    top = max(flashpoints, key=lambda f: (f["rung"], f["stories_24h"] or 0)) if flashpoints else None
    # The worst flashpoint counts in full, the others at half weight.
    pol = 0
    if top:
        pol = RUNG_POINTS[top["rung"]] + 0.5 * sum(RUNG_POINTS[f["rung"]] for f in flashpoints if f is not top)
    pol = round(min(40, pol))
    breakdown.append({"name": "Political flashpoints", "max": 40, "pts": pol,
                      "why": ", ".join(f"{f['short']} rung {f['rung']}" for f in sorted(flashpoints, key=lambda f: -f["rung"])[:3])})

    strat, notes = 0.0, []
    for cat in ("command", "bomber", "tanker", "airlift"):
        b = baseline(history[:-1], cat)
        if b is None:
            notes.append(f"{cat}: building baseline")
            continue
        r = counts[cat] / max(b, 1)
        pts = clamp((r - 1.3) * (5 if cat == "airlift" else 10), 0, 10 if cat != "airlift" else 5)
        if cat in affected:
            pts /= 2
        strat += pts
        notes.append(f"{cat} {counts[cat]} vs normal {b:g}")
    strat = round(strat)
    breakdown.append({"name": "Strategic forces", "max": 30, "pts": strat,
                      "why": "; ".join(notes) + ("; exercise down-weighting on" if affected else "")})

    sig, sig_notes = 0.0, []
    shallow = [q for q in seismic if q["shallow"] and (q["time"] or "") >= (t - timedelta(days=2)).isoformat()]
    if shallow:
        sig += 5
        sig_notes.append(f"shallow quake near {shallow[0]['site']}")
    b_mw = baseline(history[:-1], "missile_warn")
    mw = snap.get("missile_warn")
    if mw is not None:
        if b_mw is not None and mw > b_mw * 1.5 + 1:
            sig += 3
        sig_notes.append(f"{mw} active missile/rocket sea warnings" + (f" (normal {b_mw:g})" if b_mw is not None else ""))
    big_out = [o for o in outages if o["score"] >= 1000]
    if big_out:
        sig += min(2, len(big_out))
        sig_notes.append("internet outages: " + ", ".join(o["name"] for o in big_out[:3]))
    sig = round(min(sig, 10))
    breakdown.append({"name": "Command & signals", "max": 10, "pts": sig,
                      "why": "; ".join(sig_notes) or "No unusual seismic, maritime or internet signals."})

    ns = 0.0
    if nuclear_ratio:
        ns += clamp((nuclear_ratio - 1) * 8, 0, 6)
    b_bsky = baseline(history[:-1], "bsky")
    bsky_ratio = round(bsky_rate / max(b_bsky, 1), 2) if b_bsky is not None and "bluesky" not in errors else None
    if bsky_ratio:
        ns += clamp((bsky_ratio - 1) * 4, 0, 4)
    hot_topics = [x for x in topics if x["ratio"] and x["ratio"] >= 1.8]
    if hot_topics:
        ns += min(2, len(hot_topics))
    ns = round(min(ns, 10))
    breakdown.append({"name": "News & social", "max": 10, "pts": ns,
                      "why": f"Nuclear news {nuclear_ratio or '?'}× its 7-day average; Bluesky {bsky_ratio or 'baseline building'}"
                             + (f"; spiking topics: {', '.join(x['name'] for x in hot_topics)}." if hot_topics else ".")})

    civ = clamp(len(recent_l4) * 2, 0, 4) + clamp(len(ordered), 0, 3)
    if prep_ratio:
        civ += clamp((prep_ratio - 1) * 4, 0, 3)
    hot_wiki = [a for a in attention if a["ratio"] and a["ratio"] >= 2]
    civ += min(2, len(hot_wiki))
    civ += min(3, 1.5 * len(fcdo_recent_avoid))
    vixm = next((m for m in markets if m["name"].startswith("VIX")), None)
    if vixm and (vixm["change_pct"] >= 20 or vixm["last"] >= 35):
        civ += 1
    civ = round(min(civ, 10))
    breakdown.append({"name": "Civilian & diplomatic", "max": 10, "pts": civ,
                      "why": f"{len(recent_l4)} new Level-4 advisories this week; {len(ordered)} ordered departures listed; preparedness news {prep_ratio or '?'}× normal"
                             + (f"; Wikipedia spikes: {', '.join(a['article'] for a in hot_wiki[:3])}" if hot_wiki else "")
                             + (f"; UK 'avoid all travel' updated for {', '.join(f['country'] for f in fcdo_recent_avoid[:3])}" if fcdo_recent_avoid else "") + "."})

    score = int(clamp(sum(b["pts"] for b in breakdown), 0, 100))
    level = 1 if score < 20 else 2 if score < 40 else 3 if score < 60 else 4 if score < 80 else 5
    confidence = "LOW" if days_of_history < 3 or len(errors) > 4 else "MEDIUM" if days_of_history < 14 else "HIGH"

    # ---- summary ---------------------------------------------------------------
    headline = {
        1: "Calm. No unusual signals.",
        2: "Tense but stable. No sign that nuclear forces are changing posture.",
        3: "Elevated. Several warning signs are moving at the same time.",
        4: "High. Nuclear forces may be changing posture.",
        5: "Severe. Many strategic warning signs at once.",
    }[level]
    if level == 2 and strat >= 5:
        headline = "Tense. Some unusual military flight activity."
    parts = [f"The index is {score} ({LEVELS[level - 1]})."]
    if top:
        parts.append(f"The biggest political driver is {top['name']}, at rung {top['rung']} ({top['rung_name'].lower()}), "
                     f"based on {top['stories_24h']} news reports in 24 hours.")
    if feed:
        parts.append(f"Visible military aircraft right now: {counts['command']} command, {counts['bomber']} bomber, "
                     f"{counts['tanker']} tanker and {counts['recon']} recon.")
    if nuclear_ratio:
        parts.append(f"Nuclear-related news is at {nuclear_ratio}× its 7-day average.")
    parts.append(f"{len(recent_l4)} {'country was' if len(recent_l4) == 1 else 'countries were'} given or re-issued a Level 4 (Do Not Travel) advisory this week." if recent_l4
                 else "No new Level-4 travel advisories this week.")
    changed = []
    if prev.get("score") is not None and prev["score"] != score:
        changed.append(f"Index {'up' if score > prev['score'] else 'down'} from {prev['score']} to {score}")
    for f in flashpoints:
        if f["prev_rung"] and f["prev_rung"] != f["rung"]:
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
        "score": score, "level": level, "level_name": LEVELS[level - 1], "confidence": confidence,
        "breakdown": breakdown,
        "summary": {"headline": headline, "text": " ".join(parts), "changed": changed[:7]},
        "flashpoints": flashpoints,
        "news": news[:60],
        "nuclear_news_ratio": nuclear_ratio,
        "gov": {"prep_news": prep_arts[:20], "prep_ratio": prep_ratio,
                "level4": [{"country": a["country"], "time": a["time"], "url": a["url"]} for a in level4],
                "recent_level4": recent_l4, "ordered_departures": ordered},
        "aircraft": {"feed": feed, "counts": counts, "tracks": aircraft},
        "social": {"posts": top_posts, "bluesky_per_hour": bsky_rate if "bluesky" not in errors else None,
                   "bluesky_ratio": bsky_ratio, "reddit_hits": reddit_hits},
        "exercises": exercises,
        "topics": topics, "topic_articles": topic_arts,
        "seismic": seismic[:15], "nav_warnings": navwarn[:25], "outages": outages,
        "attention": attention, "markets": markets, "statements": statements[:25],
        "fcdo": fcdo, "fires": fires,
        "social_extra": {"mastodon_per_hour": masto_count if "mastodon" not in errors else None, "telegram_hits": tg_hits},
        "history_days": round(days_of_history, 1),
        "score_history": [h.get("score") for h in history[-200:] if h.get("score") is not None],
        "errors": errors,
    }
    history[-1]["score"] = score
    out["score_history"].append(score)
    save("latest.json", out)
    save("history.json", history)
    print(f"score {score} ({LEVELS[level - 1]}) · {len(news)} articles · {len(aircraft)} aircraft · "
          f"{len(top_posts)} posts · errors: {list(errors) or 'none'}")


if __name__ == "__main__":
    main()
