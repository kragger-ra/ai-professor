"""Same bench as bench_lmstudio.py but with draftModel parameter set.

Tests if LM Studio's speculative decoding (E4B target + E2B draft) gives
real speedup vs the no-draft baseline.
"""
import json
import statistics
import sys
import time

import requests

API = "http://127.0.0.1:22227/v1/chat/completions"
MODEL = "google/gemma-4-e4b"
DRAFT_MODEL = "google/gemma-4-e2b"

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
    r = requests.post(
        API,
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 4,
            "temperature": 0,
            "stream": False,
            "draftModel": DRAFT_MODEL,
        },
        timeout=60,
    )
    r.raise_for_status()


def run_one(prompt: str) -> dict:
    payload = {
        "model": MODEL,
        "draftModel": DRAFT_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "reasoning_effort": "none",
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    t_start = time.perf_counter()
    t_first = None
    chunks = 0
    completion_tokens = None
    prompt_tokens = None
    text_len = 0

    with requests.post(API, json=payload, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        resp.encoding = "utf-8"
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            if chunk.get("usage"):
                completion_tokens = chunk["usage"].get("completion_tokens")
                prompt_tokens = chunk["usage"].get("prompt_tokens")
            choices = chunk.get("choices") or []
            for ch in choices:
                delta = ch.get("delta") or {}
                content = delta.get("content")
                if content:
                    if t_first is None:
                        t_first = time.perf_counter()
                    chunks += 1
                    text_len += len(content)

    t_end = time.perf_counter()
    if t_first is None:
        t_first = t_end

    total = t_end - t_start
    ttft = t_first - t_start
    gen_time = t_end - t_first
    tok = completion_tokens or chunks
    tok_per_s = tok / gen_time if gen_time > 0 else 0.0

    return {
        "prompt": prompt[:60],
        "ttft_s": ttft,
        "gen_time_s": gen_time,
        "total_s": total,
        "completion_tokens": completion_tokens,
        "prompt_tokens": prompt_tokens,
        "chunks": chunks,
        "chars": text_len,
        "tok_per_s": tok_per_s,
    }


def main():
    print(f"Endpoint: {API}")
    print(f"Model:    {MODEL}")
    print(f"Draft:    {DRAFT_MODEL}")
    print(f"max_tok:  {MAX_TOKENS}, temp: {TEMPERATURE}")
    print()
    print("Warmup...", flush=True)
    warmup()
    time.sleep(0.5)

    results = []
    print(f"{'#':<3} {'TTFT':>6} {'gen':>6} {'tok':>5} {'tok/s':>6}  prompt")
    print("-" * 80)
    for i, p in enumerate(PROMPTS, 1):
        r = run_one(p)
        results.append(r)
        print(
            f"{i:<3} {r['ttft_s']:>5.2f}s {r['gen_time_s']:>5.1f}s "
            f"{r['completion_tokens'] or 0:>5} {r['tok_per_s']:>5.1f}  "
            f"{r['prompt']}",
            flush=True,
        )

    print()
    speeds = [r["tok_per_s"] for r in results if r["tok_per_s"] > 0]
    ttfts = [r["ttft_s"] for r in results]
    print("Aggregate (steady-state, TTFT excluded from tok/s):")
    print(f"  tok/s:  mean={statistics.mean(speeds):.1f}  "
          f"median={statistics.median(speeds):.1f}  "
          f"min={min(speeds):.1f}  max={max(speeds):.1f}")
    print(f"  TTFT:   mean={statistics.mean(ttfts):.2f}s  "
          f"median={statistics.median(ttfts):.2f}s  "
          f"min={min(ttfts):.2f}s  max={max(ttfts):.2f}s")


if __name__ == "__main__":
    sys.exit(main())
