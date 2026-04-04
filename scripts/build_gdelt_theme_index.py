"""
build_gdelt_theme_index.py
==========================
Builds a local vector index of GDELT GKG themes for semantic topic matching.

HOW IT WORKS (matches the production topic pipeline exactly):
  - Topic side: "Artificial Intelligence" → Gemini expands to a rich paragraph
    → that paragraph gets embedded with all-MiniLM-L6-v2
  - Theme side (this script): "ECON_STOCKMARKET" → Cohere writes a rich paragraph
    describing what news this theme covers → same model embeds it
  - At runtime: embed(topic_expanded_text) · embed(theme_description) = cosine score

Because BOTH sides are rich natural language descriptions embedded with the SAME model,
the cosine similarity is semantically meaningful. We are NOT doing string tricks.

RATE LIMIT SAFETY:
  - Cohere free tier: ~1000 API calls/month
  - We send BATCHES of themes per call (25 themes → 1 API call → 25 descriptions)
  - ~60K themes / 25 per batch = ~2400 calls total for full run
  - If limit exhausts mid-run, script saves checkpoint and exits cleanly
  - Re-run next day/month: resumes from exact batch where it stopped

Files produced (scripts/gdelt_theme_index/):
  themes.json         — ordered list of all theme identifiers
  descriptions.json   — Cohere-written description for each theme (parallel to themes.json)
  vectors.npy         — (N, 384) float32 embedding matrix
  checkpoint.json     — which batch we completed last (for resuming)

Usage:
  python scripts/build_gdelt_theme_index.py            # full run (do NOT run yet)
  python scripts/build_gdelt_theme_index.py --test 25  # test on first 25 themes
  python scripts/build_gdelt_theme_index.py --reset    # wipe and rebuild from scratch
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import requests
from langchain_cohere import ChatCohere
from langchain_core.messages import HumanMessage
from sentence_transformers import SentenceTransformer

# ── Load .env without pulling in the full Docker app stack ────────────────────
def _load_env(path: str = ".env") -> None:
    try:
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip(); v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except FileNotFoundError:
        pass

_load_env()

COHERE_API_KEY = os.environ.get("COHERE_API_KEY", "")
if not COHERE_API_KEY:
    print("[ERROR] COHERE_API_KEY not found. Exiting.")
    sys.exit(1)

# ── Constants ─────────────────────────────────────────────────────────────────

GDELT_THEME_URL  = "http://data.gdeltproject.org/api/v2/guides/LOOKUP-GKGTHEMES.TXT"
EMBEDDING_MODEL  = "all-MiniLM-L6-v2"   # SAME model used for topic embeddings
EMBEDDING_DIM    = 384
COHERE_MODEL     = "command-r-08-2024"   # SAME model used in LangchainCohereAdapter
BATCH_SIZE       = 10    # Lowered for better JSON reliability
SLEEP_BETWEEN    = 2.0   # seconds between Cohere calls (polite rate spacing)
CHECKPOINT_EVERY = 5     # save to disk every N batches
MAX_RETRIES      = 3     # retry Cohere calls on failure

OUTPUT_DIR      = Path(__file__).parent / "gdelt_theme_index"
THEMES_FILE     = OUTPUT_DIR / "themes.json"
DESCS_FILE      = OUTPUT_DIR / "descriptions.json"
VECTORS_FILE    = OUTPUT_DIR / "vectors.npy"
CHECKPOINT_FILE = OUTPUT_DIR / "checkpoint.json"

# ── LangChain Cohere — same pattern as LangchainCohereAdapter ────────────────
llm = ChatCohere(model=COHERE_MODEL, cohere_api_key=COHERE_API_KEY)


# ── Helpers ───────────────────────────────────────────────────────────────────

def fetch_gdelt_themes() -> list[str]:
    """Download the GDELT GKG theme list. Returns ordered list of theme names."""
    print(f"\n[INFO] Downloading theme list from: {GDELT_THEME_URL}")
    try:
        resp = requests.get(GDELT_THEME_URL, timeout=30)
        resp.raise_for_status()
        themes = []
        for line in resp.text.splitlines():
            line = line.strip()
            if "\t" in line:
                name = line.split("\t")[0].strip()
                if name:
                    themes.append(name)
        print(f"[INFO] Successfully fetched {len(themes)} themes.")
        return themes
    except Exception as e:
        print(f"[ERROR] Failed to fetch GDELT themes: {e}")
        raise


def describe_batch(themes: list[str]) -> dict[str, str]:
    """
    Ask Cohere to write a news-coverage description for each theme in the batch.
    """
    theme_list = "\n".join(f"- {t}" for t in themes)

    prompt = f"""You are an expert on the GDELT Global Knowledge Graph (GKG) news classification system.

For each GDELT GKG theme identifier below, write ONE concise paragraph (2-4 sentences) describing exactly what type of real-world news events and topics articles tagged with this theme cover. Include relevant keywords, concepts, entities, and synonyms that would appear in such news articles. This description will be used for semantic search — make it rich and specific.

Return your answer as a valid JSON object where each key is the EXACT theme identifier and the value is the description string. No markdown, no code fences, just raw JSON.

Themes to describe:
{theme_list}"""

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"\n    [BATCH_LOG] Calling Cohere for {len(themes)} themes (Attempt {attempt}/{MAX_RETRIES})...")
            response = llm.invoke([HumanMessage(content=prompt)])
            raw = response.content.strip()

            print(f"    [BATCH_LOG] Raw response received ({len(raw)} chars).")

            # Strip markdown code fences if Cohere wraps in them
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            if raw.endswith("```"):
                raw = raw.rsplit("```", 1)[0].strip()

            result = json.loads(raw)

            if not isinstance(result, dict):
                raise ValueError("Response is not a JSON object")

            # Validate that our themes are in the keys (some might be missing if LLM truncated)
            clean_result = {k.strip(): v.strip() for k, v in result.items() if isinstance(v, str)}
            missing = [t for t in themes if t not in clean_result]
            if missing:
                print(f"    [WARN] Cohere missed {len(missing)} themes in this batch: {missing}")
            
            return clean_result

        except json.JSONDecodeError as e:
            print(f"    [JSON ERROR] Attempt {attempt} failed to parse JSON: {e}")
            if attempt == MAX_RETRIES:
                print(f"    [DEBUG] Raw response snipppet: {raw[:500]}...")
        except Exception as e:
            print(f"    [ERROR] Attempt {attempt} failed: {type(e).__name__}: {e}")
        
        if attempt < MAX_RETRIES:
            wait = 5 * attempt
            print(f"    [RETRY] Waiting {wait}s before retry...")
            time.sleep(wait)

    return {}


def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.exists():
        return json.loads(CHECKPOINT_FILE.read_text())
    return {"last_completed_batch": -1}


def save_checkpoint(last_batch: int) -> None:
    CHECKPOINT_FILE.write_text(json.dumps({"last_completed_batch": last_batch}))


def fmt_time(s: float) -> str:
    if s < 60: return f"{s:.0f}s"
    m, s = divmod(int(s), 60)
    if m < 60: return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


# ── Main ──────────────────────────────────────────────────────────────────────

def main(test_n: int | None = None, reset: bool = False) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if reset:
        print("\n[RESET] Deleting existing index files...")
        for f in [THEMES_FILE, DESCS_FILE, VECTORS_FILE, CHECKPOINT_FILE]:
            if f.exists():
                f.unlink()
                print(f"  Deleted: {f.name}")

    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("STEP 1 — Load GDELT theme list")
    print("=" * 65)

    if THEMES_FILE.exists():
        all_themes = json.loads(THEMES_FILE.read_text())
        print(f"  Loaded {len(all_themes)} themes from cached themes.json")
    else:
        all_themes = fetch_gdelt_themes()
        THEMES_FILE.write_text(json.dumps(all_themes))
        print(f"  Downloaded and saved {len(all_themes)} themes")

    if test_n is not None:
        print(f"\n  [TEST MODE] Using only first {test_n} themes")
        all_themes = all_themes[:test_n]

    total_themes = len(all_themes)

    # Load existing descriptions (partial run)
    if DESCS_FILE.exists():
        descriptions: dict[str, str] = json.loads(DESCS_FILE.read_text())
        print(f"  Loaded {len(descriptions)} existing descriptions from previous run")
    else:
        descriptions = {}

    checkpoint    = load_checkpoint()
    last_batch    = checkpoint["last_completed_batch"]  # -1 = nothing done
    start_batch   = last_batch + 1

    # Split all themes into batches
    batches = [
        all_themes[i : i + BATCH_SIZE]
        for i in range(0, total_themes, BATCH_SIZE)
    ]
    total_batches = len(batches)

    print(f"\n  Total themes   : {total_themes}")
    print(f"  Batch size     : {BATCH_SIZE}")
    print(f"  Total batches  : {total_batches}")
    print(f"  Already done   : {start_batch} batches ({start_batch * BATCH_SIZE} themes)")
    print(f"  Remaining      : {total_batches - start_batch} batches")

    if start_batch >= total_batches:
        print("\n  [DONE] All batches already described. Skipping to embedding step.")
    else:
        # ─────────────────────────────────────────────────────────────────────
        print("\n" + "=" * 65)
        print("STEP 2 — Describe themes with Cohere (LangChain)")
        print("=" * 65)
        print(f"\n  Model: {COHERE_MODEL}")
        print(f"  Each API call describes {BATCH_SIZE} themes at once.")
        print(f"  Sleeping {SLEEP_BETWEEN}s between calls for rate limit safety.\n")

        run_start = time.time()
        b = start_batch

        try:
            for b in range(start_batch, total_batches):
                batch     = batches[b]
                batch_num = b + 1

                print(
                    f"\n  [PROGRESS] Batch {batch_num:>4}/{total_batches} "
                    f"({b * BATCH_SIZE + 1}–{min((b + 1) * BATCH_SIZE, total_themes)}/{total_themes})"
                )
                print(f"    Themes in this batch: {', '.join(batch)}")

                result = describe_batch(batch)

                # Merge into descriptions dict — only keep themes that got a description
                for theme in batch:
                    if theme in result and result[theme]:
                        descriptions[theme] = result[theme]
                    else:
                        # Cohere missed this one — use a minimal fallback so we
                        # don't have gaps. We can refine later.
                        descriptions.setdefault(theme, f"News coverage related to {theme.replace('_', ' ').lower()}")

                got = sum(1 for t in batch if t in result and result[t])
                print(f" {got}/{len(batch)} described")

                # Checkpoint every N batches
                if (b - start_batch + 1) % CHECKPOINT_EVERY == 0 or b == total_batches - 1:
                    DESCS_FILE.write_text(json.dumps(descriptions, indent=2))
                    save_checkpoint(b)
                    elapsed   = time.time() - run_start
                    remaining = (total_batches - b - 1) * (elapsed / (b - start_batch + 1))
                    print(f"  [CHECKPOINT] Saved at batch {batch_num}. "
                          f"Elapsed: {fmt_time(elapsed)}  ETA: {fmt_time(remaining)}")

                if b < total_batches - 1:
                    time.sleep(SLEEP_BETWEEN)

        except KeyboardInterrupt:
            print(f"\n\n  [CTRL+C] Saving progress at batch {b}...")
            DESCS_FILE.write_text(json.dumps(descriptions, indent=2))
            save_checkpoint(b - 1)
            print(f"  Saved {len(descriptions)} descriptions. Re-run to continue.")
            sys.exit(0)

        except Exception as e:
            print(f"\n\n  [ERROR] {type(e).__name__}: {e}")
            print(f"  Saving progress at batch {b}...")
            DESCS_FILE.write_text(json.dumps(descriptions, indent=2))
            save_checkpoint(b - 1)
            print(f"  Saved {len(descriptions)} descriptions. Re-run to continue.")
            raise

        # Final save of descriptions
        DESCS_FILE.write_text(json.dumps(descriptions, indent=2))
        save_checkpoint(total_batches - 1)

    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("STEP 3 — Embed theme descriptions (local, no API limits)")
    print("=" * 65)
    print(f"\n  Model: {EMBEDDING_MODEL} (same as topic embeddings in production)")
    print("  Running locally — no API calls, no rate limits.\n")

    model      = SentenceTransformer(EMBEDDING_MODEL)
    embed_list = [all_themes[i] for i in range(total_themes)]
    desc_list  = [
        descriptions.get(t, f"news about {t.replace('_', ' ').lower()}")
        for t in embed_list
    ]

    print(f"  Embedding {len(desc_list)} descriptions...")
    print("  Sample (first 3):")
    for t, d in zip(embed_list[:3], desc_list[:3]):
        print(f"    [{t}]")
        print(f"     -> {d[:100]}...")
    print()

    # Embed in batches of 64 — sentence-transformers handles this efficiently
    embed_batch = 64
    vectors     = np.zeros((total_themes, EMBEDDING_DIM), dtype=np.float32)

    for start in range(0, total_themes, embed_batch):
        end   = min(start + embed_batch, total_themes)
        batch = desc_list[start:end]
        vecs  = model.encode(
            batch,
            batch_size=embed_batch,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,   # L2-normalise: cosine = dot product
        )
        vectors[start:end] = vecs
        pct = (end / total_themes) * 100
        print(f"  [{end:>6}/{total_themes}]  {pct:5.1f}%", end="\r", flush=True)

    print(f"\n  Embedding complete. Shape: {vectors.shape}")
    np.save(str(VECTORS_FILE), vectors)

    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("STEP 4 — Verify index (spot-check)")
    print("=" * 65)

    print("\n  Quick cosine similarity test — topic descriptions vs GDELT themes:\n")

    # Simulate what happens at runtime: a topic's expanded_description gets embedded
    # and compared against the theme vectors
    test_queries = [
        "artificial intelligence machine learning deep learning neural networks GPT OpenAI",
        "stock market equities trading Wall Street financial markets S&P 500 bull bear",
        "climate change global warming carbon emissions greenhouse gas Paris Agreement",
        "cybersecurity hacking data breach ransomware malware network security",
        "pandemic infectious disease virus outbreak COVID public health",
    ]

    for query in test_queries:
        q_vec   = model.encode(query, normalize_embeddings=True)
        scores  = vectors @ q_vec                  # (N,) dot products = cosine sims
        top5_i  = scores.argsort()[::-1][:5]
        print(f"  Query: \"{query[:60]}...\"")
        for rank, idx in enumerate(top5_i, 1):
            print(f"    [{rank}] {embed_list[idx]:35s}  score: {scores[idx]:.4f}")
        print()

    # ─────────────────────────────────────────────────────────────────────────
    print("=" * 65)
    print("DONE")
    print("=" * 65)
    print(f"\n  Output files:")
    print(f"    {THEMES_FILE}")
    print(f"    {DESCS_FILE}")
    print(f"    {VECTORS_FILE}  ({VECTORS_FILE.stat().st_size / 1024:.0f} KB)")
    print(f"    {CHECKPOINT_FILE}")
    print(f"\n  At runtime:")
    print(f"    topic.expanded_description -> embed -> cosine @ theme vectors -> top GDELT theme")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build GDELT theme vector index using Cohere descriptions + sentence-transformers."
    )
    parser.add_argument("--test", type=int, metavar="N",
                        help="Test with first N themes only (e.g. --test 25)")
    parser.add_argument("--reset", action="store_true",
                        help="Delete existing index and start from scratch")
    args = parser.parse_args()
    main(test_n=args.test, reset=args.reset)
