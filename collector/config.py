"""All the settings you are likely to edit live here."""

USER_AGENT = "NukeWatch/0.1 (+https://github.com/YOUR-USERNAME/nuke-watch)"

# ---------------------------------------------------------------------------
# Flashpoints: political hotspots that involve a nuclear-armed state.
# query     -> GDELT news search (https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/)
# countries -> ISO numeric codes shaded on the map, by role:
#              party = the two sides, involved = allies sending troops/arms/aid or bases,
#              threatened = neighbors on the front line or under the missile path
# ---------------------------------------------------------------------------
FLASHPOINTS = [
    {
        "id": "ru", "name": "Russia – Ukraine / NATO", "short": "RU–UA",
        "nukes": "RU · US · UK · FR", "lat": 51, "lon": 33, "zoom": 5,
        "countries": {
            "party": ["643", "804"],                      # Russia, Ukraine
            "involved": ["112", "408", "364", "840", "826", "250", "276", "616"],  # Belarus (hosts Russian nukes), North Korea (troops), Iran (drones), US, UK, France, Germany, Poland (arms & aid)
            "threatened": ["440", "428", "233", "246", "642", "498"],  # Baltics, Finland, Romania, Moldova (NATO front line)
        },
        "query": '(Russia OR Ukraine OR Kremlin OR Putin OR Zelensky) (war OR attack OR strike OR nuclear OR missile OR troops OR NATO)',
    },
    {
        "id": "me", "name": "Israel – Iran", "short": "IL–IR",
        "nukes": "IL (undeclared)", "lat": 32, "lon": 44, "zoom": 5,
        "countries": {
            "party": ["376", "364"],                      # Israel, Iran
            "involved": ["422", "760", "887", "368", "275", "840"],  # Lebanon (Hezbollah), Syria, Yemen (Houthis), Iraq (militias), Palestine, US
            "threatened": [],
        },
        "query": '(Israel OR Iran OR Tehran OR IDF OR Hezbollah) (attack OR strike OR missile OR nuclear OR war)',
    },
    {
        "id": "sa", "name": "India – Pakistan", "short": "IN–PK",
        "nukes": "IN · PK", "lat": 31, "lon": 72, "zoom": 5,
        "countries": {
            "party": ["356", "586"],                      # India, Pakistan
            "involved": ["156"],                          # China (Pakistan ally, disputed border with India)
            "threatened": [],
        },
        "query": '(India OR Pakistan) (Kashmir OR "Line of Control" OR military OR missile OR nuclear OR border)',
    },
    {
        "id": "tw", "name": "China – Taiwan / US", "short": "TAIWAN STR.",
        "nukes": "CN · US", "lat": 24.5, "lon": 120.5, "zoom": 6,
        "countries": {
            "party": ["156", "158"],                      # China, Taiwan
            "involved": ["840"],                          # US (defense commitments)
            "threatened": ["392", "608", "410"],          # Japan, Philippines, South Korea (US bases nearby)
        },
        "query": '(Taiwan OR "Taiwan Strait" OR PLA) (military OR drills OR aircraft OR warships OR blockade OR invasion)',
    },
    {
        "id": "kr", "name": "Korean Peninsula", "short": "KOREA",
        "nukes": "KP · US", "lat": 39, "lon": 127, "zoom": 6,
        "countries": {
            "party": ["408", "410"],                      # North Korea, South Korea
            "involved": ["840", "643", "156"],            # US (troops in South Korea), Russia (defense pact with North Korea), China
            "threatened": ["392"],                        # Japan (missiles fly over it)
        },
        "query": '("North Korea" OR Pyongyang OR "Kim Jong Un") (missile OR nuclear OR launch OR military OR test)',
    },
    {
        "id": "ar", "name": "Greenland / Arctic", "short": "ARCTIC",
        "nukes": "US · RU", "lat": 72, "lon": -42, "zoom": 3,
        "countries": {
            "party": ["304", "208"],                      # Greenland, Denmark
            "involved": ["840", "643"],                   # US, Russia (Arctic military buildup)
            "threatened": ["124"],                        # Canada
        },
        "query": '(Greenland OR Arctic) (military OR Russia OR NATO OR annex OR troops OR security)',
    },
]

# Escalation ladder. Each flashpoint is placed on a rung from its last 24h of headlines.
RUNGS = [
    "Rhetoric & sanctions",
    "Buildup & missile tests",
    "Conventional fighting",
    "Nuclear signaling",
    "Strategic forces moving",
    "Nuclear use",
]

# Words in headlines that point to each rung (lower case). A rung needs MIN_HITS headlines.
RUNG_KEYWORDS = {
    4: ["nuclear weapon", "nuclear strike", "nuclear threat", "nuclear doctrine", "nuclear war",
        "nuclear drill", "nuclear-capable", "nuclear capable", "tactical nuclear", "warhead",
        "icbm", "nuclear forces", "nuclear arsenal", "nuclear option", "nuclear escalation"],
    3: ["airstrike", "air strike", "strikes", "struck", "shelling", "killed", "attack", "attacks",
        "drone strike", "offensive", "bombardment", "clashes", "missile hit", "ceasefire violation"],
    2: ["drill", "drills", "exercise", "troops", "buildup", "build-up", "deploy", "missile test",
        "test-fire", "test fire", "fires missile", "launches missile", "mobiliz", "warships", "military exercise"],
    1: ["sanction", "warns", "warning", "threat", "condemn", "tension", "diplomat", "talks", "summit"],
}
MIN_HITS = 3

# General nuclear-news volume (compared with its own 7-day average).
NUCLEAR_NEWS_QUERY = '("nuclear war" OR "nuclear weapon" OR "nuclear weapons" OR "nuclear threat" OR "nuclear strike")'

# Government preparedness / civil-defense news.
GOV_PREP_QUERY = ('("stockpile supplies" OR "emergency supplies" OR "bomb shelter" OR "bomb shelters" OR '
                  '"civil defense" OR "civil defence" OR "iodine tablets" OR "air raid shelter" OR '
                  '"reservists" OR "mobilization" OR "emergency preparedness")')
GOV_PREP_TYPES = [
    ("Stock-up advice", ["stockpile", "emergency supplies", "72 hours", "self-sufficient"]),
    ("Shelters", ["shelter", "bunker"]),
    ("Iodine", ["iodine"]),
    ("Mobilization", ["reservist", "mobiliz", "mobilis", "conscript"]),
    ("Civil defense", ["civil defense", "civil defence", "siren", "evacuation"]),
]

# ---------------------------------------------------------------------------
# Military aircraft (ICAO type codes from the ADS-B military feed).
# ---------------------------------------------------------------------------
AIRCRAFT_TYPES = {
    "command": {"E6": "E-6B Mercury (TACAMO)", "E4": "E-4B Nightwatch", "E4B": "E-4B Nightwatch"},
    "bomber": {"B52": "B-52 Stratofortress", "B2": "B-2 Spirit", "B1": "B-1B Lancer",
               "TU95": "Tu-95 Bear", "T160": "Tu-160 Blackjack", "TU22": "Tu-22M Backfire"},
    "tanker": {"K35R": "KC-135R Stratotanker", "K35E": "KC-135E", "KC46": "KC-46 Pegasus",
               "K46": "KC-46 Pegasus", "DC10": "KC-10 Extender", "A332": "A330 MRTT (check)"},
    "airlift": {"C17": "C-17 Globemaster III", "C5M": "C-5M Super Galaxy", "A400": "A400M Atlas", "IL76": "Il-76"},
    "recon": {"R135": "RC-135", "E3TF": "E-3 Sentry (AWACS)", "E3CF": "E-3 Sentry (AWACS)",
              "P8": "P-8A Poseidon", "Q4": "RQ-4 Global Hawk", "U2": "U-2"},
}

# ---------------------------------------------------------------------------
# Social media
# ---------------------------------------------------------------------------
BLUESKY_QUERIES = ["nuclear war", "nuclear strike", "air raid siren", "nuclear threat", "bomb shelter"]
REDDIT_SUBS = ["worldnews", "geopolitics", "CredibleDefense"]
REDDIT_TERMS = ["nuclear", "icbm", "warhead", "missile", "mobiliz", "evacuat", "shelter"]

# ---------------------------------------------------------------------------
# Military exercises. Add known drills here so they do not raise the index.
# affects: any of "command", "bomber", "tanker", "recon"
# ---------------------------------------------------------------------------
EXERCISES = [
    # {"name": "Global Thunder", "start": "2026-10-20", "end": "2026-11-05", "affects": ["command", "bomber", "tanker"]},
]

# How many entries of history to keep (one per run; 15-min runs -> ~30 days).
HISTORY_MAX = 3000


# ===========================================================================
# EXTRA SIGNALS
# ===========================================================================

# Topic radar: news volume for each topic vs its own 7-day average (GDELT).
TOPIC_QUERIES = [
    ("Nuclear test", '("nuclear test" OR "underground test" OR "test site")'),
    ("Missile launch", '("ballistic missile" OR "missile launch" OR "ICBM launch" OR "hypersonic missile")'),
    ("Mobilization", '(mobilization OR mobilisation OR conscription OR "reservists called")'),
    ("Evacuation", '(evacuation OR evacuate) (embassy OR citizens OR nationals)'),
    ("Air raid / sirens", '("air raid" OR "air-raid" OR "sirens sounded" OR "missile alert")'),
    ("Cyberattack", '(cyberattack OR "cyber attack" OR "power grid attack" OR blackout) (Russia OR China OR Iran OR "North Korea")'),
    ("Nuclear plant / radiation", '("radiation levels" OR "nuclear plant" OR Zaporizhzhia OR "radioactive")'),
    ("Strategic forces", '("nuclear forces" OR "strategic bombers" OR "nuclear submarine" OR "nuclear triad" OR DEFCON)'),
]

# Known nuclear test sites. Shallow quakes nearby get flagged (most will still be natural or mining).
TEST_SITES = [
    {"name": "Punggye-ri (North Korea)", "lat": 41.28, "lon": 129.08, "radius_km": 120},
    {"name": "Novaya Zemlya (Russia)", "lat": 73.37, "lon": 54.97, "radius_km": 200},
    {"name": "Lop Nur (China)", "lat": 41.55, "lon": 88.35, "radius_km": 150},
    {"name": "Nevada test site (US)", "lat": 37.12, "lon": -116.05, "radius_km": 80},
    {"name": "Pokhran (India)", "lat": 27.08, "lon": 71.75, "radius_km": 80},
    {"name": "Ras Koh (Pakistan)", "lat": 28.83, "lon": 64.95, "radius_km": 80},
]

# Maritime warnings that matter (NGA). First match wins.
NAV_WARNING_TYPES = [
    ("Missile / rocket", ["missile", "rocket", "space debris", "launch"]),
    ("Firing exercise", ["gunnery", "firing exercise", "live fire", "hazardous operations", "military exercise"]),
    ("Submarine ops", ["submarine"]),
]

# Countries watched for internet outages (ISO 2-letter codes).
OUTAGE_COUNTRIES = {"RU": "Russia", "UA": "Ukraine", "BY": "Belarus", "IR": "Iran", "IL": "Israel", "LB": "Lebanon",
                    "SY": "Syria", "IN": "India", "PK": "Pakistan", "CN": "China", "TW": "Taiwan", "KP": "North Korea",
                    "KR": "South Korea", "PL": "Poland", "EE": "Estonia", "LV": "Latvia", "LT": "Lithuania", "FI": "Finland"}

# Public attention: English Wikipedia pageviews vs their 30-day median.
WIKI_ARTICLES = ["Potassium_iodide", "Fallout_shelter", "Nuclear_warfare", "DEFCON", "Nuclear_fallout",
                 "Doomsday_Clock", "Emergency_Alert_System", "Nuclear_winter", "Bomb_shelter", "Mutual_assured_destruction"]

# Markets (stooq.com symbols). VIX comes from Cboe directly.
MARKETS = [("xauusd", "Gold (USD)"), ("cl.f", "Crude oil"), ("ita.us", "US defense stocks (ITA)"), ("^spx", "S&P 500")]

# Official statements: RSS feeds, filtered by keyword. Broken feeds are skipped and shown as errors.
OFFICIAL_FEEDS = [
    ("NATO", "https://www.nato.int/cps/rss/en/natohq/rssFeed.xsl/rssFeed.xml"),
    ("US Dept of Defense", "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=20"),
    ("US State Dept", "https://www.state.gov/rss-feed/press-releases/feed/"),
    ("Kremlin", "http://en.kremlin.ru/events/president/news/feed"),
    ("UN press", "https://press.un.org/en/rss.xml"),
    ("IAEA", "https://www.iaea.org/feeds/topnews"),
    ("UK Gov (defence)", "https://www.gov.uk/search/news-and-communications.atom?organisations%5B%5D=ministry-of-defence"),
]
OFFICIAL_KEYWORDS = ["nuclear", "missile", "deterr", "strategic", "mobiliz", "escalat", "warhead", "icbm", "evacuat",
                     "security council", "ultimatum", "red line", "retaliat", "sanction", "alert", "readiness"]

# UK Foreign Office travel advice pages to watch (gov.uk slugs). "Avoid all travel" changes are a strong signal.
FCDO_SLUGS = ["russia", "ukraine", "belarus", "israel", "iran", "lebanon", "syria", "iraq", "india", "pakistan",
              "china", "taiwan", "north-korea", "south-korea", "japan", "poland", "estonia", "latvia", "lithuania", "moldova"]

# Social: public Mastodon hashtags (no account needed).
MASTODON_TAGS = ["nuclear", "nuclearwar", "ukraine", "iran", "taiwan", "osint"]

# Telegram: public channel usernames to read via t.me/s/<name>. Add OSINT / news channels you trust.
TELEGRAM_CHANNELS = []
TELEGRAM_KEYWORDS = ["nuclear", "missile", "iskander", "yars", "sarmat", "bomber", "submarine", "mobiliz", "evacuat",
                     "air raid", "ядер", "ракет"]

# NASA FIRMS fire hotspots in conflict zones (needs free key in FIRMS_MAP_KEY secret). west,south,east,north
FIRMS_AREAS = [("Ukraine & W. Russia", "22,44,45,56"), ("Israel / Lebanon / Iran", "34,29,60,38")]
