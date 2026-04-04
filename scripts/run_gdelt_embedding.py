import json
import os
from pathlib import Path
import numpy as np
from sentence_transformers import SentenceTransformer

# Paths
INDEX_DIR = Path(__file__).parent / "gdelt_theme_index"
DESCS_FILE = INDEX_DIR / "descriptions.json"
VECTORS_FILE = INDEX_DIR / "vectors.npy"
# We'll use a specific file to track which themes are actually in the matrix
INDEXED_LIST_FILE = INDEX_DIR / "indexed_themes.json"

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

def main():
    if not DESCS_FILE.exists():
        print(f"[ERROR] {DESCS_FILE} not found. Run builder script to collect descriptions first.")
        return

    # 1. Load the "Available" set (those with descriptions)
    print("[1/3] Checking available descriptions...")
    available_data = json.loads(DESCS_FILE.read_text())
    # available_data is a dict: { "THEME_ID": "Description..." }
    
    available_themes = list(available_data.keys())
    total_available = len(available_themes)
    
    # 2. Load the "Already Indexed" set
    indexed_themes = []
    current_vectors = None
    
    if INDEXED_LIST_FILE.exists() and VECTORS_FILE.exists():
        indexed_themes = json.loads(INDEXED_LIST_FILE.read_text())
        current_vectors = np.load(str(VECTORS_FILE))
        # Safety check: Matrix must match indexed list
        if current_vectors.shape[0] != len(indexed_themes):
            print("[WARN] Vector matrix size mismatch. Rebuilding from scratch for safety.")
            indexed_themes = []
            current_vectors = None

    # 3. Find "New" themes (those in descriptions but not in index)
    # We maintain the order of descriptions.json
    new_themes = [t for t in available_themes if t not in indexed_themes]
    
    if not new_themes:
        print(f"  Done! All {total_available} descriptions are already indexed.")
        return

    print(f"  Current Index : {len(indexed_themes)} themes")
    print(f"  New to Add    : {len(new_themes)} themes")

    # 4. Embed only the new ones
    print(f"[2/3] Generating embeddings for {len(new_themes)} new themes...")
    model = SentenceTransformer(EMBEDDING_MODEL)
    
    new_texts = [available_data[t] for t in new_themes]
    
    # Generate vectors for ONLY the new items
    new_vectors = model.encode(
        new_texts,
        batch_size=64,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True
    )

    # 5. Combine and Save
    print("[3/3] Finalising index...")
    if current_vectors is not None:
        final_vectors = np.vstack([current_vectors, new_vectors])
        final_themes = indexed_themes + new_themes
    else:
        final_vectors = new_vectors
        final_themes = new_themes

    # Update files
    np.save(str(VECTORS_FILE), final_vectors.astype(np.float32))
    INDEXED_LIST_FILE.write_text(json.dumps(final_themes, indent=2))
    
    print(f"\n[SUCCESS] Index updated.")
    print(f"  Total themes in matrix: {final_vectors.shape[0]}")
    print(f"  Vector shape          : {final_vectors.shape}")
    print(f"\nYour 'explore_index.py' will now see the top {final_vectors.shape[0]} humanized themes.")

if __name__ == "__main__":
    main()
