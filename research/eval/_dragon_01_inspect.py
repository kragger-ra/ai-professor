"""Inspect RuBQRetrieval schema + counts; smoke-test the LM Studio bge-m3 endpoint."""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from datasets import load_dataset

print("--- loading mteb/RuBQRetrieval ---")
for cfg in ["corpus", "queries", "qrels"]:
    try:
        ds = load_dataset("mteb/RuBQRetrieval", cfg)
        for split in ds:
            d = ds[split]
            print(f"[{cfg}/{split}] n={len(d)}  cols={d.column_names}")
            print(f"   sample: {d[0]}")
    except Exception as e:
        print(f"[{cfg}] ERROR: {type(e).__name__}: {e}")

print("\n--- smoke-test LM Studio bge-m3 embedding endpoint ---")
import requests
try:
    r = requests.post(
        "http://localhost:22227/v1/embeddings",
        json={"model": "text-embedding-user-bge-m3", "input": ["тестовый запрос"]},
        timeout=30,
    )
    r.raise_for_status()
    emb = r.json()["data"][0]["embedding"]
    print(f"embedding ok: dim={len(emb)}  first3={emb[:3]}")
except Exception as e:
    print(f"embedding ERROR: {type(e).__name__}: {e}")
