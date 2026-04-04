"""
test_theme_describe.py — Visible step-by-step GDELT theme description test.

Does 5 themes, ONE AT A TIME, printing everything:
  1. The theme name
  2. The exact prompt sent to Cohere
  3. The raw Cohere response
  4. The parsed description
  5. The embedding (first 5 dims)
  6. Cosine similarity test against sample topic queries

Run: python scripts/test_theme_describe.py
"""

import os
import sys
import json
import time
import numpy as np
from pathlib import Path

# ── Load .env ─────────────────────────────────────────────────────────────────
def _load_env():
    try:
        for line in Path(".env").read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except FileNotFoundError:
        pass

_load_env()

COHERE_API_KEY = os.environ.get("COHERE_API_KEY", "")
if not COHERE_API_KEY:
    print("[ERROR] No COHERE_API_KEY found.")
    sys.exit(1)

print("[1/6] Loading LangChain + Cohere...")
sys.stdout.flush()
from langchain_cohere import ChatCohere
from langchain_core.messages import HumanMessage

llm = ChatCohere(model="command-r-08-2024", cohere_api_key=COHERE_API_KEY)
print("  Done. Cohere model ready.\n")
sys.stdout.flush()

print("[2/6] Loading sentence-transformers model...")
sys.stdout.flush()
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("all-MiniLM-L6-v2")
print("  Done. Embedding model ready.\n")
sys.stdout.flush()

# ── 5 hand-picked themes that cover different categories ──────────────────────
TEST_THEMES = [
    "ECON_STOCKMARKET",
    "ENV_CLIMATECHANGE",
    "CYBER_ATTACK",
    "HEALTH_PANDEMIC",
    "ELECTION",
]

# ── Describe each theme ONE BY ONE so we can see exactly what happens ─────────
descriptions: dict[str, str] = {}

print("[3/6] Describing each theme with Cohere (one at a time)...\n")
print("=" * 70)
sys.stdout.flush()

for i, theme in enumerate(TEST_THEMES, 1):
    print(f"\n{'─' * 70}")
    print(f"  Theme {i}/5: {theme}")
    print(f"{'─' * 70}")
    sys.stdout.flush()

    prompt = f"""You are an expert on the GDELT Global Knowledge Graph (GKG) news classification system.

The GDELT GKG theme "{theme}" is used to classify news articles. Write ONE paragraph (3-5 sentences) describing exactly what kind of real-world news stories and events get tagged with this theme. Include specific keywords, entities, concepts, and synonyms that would appear in such articles. Be rich and descriptive — this will be used for semantic search matching.

Return ONLY the description paragraph, nothing else."""

    print(f"\n  Prompt sent to Cohere:")
    print(f"  (first 200 chars): {prompt[:200]}...")
    print(f"\n  Calling Cohere...", end="", flush=True)
    
    t0 = time.time()
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        elapsed = time.time() - t0
        raw = response.content.strip()
        
        print(f" done in {elapsed:.1f}s")
        print(f"\n  RAW Cohere response ({len(raw)} chars):")
        print(f"  ┌{'─' * 66}┐")
        # Print wrapped lines
        for line_start in range(0, len(raw), 64):
            chunk = raw[line_start:line_start + 64]
            print(f"  │ {chunk:<64s} │")
        print(f"  └{'─' * 66}┘")
        
        descriptions[theme] = raw
        print(f"\n  ✓ Stored description for {theme}")
        
    except Exception as e:
        elapsed = time.time() - t0
        print(f" FAILED after {elapsed:.1f}s")
        print(f"  Error: {type(e).__name__}: {e}")
        descriptions[theme] = f"News about {theme.replace('_', ' ').lower()}"
        print(f"  Using fallback: '{descriptions[theme]}'")
    
    sys.stdout.flush()
    
    if i < len(TEST_THEMES):
        print(f"\n  Sleeping 1s before next call...")
        sys.stdout.flush()
        time.sleep(1)

print(f"\n\n{'=' * 70}")
print(f"[4/6] All 5 descriptions collected. Summary:")
print(f"{'=' * 70}\n")
for theme, desc in descriptions.items():
    print(f"  {theme}:")
    print(f"    {desc[:120]}...")
    print()
sys.stdout.flush()

# ── Embed the descriptions ────────────────────────────────────────────────────
print(f"{'=' * 70}")
print(f"[5/6] Embedding descriptions with all-MiniLM-L6-v2 (local, instant)")
print(f"{'=' * 70}\n")
sys.stdout.flush()

theme_names = list(descriptions.keys())
desc_texts = list(descriptions.values())

vectors = model.encode(desc_texts, normalize_embeddings=True, convert_to_numpy=True)
print(f"  Vectors shape: {vectors.shape}")
print(f"  Vectors dtype: {vectors.dtype}")
print()

for i, (theme, desc) in enumerate(descriptions.items()):
    v = vectors[i]
    print(f"  {theme}:")
    print(f"    Description: {desc[:80]}...")
    print(f"    Vector[0:5]: [{v[0]:.4f}, {v[1]:.4f}, {v[2]:.4f}, {v[3]:.4f}, {v[4]:.4f}]")
    print(f"    L2 norm: {float(np.linalg.norm(v)):.6f}  (should be ~1.0)")
    print()
sys.stdout.flush()

# ── Cosine similarity test ────────────────────────────────────────────────────
print(f"{'=' * 70}")
print(f"[6/6] Cosine similarity test — simulating topic matching")
print(f"{'=' * 70}")
print()
print("  These simulate what Gemini's topic expansion produces for a user topic.")
print("  The cosine score should rank the correct GDELT theme highest.\n")
sys.stdout.flush()

# Simulate expanded topic descriptions (like Gemini would generate)
test_topics = {
    "Stock Market": (
        "Stock market trading, equities, Wall Street, financial markets, "
        "S&P 500, NASDAQ, Dow Jones, bull market, bear market, stock prices, "
        "market capitalization, IPO, derivatives, hedge funds, portfolio"
    ),
    "Climate Change": (
        "Climate change, global warming, carbon emissions, greenhouse gases, "
        "Paris Agreement, rising sea levels, renewable energy, fossil fuels, "
        "environmental policy, deforestation, carbon footprint, sustainability"
    ),
    "Cybersecurity": (
        "Cybersecurity, hacking, data breach, ransomware, malware, phishing, "
        "network security, cyber attack, vulnerability, encryption, firewall, "
        "threat intelligence, zero-day exploit, DDoS attack"
    ),
    "COVID Pandemic": (
        "Pandemic, infectious disease, virus, COVID-19, outbreak, vaccination, "
        "public health, quarantine, WHO, lockdown, epidemiology, mortality rate, "
        "hospital capacity, ventilators, contact tracing"
    ),
    "US Elections": (
        "Elections, voting, presidential election, ballot, campaign, candidates, "
        "Republican, Democrat, polls, Electoral College, swing states, primaries, "
        "political debate, voter turnout, election results"
    ),
}

for topic_name, topic_desc in test_topics.items():
    q_vec = model.encode(topic_desc, normalize_embeddings=True)
    scores = vectors @ q_vec  # cosine similarity (vectors already L2-normalised)
    
    ranked = sorted(enumerate(scores), key=lambda x: -x[1])
    
    print(f"  Topic: \"{topic_name}\"")
    print(f"  Expanded: \"{topic_desc[:80]}...\"")
    print(f"  Results:")
    for rank, (idx, score) in enumerate(ranked, 1):
        marker = " ◀ BEST" if rank == 1 else ""
        print(f"    [{rank}] {theme_names[idx]:25s}  score: {score:.4f}{marker}")
    print()

print("=" * 70)
print("Test complete.")
print("=" * 70)
