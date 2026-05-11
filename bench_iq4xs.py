"""Bench bartowski/gemma-4-e4b-it IQ4_XS variant — same prompts as bench_lmstudio.py."""
import json
import statistics
import sys
import time

import requests

API = "http://127.0.0.1:22227/v1/chat/completions"
MODEL = "bartowski/gemma-4-e4b-it"

SYSTEM = (
    "Ты — преподаватель курса по созданию цифровых персонажей. "
    "Отвечай кратко, по делу, без воды. Поясняй понятия простыми словами."
)

PROMPTS = [
    "Объясни в трёх предложениях, что такое нейронная сеть и зачем она нужна.",
    "Что такое RAG и чем он отличается от обычного поиска? Развёрнуто, с примером.",
    "Студент спросил: 'А зачем мне вообще FAISS, если есть обычная база данных?'. "
    "Ответь как преподаватель — терпеливо, объясни мотивацию.",
    "Дай пять конкретных советов, как новичку начать собирать датасет для тонкой настройки модели.",
    "Сравни кратко: трансформер vs RNN. Что лучше для современных диалоговых ассистентов?",
]

MAX_TOKENS = 256
TEMPERATURE = 0.7


def warmup():
    r = requests.post(API, json={"model": MODEL, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 4, "temperature": 0, "stream": False}, timeout=60)
    r.raise_for_status()


def run_one(prompt: str) -> dict:
    payload = {"model": MODEL, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}], "max_tokens": MAX_TOKENS, "temperature": TEMPERATURE, "reasoning_effort": "none", "stream": True, "stream_options": {"include_usage": True}}
    t_start = time.perf_counter()
    t_first = None
    chunks = 0
    completion_tokens = None
    with requests.post(API, json=payload, stream=True, timeout=120) as resp:
        resp.encoding = "utf-8"
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "): continue
            data = line[6:]
            if data == "[DONE]": break
            try: chunk = json.loads(data)
            except: continue
            if chunk.get("usage"): completion_tokens = chunk["usage"].get("completion_tokens")
            for ch in chunk.get("choices", []):
                if (ch.get("delta") or {}).get("content"):
                    if t_first is None: t_first = time.perf_counter()
                    chunks += 1
    t_end = time.perf_counter()
    if t_first is None: t_first = t_end
    gen = t_end - t_first
    tok = completion_tokens or chunks
    return {"prompt": prompt[:60], "ttft": t_first - t_start, "gen": gen, "tok": completion_tokens, "tok_per_s": tok / gen if gen > 0 else 0}


def main():
    print(f"Model: {MODEL}\nmax_tok: {MAX_TOKENS}\n")
    warmup()
    time.sleep(0.5)
    print(f"{'#':<3} {'TTFT':>6} {'gen':>6} {'tok':>5} {'tok/s':>6}")
    print("-" * 40)
    results = []
    for i, p in enumerate(PROMPTS, 1):
        r = run_one(p)
        results.append(r)
        print(f"{i:<3} {r['ttft']:>5.2f}s {r['gen']:>5.1f}s {r['tok'] or 0:>5} {r['tok_per_s']:>5.1f}", flush=True)
    speeds = [r["tok_per_s"] for r in results if r["tok_per_s"] > 0]
    print(f"\n  tok/s mean={statistics.mean(speeds):.1f}  median={statistics.median(speeds):.1f}  min={min(speeds):.1f}  max={max(speeds):.1f}")


if __name__ == "__main__":
    sys.exit(main())
