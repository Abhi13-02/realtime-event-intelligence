"""
test_gdelt_mock.py  —  GDELT integration flow mock test
========================================================

ONLY MOCK THING: the list of topic names (simulating what users create via POST /topics).
Everything else is real:
  - Fetches the actual GDELT GKG theme list from the live URL
  - Uses LangChain + ChatCohere (same as LangchainCohereAdapter in production)
    to map each topic -> best matching GDELT theme from the official list
  - Deduplicates themes in a set (no re-querying the same theme twice)
  - Builds the real GDELT query and fires it live
  - Displays article results at each stage

Run from project root:
    python tests/test_gdelt_mock.py
"""

import os
import sys
import time
import requests
from pathlib import Path

# ── Load .env manually (avoids pulling in the full Docker-wired app stack) ────
def _load_env(path: str = ".env") -> None:
    try:
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:   # don't override existing env vars
                os.environ[k] = v
    except FileNotFoundError:
        pass

_load_env()

# Validate API key before doing anything else
COHERE_API_KEY = os.environ.get("COHERE_API_KEY", "")
if not COHERE_API_KEY:
    print("[ERROR] COHERE_API_KEY not found in .env or environment. Exiting.")
    sys.exit(1)

# ── LangChain Cohere — same import as LangchainCohereAdapter in production ────
from langchain_cohere import ChatCohere
from langchain_core.messages import HumanMessage

llm = ChatCohere(
    model="command-r-08-2024",    # same model used in LangchainCohereAdapter
    cohere_api_key=COHERE_API_KEY,
)


# ═════════════════════════════════════════════════════════════════════════════
# STAGE 1 — Fetch the official GDELT GKG theme list (live)
#
# In production this will be fetched once on Celery worker startup and cached
# in a module-level variable (or Redis). Refreshed weekly.
# Format: THEME_NAME<TAB>article_count
# ═════════════════════════════════════════════════════════════════════════════

GDELT_THEME_LOOKUP_URL = "http://data.gdeltproject.org/api/v2/guides/LOOKUP-GKGTHEMES.TXT"

print("\n" + "=" * 65)
print("STAGE 1 — Fetch official GDELT GKG theme list (live)")
print("=" * 65)
print(f"\n  URL: {GDELT_THEME_LOOKUP_URL}")

resp = requests.get(GDELT_THEME_LOOKUP_URL, timeout=30)
resp.raise_for_status()

ALL_GDELT_THEMES: list[str] = [
    line.split("\t")[0].strip()
    for line in resp.text.splitlines()
    if "\t" in line and line.split("\t")[0].strip()
]

print(f"  Total themes loaded: {len(ALL_GDELT_THEMES)}")
print(f"  Sample: {ALL_GDELT_THEMES[:4]} ...")

# ── Pre-filter to a meaningful subset for the LLM prompt ─────────────────────
# Sending 60K themes to the LLM exceeds context/token limits and adds noise.
# We pre-filter to themes that are broad, topic-level categories (not TAX_FNCACT_*
# role names or TAX_WORLDMAMMALS_* species names). This is the same filter
# production will apply.
#
# Keep themes that don't start with known role/entity-only prefixes:
ROLE_PREFIXES = {
    "TAX_FNCACT_",     # job titles (doctor, officer, CEO...)
    "TAX_WORLDMAMMALS_",  # animal species
    "TAX_WORLDBIRDS_",
    "TAX_WORLDFISH_",
    "TAX_WORLDINSECTS",
    "TAX_WORLDREPTILES",
    "TAX_WORLDCRUSTACEANS",
    "TAX_WORLDARACHNIDS",
    "TAX_WORLDLANGUAGES_",  # specific languages
    "TAX_ETHNICITY_",       # specific ethnicities
    "TAX_MILITARY_TITLE_",  # specific military ranks
    "TAX_POLITICAL_PARTY_", # specific parties
    "TAX_RELIGION_",        # specific religions
    "TAX_TERROR_GROUP_",    # specific terror groups
    "TAX_FOODSTAPLES_",     # specific foods
    "SOC_POINTSOFINTEREST_",# specific locations
    "WB_",                  # World Bank sub-categories (too granular)
    "CRISISLEX_T",          # CrisisLex tweet-level tags
    "EPU_CATS_",            # EPU sub-categories
}

def _should_keep(theme: str) -> bool:
    return not any(theme.startswith(p) for p in ROLE_PREFIXES)

TOPIC_THEMES: list[str] = [t for t in ALL_GDELT_THEMES if _should_keep(t)]
print(f"  After pre-filtering to topic-level themes: {len(TOPIC_THEMES)}")
print(f"  Sample: {TOPIC_THEMES[:6]} ...")


# ═════════════════════════════════════════════════════════════════════════════
# STAGE 2 — Topic -> GDELT theme resolver using LangChain + Cohere
#
# This is the exact function that will live in production as
# app/pipeline/gdelt_theme_resolver.py
# ═════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 65)
print("STAGE 2 — Topic -> GDELT theme resolver (LangChain + Cohere)")
print("=" * 65)

THEMES_FOR_PROMPT = "\n".join(TOPIC_THEMES)

def resolve_gdelt_theme(topic_name: str) -> str | None:
    """
    Given a user topic name, use ChatCohere via LangChain to select the
    single best-matching GDELT GKG theme from the filtered official list.

    Returns the bare theme name (e.g. "ENV_CLIMATECHANGE") or None.
    This is exactly what production will call on topic create/update.
    """
    prompt = f"""You are a GDELT GKG theme classifier.

GDELT GKG themes are a controlled vocabulary for classifying global news articles.
Below is the official filtered list of topic-level themes you must choose from.

Your task:
- Pick the SINGLE best matching theme for the user's topic
- Return ONLY the exact theme name as listed (e.g. ENV_CLIMATECHANGE)
- Do NOT add "theme:" prefix
- If absolutely no theme fits, return: NONE
- No explanation, no punctuation, no markdown — just the theme name

User topic: "{topic_name}"

Official GDELT theme list:
{THEMES_FOR_PROMPT}"""

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = response.content.strip().upper()

        # Strip "theme:" prefix if Cohere adds it
        if raw.startswith("THEME:"):
            raw = raw[len("THEME:"):]

        if raw == "NONE":
            return None

        # Must be exactly in our filtered list
        if raw in TOPIC_THEMES:
            return raw

        # Fallback: check full list in case pre-filter was too aggressive
        if raw in ALL_GDELT_THEMES:
            return raw

        print(f"\n    [WARN] Cohere returned '{raw}' — not in official GDELT list. Treating as no match.")
        return None

    except Exception as e:
        print(f"\n    [ERROR] LangChain/Cohere call failed: {e}")
        return None


# ═════════════════════════════════════════════════════════════════════════════
# STAGE 3 — Simulate topic creation events + build theme set
#
# ONLY THESE TOPIC NAMES ARE MOCKED.
# Resolution + dedup logic is production-grade.
# ═════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 65)
print("STAGE 3 — Topic creation events + theme resolution")
print("=" * 65)

MOCK_TOPIC_NAMES = [
    "Artificial Intelligence",
    "Stock Market",
    "artificial intelligence",    # duplicate (different casing)
    "Climate Change",
    "Cybersecurity",
    "Stock Market",               # exact duplicate
    "Indian Politics",
    "Space Exploration",
    "Health and Medicine",
    "Cryptocurrency",
    "Weather Disasters",          # ambiguous — what will Cohere pick?
]

# The shared dedup set. In production this is a Redis SET.
# Key: normalised topic name -> resolved theme (so we don't re-call Cohere)
# Value: the set itself is what gets queried against GDELT
resolved_cache: dict[str, str | None] = {}   # normalised_name -> theme
active_gdelt_themes: set[str] = set()

print(f"\n  {len(MOCK_TOPIC_NAMES)} topic events incoming...\n")

for topic_name in MOCK_TOPIC_NAMES:
    normalised = topic_name.strip().lower()

    # Already resolved this topic name before (same or different user)
    if normalised in resolved_cache:
        cached = resolved_cache[normalised]
        print(f"  [CACHE ] \"{topic_name}\"")
        print(f"           -> already resolved: {cached or 'NO MATCH (skipped)'}")
        if cached:
            active_gdelt_themes.add(cached)
        continue

    # First time seeing this topic — call Cohere to resolve
    print(f"  [NEW   ] \"{topic_name}\"")
    print(f"           -> calling Cohere...", end="", flush=True)

    theme = resolve_gdelt_theme(topic_name)
    resolved_cache[normalised] = theme

    if theme is None:
        print(f" NO MATCH — will not contribute to GDELT query")
    else:
        before = len(active_gdelt_themes)
        active_gdelt_themes.add(theme)
        added = len(active_gdelt_themes) > before
        status = "ADDED to set" if added else "already in set"
        print(f" {theme}  ({status})")

    time.sleep(0.3)   # polite rate spacing

print(f"\n  ── Resolution summary ──────────────────────────────────")
for normed, theme in resolved_cache.items():
    print(f"    \"{normed}\" -> {theme or 'NONE'}")

print(f"\n  ── Active GDELT theme set ({len(active_gdelt_themes)} unique) ──────────")
for t in sorted(active_gdelt_themes):
    print(f"    theme:{t}")


# ═════════════════════════════════════════════════════════════════════════════
# STAGE 4 — Build the GDELT query
# ═════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 65)
print("STAGE 4 — Building GDELT query")
print("=" * 65)

GDELT_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

if not active_gdelt_themes:
    print("\n  [WARN] No themes resolved — nothing to query GDELT with.")
    sys.exit(0)

# "theme:X OR theme:Y OR ..." inside parens
theme_query    = " OR ".join(f"theme:{t}" for t in sorted(active_gdelt_themes))
country_filter = "sourcecountry:US OR sourcecountry:IN"
lang_filter    = "sourcelang:english"
full_query     = f"({theme_query}) ({country_filter}) {lang_filter}"

params = {
    "query":      full_query,
    "mode":       "artlist",
    "format":     "json",
    "maxrecords": 75,
    # Real Celery task will use "15min". Using "1h" here so the test
    # always returns articles to inspect regardless of news volume.
    "timespan":   "1h",
    "sort":       "datedesc",
}

import urllib.parse
print(f"\n  Theme OR block : ({theme_query})")
print(f"  Country filter : ({country_filter})")
print(f"  Language       : {lang_filter}")
print(f"\n  Full query:\n    {full_query}")


# ═════════════════════════════════════════════════════════════════════════════
# STAGE 5 — Hit GDELT API (live)
# ═════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 65)
print("STAGE 5 — GDELT API call (live)")
print("=" * 65)

print("\n  Waiting 10s for GDELT rate limit (1 req / 5s) ...")
time.sleep(10)
print("  Firing request...")

try:
    response = requests.get(GDELT_BASE_URL, params=params, timeout=20)
    print(f"  HTTP {response.status_code}")
    response.raise_for_status()

    raw_body = response.text.strip()
    if not raw_body:
        print("\n  [INFO] GDELT returned empty body — no articles in this window.")
        print("  Normal for narrow timespans. Production Celery task just logs & exits.")
        sys.exit(0)

    data     = response.json()
    articles = data.get("articles", [])
    print(f"  Articles returned: {len(articles)}")

    if not articles:
        print("\n  [INFO] Valid JSON but empty article list.")
        sys.exit(0)

    # ── Stage 6 results ───────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("STAGE 6 — Article results (what publish_article() receives)")
    print("=" * 65)

    for i, art in enumerate(articles, 1):
        title    = art.get("title", "(no title)")
        url      = art.get("url", "")
        domain   = art.get("domain", "")
        lang     = art.get("language", "")
        country  = art.get("sourcecountry", "")
        seendate = art.get("seendate", "")

        print(f"\n  [{i:02d}] {title}")
        print(f"       Domain  : {domain}")
        print(f"       Country : {country}   Language: {lang}")
        print(f"       Seen at : {seendate}")
        print(f"       URL     : {url[:90]}{'...' if len(url) > 90 else ''}")

    print("\n" + "-" * 65)
    print(f"  {len(articles)} articles -> Kafka -> pipeline-consumer")
    print(f"  -> embedding -> cosine similarity -> summarise -> deliver")
    print("-" * 65)

except requests.exceptions.HTTPError as e:
    print(f"\n  [HTTP ERROR] {response.status_code}: {e}")
    print(f"  Body: {response.text[:300]}")
except requests.exceptions.Timeout:
    print("\n  [TIMEOUT] GDELT did not respond in time.")
except Exception as e:
    print(f"\n  [ERROR] {type(e).__name__}: {e}")

print("\n" + "=" * 65)
print("Mock test complete.")
print("=" * 65 + "\n")
