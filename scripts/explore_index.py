"""
explore_index.py — Interactively explore the GDELT theme vector index.

Usage:
  python scripts/explore_index.py
"""

import os
import sys
import json
import numpy as np
from pathlib import Path

# Try Loading sentence-transformers (local embedding)
try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    print("[ERROR] sentence-transformers not found. Run: pip install sentence-transformers")
    sys.exit(1)

# Paths
INDEX_DIR = Path("scripts/gdelt_theme_index")
THEMES_FILE = INDEX_DIR / "themes.json"
INDEXED_LIST_FILE = INDEX_DIR / "indexed_themes.json" # The subset that has vectors
DESCRIPTIONS_FILE = INDEX_DIR / "descriptions.json"
VECTORS_FILE = INDEX_DIR / "vectors.npy"

# Load the current index
def load_index():
    if not VECTORS_FILE.exists():
        print(f"[ERROR] vectors.npy not found in {INDEX_DIR}. Run run_gdelt_embedding.py first.")
        sys.exit(1)
    
    # Priority: indexed_themes.json (the specific themes represented in vectors.npy)
    # Fallback: themes.json (the full 59k list)
    if INDEXED_LIST_FILE.exists():
        themes = json.loads(INDEXED_LIST_FILE.read_text())
    elif THEMES_FILE.exists():
        themes = json.loads(THEMES_FILE.read_text())
    else:
        print(f"[ERROR] No theme list found in {INDEX_DIR}.")
        sys.exit(1)
        
    vectors = np.load(str(VECTORS_FILE))
    
    # Safety truncation/check
    if len(themes) != vectors.shape[0]:
        print(f"[WARN] Index mismatch: {len(themes)} themes but {vectors.shape[0]} vectors. Truncating to match.")
        themes = themes[:vectors.shape[0]]

    descriptions = {}
    if DESCRIPTIONS_FILE.exists():
        descriptions = json.loads(DESCRIPTIONS_FILE.read_text())
    
    return themes, descriptions, vectors

def main():
    print("\n" + "=" * 65)
    print(" GDELT THEME INDEX EXPLORER")
    print("=" * 65 + "\n")
    
    # Check if we have descriptions at all
    themes, descriptions, vectors = load_index()
    
    print(f"  Total themes in index     : {len(themes)}")
    print(f"  Themes with descriptions  : {len(descriptions)}")
    print(f"  Vector Matrix shape       : {vectors.shape}")
    print("\n" + "─" * 65)

    # Initialise model once
    print("\n[PROGRESS] Loading embedding model (all-MiniLM-L6-v2)...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    print("[PROGRESS] Ready.\n")

    while True:
        print("\nWhat would you like to do?")
        print("  1. Search for a topic (see top matching GDELT themes)")
        print("  2. Inspect a specific GDELT theme (see description + vector)")
        print("  3. List first 10 themes")
        print("  q. Quit")
        
        choice = input("\nChoice: ").strip().lower()
        
        if choice == 'q':
            break
            
        elif choice == '1':
            query = input("\nEnter search query (e.g. 'artificial intelligence' or 'election fraud'): ").strip()
            if not query: continue
            
            # 1. Embed query
            q_vec = model.encode(query, normalize_embeddings=True)
            
            # 2. Calculate cosine similarity (vectors are pre-normalised)
            scores = vectors @ q_vec
            
            # 3. Get top 5
            top_i = scores.argsort()[::-1][:5]
            
            print(f"\n  Top match results for: \"{query}\"\n")
            for rank, idx in enumerate(top_i, 1):
                theme_id = themes[idx]
                score = scores[idx]
                print(f"    [{rank}] {theme_id:35s}  Score: {score:.4f}")
                desc = descriptions.get(theme_id, "No rich description available.")
                print(f"        Desc: {desc[:140]}...")
                print()

        elif choice == '2':
            theme_id = input("\nEnter GDELT theme ID (e.g. 'ECON_STOCKMARKET'): ").strip().upper()
            if theme_id not in themes: 
                print(f"\n[ERROR] Theme '{theme_id}' not found in index.")
                continue
            
            idx = themes.index(theme_id)
            vector = vectors[idx]
            desc = descriptions.get(theme_id, "No rich description available.")
            
            print(f"\n  Theme: {theme_id}")
            print(f"  Index: {idx}")
            print(f"  Desc : {desc}")
            print(f"  Vector (first 10 components):")
            print(f"    {vector[:10]}")

        elif choice == '3':
            print(f"\nFirst 10 themes in the current index ({len(themes)} total):\n")
            # We must be careful to only show what is actually in the current vectors/themes
            limit = min(10, len(themes))
            for i in range(limit):
                t = themes[i]
                d = descriptions.get(t, "N/A")
                print(f"  {i:>2}. {t:30s} | Desc: {d[:80]}...")
            print()
        
        else:
            print("\n[ERROR] Invalid choice. Please try again.")

if __name__ == "__main__":
    main()
