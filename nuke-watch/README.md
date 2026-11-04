# NukeWatch

An open-source dashboard that tracks public signals that could point toward nuclear escalation:
political flashpoints, world news (with article photos), government warnings, military aircraft and social media.

It is context, not a warning system. Launch orders and most submarine movements are classified.

## How it works

```
GitHub Actions (every 15 min)  →  python -m collector.run  →  data/latest.json  →  GitHub Pages site (index.html)
```

| Source | What it gives | Key needed |
|---|---|---|
| GDELT DOC 2.0 API | Headlines, article photos, news volume per flashpoint | No |
| U.S. State Dept travel advisories (RSS) | Level 4 "Do Not Travel", ordered departures | No |
| airplanes.live / adsb.fi military feed | Live positions of command, bomber, tanker, recon aircraft | No |
| Bluesky search | Posts about nuclear war, sirens, shelters | Optional (app password, recommended) |
| Reddit | Matching posts from r/worldnews, r/geopolitics, r/CredibleDefense | No (may be blocked from GitHub) |

Not connected yet (phase 2): FAA NOTAMs, HF radio logs, satellite images of submarine bases.

## Put it online (GitHub Pages)

1. Create a **public** repo on GitHub called `nuke-watch`.
2. Upload everything in this folder (keep the hidden `.github` folder: in GitHub Desktop it is included automatically).
3. Repo **Settings → Pages → Build and deployment → Source: Deploy from a branch → `main` / `(root)` → Save**.
4. Repo **Settings → Actions → General → Workflow permissions → Read and write permissions → Save**.
5. **Actions** tab → enable workflows → click **scan** → **Run workflow**.
6. After about 2 minutes your site is live at `https://<your-username>.github.io/nuke-watch/`.
   From then on it updates itself every 15 minutes.

### Optional: Bluesky
Bluesky search works best when logged in. Create an **app password** in Bluesky (Settings → Privacy and security → App passwords),
then in GitHub go to **Settings → Secrets and variables → Actions → New repository secret** and add
`BSKY_HANDLE` (e.g. `you.bsky.social`) and `BSKY_APP_PASSWORD`.

## Run it on your own computer

Needs Python 3.10+ (no extra packages).

```powershell
cd nuke-watch
python -m collector.run          # one scan, writes data/latest.json (takes ~2 minutes)
python -m http.server 8000       # then open http://localhost:8000
```

Offline test with fake data: `python tests/make_fixtures.py` then
`set NUKEWATCH_FIXTURES=tests\fixtures` (PowerShell: `$env:NUKEWATCH_FIXTURES="tests\fixtures"`) and run the collector.

## Tuning

Everything you are likely to change is in `collector/config.py`:
flashpoints and their news searches, the keywords that place a flashpoint on the escalation ladder,
aircraft types, social media search terms, and **`EXERCISES`** (add scheduled military drills so they do not raise the index).

## How the index is scored (0–100)

| Part | Max | How |
|---|---|---|
| Political flashpoints | 40 | Worst flashpoint's rung in full + others at half weight |
| Strategic forces | 30 | Command / bomber / tanker aircraft vs their own median (needs ~12h of history; halved during listed exercises) |
| Command & signals | 10 | Phase 2 (NOTAMs, HF radio) |
| News & social | 10 | Nuclear-news volume vs 7-day average, Bluesky volume vs history |
| Civilian & diplomatic | 10 | New Level-4 advisories, ordered departures, preparedness-news volume |

Levels: 0–19 Baseline · 20–39 Watch · 40–59 Elevated · 60–79 High · 80–100 Severe.

The ladder placement is automatic keyword matching on headlines, so it can be wrong. Read the stories.

Article photos and headlines belong to their publishers; the site shows them as linked previews back to the original story.
