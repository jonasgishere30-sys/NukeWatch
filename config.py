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
