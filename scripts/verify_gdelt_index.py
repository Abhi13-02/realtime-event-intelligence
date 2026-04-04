"""Quick verification of the built index."""
import json, re
import numpy as np
from pathlib import Path
from sentence_transformers import SentenceTransformer

base = Path("scripts/gdelt_theme_index")

themes  = json.loads((base / "themes.json").read_text())
vectors = np.load(str(base / "vectors.npy"))
ckpt    = json.loads((base / "checkpoint.json").read_text())

print("=== checkpoint.json ===")
print(json.dumps(ckpt, indent=2))

print("\n=== themes.json ===")
for t in themes:
    print(f"  {t}")

print("\n=== vectors.npy ===")
print(f"  Shape : {vectors.shape}")
print(f"  Dtype : {vectors.dtype}")
print(f"  L2 norm row[0] (should be ~1.0 — normalised): {float(np.linalg.norm(vectors[0])):.6f}")

print("\n=== Cosine similarity sanity check ===")
print("  (each theme should be most similar to itself)\n")

model = SentenceTransformer("all-MiniLM-L6-v2")

def humanize(t):
    for pfx in ["TAX_FNCACT_", "TAX_ETHNICITY_", "ENV_", "ECON_", "HEALTH_", "CYBER_"]:
        t = re.sub(f"^{pfx}", "", t)
    return t.replace("_", " ").lower().strip()

for i, theme in enumerate(themes):
    h = humanize(theme)
    q = model.encode(h, normalize_embeddings=True)
    scores  = vectors @ q
    best_i  = int(scores.argmax())
    best_score = float(scores[best_i])
    match = "OK" if best_i == i else f"MISMATCH -> {themes[best_i]}"
    print(f"  [{i}] {theme:30s}  humanized: '{h}'")
    print(f"       best match: {themes[best_i]:30s}  score: {best_score:.4f}  [{match}]")
    print()
