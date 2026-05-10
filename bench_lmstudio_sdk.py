"""Bench LM Studio speculative decoding via the official SDK.

Uses lmstudio.llm.respond_stream(...) with config={"draftModel": ...}
which is the documented way to enable speculative decoding.
"""
import statistics
import sys
import time

import lmstudio as lms

TARGET = "google/gemma-4-e4b"
DRAFT = "google/gemma-4-e2b"

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


def bench(use_draft: bool):
    label = "DRAFT" if use_draft else "no-draft"
    print(f"=== {label} ===")
    model = lms.llm(TARGET)

    cfg = {
        "maxTokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
    }
    if use_draft:
        cfg["draftModel"] = DRAFT

    # Warmup
    chat = lms.Chat(SYSTEM)
    chat.add_user_message("ping")
    list(model.respond_stream(chat, config={**cfg, "maxTokens": 4}))

    results = []
    print(f"{'#':<3} {'TTFT':>6} {'gen':>6} {'tok':>5} {'tok/s':>6}")
    print("-" * 40)
    for i, p in enumerate(PROMPTS, 1):
        chat = lms.Chat(SYSTEM)
        chat.add_user_message(p)
        t0 = time.perf_counter()
        first = None
        token_count = 0
        for fragment in model.respond_stream(chat, config=cfg):
            if first is None:
                first = time.perf_counter()
            token_count += 1
        end = time.perf_counter()
        ttft = (first - t0) if first else (end - t0)
        gen = end - first if first else 0.001
        tps = token_count / gen if gen > 0 else 0
        results.append({"ttft": ttft, "gen": gen, "tok": token_count, "tps": tps})
        print(f"{i:<3} {ttft:>5.2f}s {gen:>5.1f}s {token_count:>5} {tps:>5.1f}")

    speeds = [r["tps"] for r in results if r["tps"] > 0]
    print(f"\n  tok/s mean={statistics.mean(speeds):.1f}  median={statistics.median(speeds):.1f}  min={min(speeds):.1f}  max={max(speeds):.1f}")
    return statistics.mean(speeds)


def main():
    no_draft = bench(False)
    print()
    with_draft = bench(True)
    print()
    print(f"Speedup: {with_draft / no_draft:.2f}x  ({no_draft:.1f} -> {with_draft:.1f} tok/s)")


if __name__ == "__main__":
    sys.exit(main())
