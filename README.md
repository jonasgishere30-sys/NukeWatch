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
| GDELT topic radar | News volume for nuclear tests, missile launches, mobilization, evacuations, air raids, cyberattacks, radiation, strategic forces | No |
| USGS earthquakes | Shallow quakes near the six nuclear test sites | No |
| NGA maritime warnings | Active missile / rocket / firing-area warnings to ships | No |
| IODA (Georgia Tech) | Internet outages in 18 watched countries | No |
| Wikipedia pageviews | Public attention: potassium iodide, fallout shelter, DEFCON and more | No |
| Cboe + Stooq | VIX, gold, oil, defense stocks, S&P 500 | No |
| NATO, DoD, State, Kremlin, UN, IAEA, UK MoD RSS | Official statements filtered for escalation keywords | No |
| UK Foreign Office | "Avoid all travel" changes for 20 countries | No |
| Mastodon | Public hashtag posts | No |
| Telegram | Public channels you list in `config.TELEGRAM_CHANNELS` | No |
| NASA FIRMS | Fire hotspots in conflict zones | Free key → secret `FIRMS_MAP_KEY` |

Not connected yet: FAA NOTAMs (needs FAA API approval), HF radio logs (no public feed), satellite images of submarine bases, ship tracking (AIS feeds are paid).

## Put it online (GitHub Pages)

1. Keep `index.html` at the repository root, front-end files inside `assets/`, and Python modules inside `collector/`.
2. In repository Settings → Pages → Build and deployment, set Source to **GitHub Actions**.
3. Add any optional credentials as repository Actions secrets; never put passwords or API keys in front-end files.
4. After the complete release is merged into `main`, open Actions → **Build and deploy NukeWatch**. A push to `main` starts deployment; the workflow can also be run manually.
5. Wait for the workflow to finish successfully. External sources may be unavailable; the dashboard reports source errors rather than guaranteeing complete coverage.
6. For this repository, the expected Pages address is `https://jonasgishere30-sys.github.io/NukeWatch/`. Check the deployment result for the actual published URL. Scheduled runs request updates every 15 minutes; execution can be delayed.

### Optional: NASA fire hotspots
Get a free MAP_KEY at https://firms.modaps.eosdis.nasa.gov/api/map_key/ and add it as the secret `FIRMS_MAP_KEY`.

### Optional: Telegram
Add public channel usernames to `TELEGRAM_CHANNELS` in `collector/config.py`.

### Optional: Bluesky
Bluesky search works best when logged in. Create an **app password** in Bluesky (Settings → Privacy and security → App passwords),
then in GitHub go to **Settings → Secrets and variables → Actions → New repository secret** and add
`BSKY_HANDLE` (e.g. `you.bsky.social`) and `BSKY_APP_PASSWORD`.

## Run it on your own computer

Needs Python 3.10+ (no extra packages).

```powershell
cd nuke-watch
python -m collector.run          # one live scan; may take several minutes
python -m http.server 8000       # then open http://localhost:8000
```

Offline test with fake data: `python tests/make_fixtures.py` then
`set NUKEWATCH_FIXTURES=tests\fixtures` (PowerShell: `$env:NUKEWATCH_FIXTURES="tests\fixtures"`) and run the collector.
Never publish fixture-generated dashboard data as live observations.

## Tuning

Everything you are likely to change is in `collector/config.py`:
flashpoints and their news searches, the keywords that place a flashpoint on the escalation ladder,
aircraft types, social media search terms, and **`EXERCISES`** (add scheduled military drills so they do not raise the index).

## How the index is scored (0–100)

| Part | Max | How |
|---|---|---|
| Political flashpoints | 40 | Worst flashpoint's rung in full + others at half weight |
| Strategic forces | 30 | Command / bomber / tanker / airlift aircraft vs their own median (needs ~12h of history; halved during listed exercises) |
| Command & signals | 10 | Shallow quakes at test sites, spikes in missile sea warnings, major internet outages |
| News & social | 10 | Nuclear-news volume, topic-radar spikes, Bluesky volume vs history |
| Civilian & diplomatic | 10 | Level-4 advisories, ordered departures, UK 'avoid all travel' changes, preparedness news, Wikipedia spikes, VIX jumps |

Levels: 0–19 Baseline · 20–39 Watch · 40–59 Elevated · 60–79 High · 80–100 Severe.

The ladder placement is automatic keyword matching on headlines, so it can be wrong. Read the stories.

Article photos and headlines belong to their publishers; the site shows them as linked previews back to the original story.
