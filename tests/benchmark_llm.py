"""A/B Benchmark: Mistral API vs LM Studio (local LLM).

Measures TTFT, tokens/s, total time, and response quality for both backends.
Supports warm cache testing (repeated prompts) and cold start measurement.

Usage:
    # Compare both backends
    PYTHONPATH=src python tests/benchmark_llm.py

    # LM Studio only
    PYTHONPATH=src python tests/benchmark_llm.py --backend lm_studio

    # Mistral API only
    PYTHONPATH=src python tests/benchmark_llm.py --backend mistral

    # Custom number of runs
    PYTHONPATH=src python tests/benchmark_llm.py --runs 5

    # Test with large context (prompt caching benchmark)
    PYTHONPATH=src python tests/benchmark_llm.py --context-size 20000
"""

import argparse
import json
import os
import sys
import time
from typing import Dict, List, Optional

import requests

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

try:
    import litellm
except ImportError:
    litellm = None


# =========================================================================
# Test questions (varying complexity)
# =========================================================================

TEST_QUESTIONS = [
    # Simple
    {"q": "Привет, как дела?", "complexity": "simple", "expected_len": "short"},
    {"q": "Что такое нейронная сеть?", "complexity": "simple", "expected_len": "medium"},
    {"q": "Спасибо за объяснение.", "complexity": "simple", "expected_len": "short"},

    # Medium
    {"q": "Объясни, как работает обратное распространение ошибки.", "complexity": "medium", "expected_len": "long"},
    {"q": "Какие есть типы машинного обучения?", "complexity": "medium", "expected_len": "medium"},
    {"q": "Чем отличается CNN от RNN?", "complexity": "medium", "expected_len": "long"},
    {"q": "Что такое transfer learning и зачем он нужен?", "complexity": "medium", "expected_len": "medium"},

    # Complex
    {"q": "Сравни архитектуры Transformer и LSTM. Когда какую лучше использовать?", "complexity": "complex", "expected_len": "long"},
    {"q": "Объясни подробно, как работает механизм внимания в трансформерах.", "complexity": "complex", "expected_len": "long"},
    {"q": "Как спроектировать RAG-систему для образовательного чат-бота? Какие компоненты нужны?", "complexity": "complex", "expected_len": "long"},
]

# System prompt matching Professor's style
SYSTEM_PROMPT = """Ты — Professor. МУЖЧИНА. Мужской род (сказал, объяснил, готов).
Ты отвечаешь ГОЛОСОМ. Студент слушает, не читает.
Варьируй длину ответов. Не заканчивай каждую реплику вопросом.
Тег эмоции в конце — не произносить вслух.
Русский язык. Тег настроения в конце реплики: (neutral) (happy) (thoughtful) (encouraging).
Не повторяй слова студента. Не пересказывай вопрос. Сразу отвечай по сути."""

# Filler context for testing prompt caching with large prefixes
FILLER_CONTEXT = """
## Материалы курса PersonaLab Workshop

### Лекция 1: Введение в AI-персонажей
Цифровые персонажи — это программные агенты с уникальной личностью, знаниями
и стилем общения. Они применяются в образовании, играх, обслуживании клиентов.
Ключевые компоненты: LLM для генерации текста, TTS для озвучки, STT для распознавания
речи, RAG для доступа к базе знаний.

### Лекция 2: Архитектура AI-агента
Агент состоит из: промпта (личность + инструкции), памяти (краткосрочная и долгосрочная),
инструментов (RAG, API), цикла восприятие-решение-действие. Промпт определяет поведение.
Память хранит контекст диалога. Инструменты расширяют возможности.

### Лекция 3: Распознавание и синтез речи
STT: Whisper, faster-whisper. VAD для определения начала и конца речи.
TTS: Piper, VITS, Fish Speech. Важно: низкая латентность, естественность,
эмоциональная окраска. Стриминг TTS для снижения задержки.

### Лекция 4: RAG и базы знаний
Retrieval-Augmented Generation: эмбеддинги документов, векторный поиск (FAISS, Chroma),
re-ranking. Chunking стратегии: по предложениям, по абзацам, рекурсивный.
Оценка релевантности: L2 distance, cosine similarity.
"""


def generate_filler(target_tokens: int) -> str:
    """Generate filler text to pad the prompt to target_tokens size."""
    # Rough estimate: 1 token ~= 3.5 chars for Russian text
    target_chars = int(target_tokens * 3.5)
    result = FILLER_CONTEXT
    while len(result) < target_chars:
        result += "\n" + FILLER_CONTEXT
    return result[:target_chars]


# =========================================================================
# Backend implementations
# =========================================================================

def benchmark_lm_studio(
    messages: List[Dict],
    max_tokens: int = 300,
    temperature: float = 0.5,
) -> Dict:
    """Benchmark a single request to LM Studio."""
    base_url = os.getenv("LM_STUDIO_API_BASE", "http://127.0.0.1:1234/v1")

    payload = {
        "model": "loaded-model",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }

    t_start = time.perf_counter()
    t_first_token = None
    tokens = []
    full_response = ""

    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            json=payload,
            stream=True,
            timeout=30,
        )
        resp.raise_for_status()

        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
                delta = chunk["choices"][0]["delta"]
                # Gemma 4 streams "reasoning_content" (thinking) then "content" (answer).
                # We measure TTFT from first content token (actual answer),
                # but track reasoning start separately.
                if "content" in delta and delta["content"]:
                    token = delta["content"]
                    if t_first_token is None:
                        t_first_token = time.perf_counter()
                    tokens.append(token)
                    full_response += token
                elif "reasoning_content" in delta and delta["reasoning_content"]:
                    # Count reasoning tokens for stats but don't include in response
                    if t_first_token is None:
                        # Mark first activity (reasoning start) for total time calc
                        pass
            except (json.JSONDecodeError, KeyError, IndexError):
                continue

        # Drain remaining
        for _ in resp.iter_lines():
            pass
        resp.close()

    except Exception as e:
        return {"error": str(e), "ttft": -1, "total_time": -1, "tok_per_s": 0}

    t_end = time.perf_counter()
    ttft = (t_first_token - t_start) if t_first_token else -1
    total_time = t_end - t_start
    tok_count = len(tokens)
    gen_time = (t_end - t_first_token) if t_first_token else total_time
    tok_per_s = tok_count / gen_time if gen_time > 0 else 0

    return {
        "ttft": ttft,
        "total_time": total_time,
        "tok_count": tok_count,
        "tok_per_s": tok_per_s,
        "response": full_response,
        "response_len": len(full_response),
    }


def benchmark_mistral(
    messages: List[Dict],
    max_tokens: int = 300,
    temperature: float = 0.5,
) -> Dict:
    """Benchmark a single request to Mistral API via litellm."""
    if litellm is None:
        return {"error": "litellm not installed", "ttft": -1, "total_time": -1, "tok_per_s": 0}

    model = os.getenv("CORE_LLM_MODEL_NAME", "mistral/mistral-large-latest")
    api_base = os.getenv("CORE_LLM_API_BASE")
    effective_base = api_base if api_base and api_base != "NONE" else None

    t_start = time.perf_counter()
    t_first_token = None
    tokens = []
    full_response = ""

    try:
        response = litellm.completion(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
            timeout=15,
            api_base=effective_base,
        )

        for chunk in response:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                token = delta.content
                if t_first_token is None:
                    t_first_token = time.perf_counter()
                tokens.append(token)
                full_response += token

    except Exception as e:
        return {"error": str(e), "ttft": -1, "total_time": -1, "tok_per_s": 0}

    t_end = time.perf_counter()
    ttft = (t_first_token - t_start) if t_first_token else -1
    total_time = t_end - t_start
    tok_count = len(tokens)
    gen_time = (t_end - t_first_token) if t_first_token else total_time
    tok_per_s = tok_count / gen_time if gen_time > 0 else 0

    return {
        "ttft": ttft,
        "total_time": total_time,
        "tok_count": tok_count,
        "tok_per_s": tok_per_s,
        "response": full_response,
        "response_len": len(full_response),
    }


# =========================================================================
# Main benchmark
# =========================================================================

def build_messages(question: str, context_size: int = 0) -> List[Dict]:
    """Build messages list with optional filler context."""
    system_content = SYSTEM_PROMPT
    if context_size > 0:
        filler = generate_filler(context_size)
        system_content += f"\n\n{filler}"

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": question},
    ]


def run_benchmark(
    backend: str,
    runs: int = 3,
    context_size: int = 0,
    questions: Optional[List[Dict]] = None,
):
    """Run benchmark for a single backend."""
    if questions is None:
        questions = TEST_QUESTIONS

    bench_fn = benchmark_lm_studio if backend == "lm_studio" else benchmark_mistral
    backend_label = "LM Studio (local)" if backend == "lm_studio" else "Mistral API"

    print(f"\n{'='*70}")
    print(f"  Benchmark: {backend_label}")
    print(f"  Runs per question: {runs}")
    print(f"  Context size: {context_size} tokens")
    print(f"{'='*70}\n")

    all_results = []

    for qi, q_info in enumerate(questions, 1):
        question = q_info["q"]
        complexity = q_info["complexity"]
        messages = build_messages(question, context_size)

        print(f"  [{qi}/{len(questions)}] ({complexity}) {question[:60]}")

        q_results = []
        for run in range(runs):
            result = bench_fn(messages, max_tokens=300, temperature=0.5)

            if "error" in result:
                print(f"    Run {run+1}: ERROR - {result['error']}")
                continue

            q_results.append(result)
            ttft_ms = result["ttft"] * 1000
            total_ms = result["total_time"] * 1000
            cache_label = "(cold)" if run == 0 else "(warm)"
            print(f"    Run {run+1} {cache_label}: TTFT={ttft_ms:.0f}ms, "
                  f"total={total_ms:.0f}ms, "
                  f"{result['tok_count']} tok @ {result['tok_per_s']:.1f} tok/s")

        if q_results:
            avg_ttft = sum(r["ttft"] for r in q_results) / len(q_results) * 1000
            avg_tps = sum(r["tok_per_s"] for r in q_results) / len(q_results)
            all_results.append({
                "question": question[:50],
                "complexity": complexity,
                "avg_ttft_ms": avg_ttft,
                "avg_tok_per_s": avg_tps,
                "runs": q_results,
            })

        # Brief pause between questions to avoid rate limiting
        if backend == "mistral":
            time.sleep(1)

    return all_results


def print_comparison(lm_results: List[Dict], mistral_results: List[Dict]):
    """Print side-by-side comparison table."""
    print(f"\n{'='*90}")
    print(f"  COMPARISON: LM Studio vs Mistral API")
    print(f"{'='*90}")
    print(f"{'Question':<40} | {'LM TTFT':>8} {'LM t/s':>7} | {'M TTFT':>8} {'M t/s':>7} | {'Winner':>8}")
    print(f"{'-'*40}-+-{'-'*16}-+-{'-'*16}-+-{'-'*8}")

    lm_ttfts = []
    m_ttfts = []
    lm_tps_list = []
    m_tps_list = []

    for lm, m in zip(lm_results, mistral_results):
        lm_ttft = lm["avg_ttft_ms"]
        m_ttft = m["avg_ttft_ms"]
        lm_tps = lm["avg_tok_per_s"]
        m_tps = m["avg_tok_per_s"]

        winner = "LM" if lm_ttft < m_ttft else "Mistral"

        print(f"{lm['question']:<40} | {lm_ttft:>7.0f}ms {lm_tps:>6.1f} | {m_ttft:>7.0f}ms {m_tps:>6.1f} | {winner:>8}")

        lm_ttfts.append(lm_ttft)
        m_ttfts.append(m_ttft)
        lm_tps_list.append(lm_tps)
        m_tps_list.append(m_tps)

    if lm_ttfts and m_ttfts:
        print(f"{'-'*40}-+-{'-'*16}-+-{'-'*16}-+-{'-'*8}")
        avg_lm_ttft = sum(lm_ttfts) / len(lm_ttfts)
        avg_m_ttft = sum(m_ttfts) / len(m_ttfts)
        avg_lm_tps = sum(lm_tps_list) / len(lm_tps_list)
        avg_m_tps = sum(m_tps_list) / len(m_tps_list)
        winner = "LM" if avg_lm_ttft < avg_m_ttft else "Mistral"
        print(f"{'AVERAGE':<40} | {avg_lm_ttft:>7.0f}ms {avg_lm_tps:>6.1f} | {avg_m_ttft:>7.0f}ms {avg_m_tps:>6.1f} | {winner:>8}")

        print(f"\n  LM Studio avg TTFT: {avg_lm_ttft:.0f}ms, avg speed: {avg_lm_tps:.1f} tok/s")
        print(f"  Mistral   avg TTFT: {avg_m_ttft:.0f}ms, avg speed: {avg_m_tps:.1f} tok/s")
        speedup = avg_m_ttft / avg_lm_ttft if avg_lm_ttft > 0 else 0
        print(f"  TTFT speedup: {speedup:.1f}x {'(LM Studio faster)' if speedup > 1 else '(Mistral faster)'}")


def run_cache_benchmark(runs: int = 5):
    """Test prompt caching effectiveness: same prefix, different suffix."""
    print(f"\n{'='*70}")
    print(f"  Prompt Cache Benchmark (LM Studio)")
    print(f"  Same prefix, different questions — measures KV cache hit rate")
    print(f"{'='*70}\n")

    context_size = 5000
    filler = generate_filler(context_size)
    system_content = SYSTEM_PROMPT + f"\n\n{filler}"

    questions = [
        "Что такое нейронная сеть?",
        "Как работает backpropagation?",
        "Чем CNN отличается от RNN?",
        "Что такое attention?",
        "Объясни transfer learning.",
    ]

    results = []
    for i, question in enumerate(questions):
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": question},
        ]
        result = benchmark_lm_studio(messages, max_tokens=100)

        if "error" in result:
            print(f"  [{i+1}] ERROR: {result['error']}")
            continue

        ttft_ms = result["ttft"] * 1000
        label = "COLD" if i == 0 else "WARM"
        print(f"  [{i+1}] {label}: TTFT={ttft_ms:.0f}ms, "
              f"{result['tok_count']} tok @ {result['tok_per_s']:.1f} tok/s — {question}")
        results.append({"question": question, "ttft_ms": ttft_ms, "cold": i == 0})

    if len(results) >= 2:
        cold = results[0]["ttft_ms"]
        warm_avg = sum(r["ttft_ms"] for r in results[1:]) / len(results[1:])
        speedup = cold / warm_avg if warm_avg > 0 else 0
        print(f"\n  Cold start TTFT: {cold:.0f}ms")
        print(f"  Warm cache TTFT: {warm_avg:.0f}ms (avg)")
        print(f"  Cache speedup: {speedup:.1f}x")


def main():
    parser = argparse.ArgumentParser(description="LLM Backend Benchmark")
    parser.add_argument("--backend", choices=["lm_studio", "mistral", "both"],
                        default="both", help="Which backend to benchmark")
    parser.add_argument("--runs", type=int, default=3, help="Runs per question")
    parser.add_argument("--context-size", type=int, default=0,
                        help="Extra context tokens (for cache testing)")
    parser.add_argument("--cache-test", action="store_true",
                        help="Run prompt cache effectiveness test")
    parser.add_argument("--quick", action="store_true",
                        help="Quick mode: 3 questions, 2 runs")
    args = parser.parse_args()

    if args.quick:
        questions = TEST_QUESTIONS[:3]
        runs = 2
    else:
        questions = TEST_QUESTIONS
        runs = args.runs

    if args.cache_test:
        run_cache_benchmark()
        return

    lm_results = None
    mistral_results = None

    if args.backend in ("lm_studio", "both"):
        # Check LM Studio health first
        try:
            resp = requests.get(
                f"{os.getenv('LM_STUDIO_API_BASE', 'http://127.0.0.1:1234/v1')}/models",
                timeout=3,
            )
            models = resp.json().get("data", [])
            if not models:
                print("WARNING: LM Studio has no model loaded!")
            else:
                print(f"LM Studio model: {models[0]['id']}")
        except Exception as e:
            print(f"WARNING: LM Studio not reachable: {e}")
            if args.backend == "lm_studio":
                return

        lm_results = run_benchmark("lm_studio", runs, args.context_size, questions)

    if args.backend in ("mistral", "both"):
        if litellm is None:
            print("WARNING: litellm not installed, skipping Mistral benchmark")
        else:
            mistral_results = run_benchmark("mistral", runs, args.context_size, questions)

    if lm_results and mistral_results:
        print_comparison(lm_results, mistral_results)

    print("\nBenchmark complete.")


if __name__ == "__main__":
    main()
