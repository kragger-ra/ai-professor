"""One-shot smoke test for OpenAI migration.

1. List models, look for gpt-5.4 / gpt-5.5 family.
2. Send a 5-token ping to gpt-5.4 and report token usage.

Costs <$0.001. Run after .env is configured.
"""
import json
import os
import sys
from pathlib import Path

# Load .env from project root
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v

import requests

KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get("LM_STUDIO_API_KEY", "")
BASE = "https://api.openai.com/v1"
HEADERS = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

if not KEY or not KEY.startswith("sk-"):
    print("ERROR: no OPENAI_API_KEY in env")
    sys.exit(1)

# 1) list models
print("=" * 60)
print("Step 1: listing models")
print("=" * 60)
r = requests.get(f"{BASE}/models", headers=HEADERS, timeout=10)
if r.status_code != 200:
    print(f"FAIL list models: HTTP {r.status_code}")
    print(r.text[:500])
    sys.exit(2)
models = [m["id"] for m in r.json().get("data", [])]
gpt5 = sorted(m for m in models if "gpt-5" in m.lower() or "5.4" in m or "5.5" in m)
print(f"Total models: {len(models)}")
print(f"GPT-5* / 5.4 / 5.5 family ({len(gpt5)}):")
for m in gpt5:
    print(f"  - {m}")

# 2) ping requested model
MODEL = os.environ.get("LM_STUDIO_MODEL_NAME", "gpt-5.4")
print()
print("=" * 60)
print(f"Step 2: ping {MODEL}")
print("=" * 60)
body = {
    "model": MODEL,
    "messages": [{"role": "user", "content": "Say 'pong' and nothing else."}],
    "max_completion_tokens": 50,
    "reasoning_effort": "none",
    "temperature": 0.4,
}
r = requests.post(f"{BASE}/chat/completions", headers=HEADERS, json=body, timeout=30)
print(f"HTTP {r.status_code}")
if r.status_code != 200:
    print("Body:", r.text[:1000])
    sys.exit(3)
data = r.json()
print("Content:", repr(data["choices"][0]["message"]["content"]))
usage = data.get("usage", {})
print("Usage:", json.dumps(usage, indent=2))
print()
print("OK")
