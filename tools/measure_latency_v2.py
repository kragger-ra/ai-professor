"""Latency measurement for the Tutor v2 pipeline (no audio stack).

Re-measures pipeline latencies after the 21.05 single-process rewrite, for
ВКР chapter 3.1 and defence position 3 (the background meta-agent does not
add to the main loop because it runs in parallel with RAG).

Measures, without touching the microphone or TTS:
  1. TTFT  — time to first token of the core LLM (gpt-5.4 streaming).
  2. e2e   — full generation time (same call, to the final token).
  3. preflight — wall time of the ThreadPoolExecutor block that runs the
     meta-agent and RAG retrieval in parallel.
  4. retrieval — rag.explain() in isolation (bge-m3 embed + FAISS search).
  5. meta  — meta.analyze_context() in isolation.
  6. TTFT delta meta on/off — the meta-agent runs in preflight, which
     completes BEFORE the LLM call, so the LLM TTFT itself is meta-independent
     by construction. The meta-agent's whole contribution to the critical
     path is therefore localised in preflight. #6 compares
     (preflight + TTFT) with the real meta-agent vs. with a zero-cost mock
     returning SAFE_DEFAULTS; the shared TTFT is measured once.
  7. VRAM peak — nvidia-smi sampled once per second in the background.

Run order: 3 passes; pass 1 is discarded (warms up the litellm client and
the provider kv-cache), passes 2 and 3 feed the results.

Autonomous: `python tools/measure_latency_v2.py`. Requires LM Studio with
bge-m3 on :22227 (RAG embeddings) and network access to OpenAI.

Artifacts:
  data/eval/_latency_v2_raw.json — per-question raw numbers, every pass.
  data/eval/_latency_v2.md       — p50/p95 report + comparison with v1.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# UTF-8 stdout so Cyrillic prints don't crash on Windows cp1251.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# RAG corpus to measure against:
#   "personalab" — data/rag_vector_store_personalab_backup (140 chunks).
#                  Matches the v1 ВКР measurement — use for the v1-vs-v2
#                  comparison (isolates the architecture from the corpus).
#   "active"     — data/rag_vector_store (whatever is currently active).
CORPUS = "personalab"

# Core LLM output cap. The v2 agent uses RESPONSE_MAX_TOKENS=400, so 400 is
# the representative value. NB: the v1 ВКР measurement used 200 — e2e is
# therefore NOT directly comparable across versions (see the report's
# methodology note); TTFT and tokens/s are.
MAX_TOKENS = 400

N_PASSES = 3            # pass 1 is the discarded warm-up
WARMUP_PASSES = 1
TEMPERATURE = 0.6       # matches stream_response_sentences' default

# v1 baseline (ВКР, measured 2026-05-19 on v1 — values as stated in the task).
V1_BASELINE = {
    "ttft_p50": 1400, "ttft_p95": 1700,
    "e2e_p50": 3200, "e2e_p95": 4400,
    "retrieval_p50": 18, "retrieval_p95": 28,
    "vram_peak_mb": 3500,
}
DIVERGENCE_THRESHOLD = 0.15   # flag metrics that drift more than ±15%

# Ten questions — the exact list from the v1 measurement (_inventory_measure.py),
# reused verbatim so the v1-vs-v2 comparison isolates the architecture from
# question-set variability. PersonaLab Workshop course.
QUESTIONS = [
    "Что такое цифровой персонаж в курсе?",
    "Объясни разницу между summary и rank в архитектуре агента",
    "Что такое prefill?",
    "Как работает Like Tool?",
    "Что такое tool_status?",
    "Зачем нужен RAG в этой архитектуре?",
    "Что делает Whisper в pipeline?",
    "Зачем Vosk TTS, а не piper?",
    "Что хранится в FAISS-индексе?",
    "Чем меня-агент отличается от основного агента?",
]

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


def load_env() -> None:
    """Load .env into os.environ; force cloud-LLM mode for this measurement."""
    env_path = REPO_ROOT / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    # Only USE_LOCAL_LLM is forced (the task allows toggling it); everything
    # else stays as the .env defines it.
    os.environ["USE_LOCAL_LLM"] = "false"


# ---------------------------------------------------------------------------
# VRAM background sampler
# ---------------------------------------------------------------------------


class VramSampler(threading.Thread):
    """Sample nvidia-smi memory.used once per second; keep all samples."""

    def __init__(self) -> None:
        super().__init__(name="vram-sampler", daemon=True)
        # NB: not `_stop` — that name collides with Thread._stop (an internal
        # method), which breaks Thread.join().
        self._stop_evt = threading.Event()
        self.samples: list[int] = []

    def run(self) -> None:
        while not self._stop_evt.is_set():
            try:
                out = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=memory.used",
                     "--format=csv,noheader,nounits"],
                    text=True, encoding="utf-8",
                ).strip().splitlines()[0]
                self.samples.append(int(out.strip()))
            except Exception:
                pass
            self._stop_evt.wait(1.0)

    def stop(self) -> None:
        self._stop_evt.set()


# ---------------------------------------------------------------------------
# Measurement primitives
# ---------------------------------------------------------------------------


def measure_llm(messages: list, max_tokens: int) -> dict:
    """Stream the core LLM and record TTFT + e2e.

    Equivalent of stream_response_sentences: replicates the litellm.completion
    call from llm.py::_stream_to_queue_litellm with identical kwargs, so the
    timing reflects exactly what the agent's producer thread does. The start
    point is the moment of the litellm.completion() call.
    """
    import litellm

    model = os.getenv("CORE_LLM_MODEL_NAME", "openai/gpt-5.4")
    api_base = os.getenv("CORE_LLM_API_BASE")
    kwargs = dict(
        model=model,
        messages=messages,
        temperature=TEMPERATURE,
        stream=True,
        timeout=7,
        api_base=(api_base if api_base and api_base != "NONE" else None),
    )
    if "gpt-5" in model.lower():
        kwargs["max_completion_tokens"] = max_tokens
        reasoning = os.getenv("LM_STUDIO_REASONING_EFFORT", "").strip()
        if reasoning:
            kwargs["reasoning_effort"] = reasoning
    else:
        kwargs["max_tokens"] = max_tokens

    t_call = time.time()
    t_first = t_last = None
    tokens = 0
    text: list[str] = []
    try:
        response = litellm.completion(**kwargs)
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                now = time.time()
                if t_first is None:
                    t_first = now
                t_last = now
                tokens += 1
                text.append(delta.content)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}",
                "ttft_ms": None, "e2e_ms": None, "tokens": 0, "text": ""}

    return {
        "ttft_ms": (t_first - t_call) * 1000 if t_first else None,
        "e2e_ms": (t_last - t_call) * 1000 if t_last else None,
        "tokens": tokens,
        "text": "".join(text),
        "error": None,
    }


def run_preflight(rag, recent: list, question: str, meta_on: bool) -> dict:
    """Replicate the agent's preflight: meta-agent + RAG in parallel.

    With meta_on=False the meta task is a zero-cost mock returning the safe
    defaults instantly — this is the 'meta off' arm of measurement #6.
    """
    from tutor.brain.meta import SAFE_DEFAULTS, analyze_context

    def meta_task():
        if meta_on:
            return analyze_context("", recent, question)
        return dict(SAFE_DEFAULTS)

    with ThreadPoolExecutor(max_workers=2) as pool:
        t0 = time.time()
        meta_future = pool.submit(meta_task)
        rag_future = pool.submit(rag.explain, question)
        meta_result = meta_future.result()
        rag_context = rag_future.result()
        dt_ms = (time.time() - t0) * 1000
    return {
        "preflight_ms": dt_ms,
        "meta_result": meta_result,
        "rag_context": rag_context,
        "rag_score": float(getattr(rag, "last_score", float("inf"))),
    }


def build_messages(rag_context: str, rag_score: float, meta_result: dict,
                   past_sessions: str, question: str, history: list) -> list:
    """Assemble the full system+history+question prompt exactly as the agent."""
    from tutor.brain.meta import build_meta_instruction
    from tutor.brain.prompt import PROFESSOR_GOAL, construct_prompt

    system_prompt = PROFESSOR_GOAL + "\n\n" + construct_prompt(
        rag_context=rag_context,
        personality_key="professor_simpler",      # DEFAULT_PERSONALITY
        student_profile="",                        # _PROFILE_DISABLED
        meta_instruction=build_meta_instruction(meta_result),
        rag_score=rag_score,
        past_sessions=past_sessions,
    )
    messages = [{"role": "system", "content": system_prompt}]
    messages += history[-12:]                      # last 6 turns
    messages.append({"role": "user", "content": question})
    return messages


# ---------------------------------------------------------------------------
# One measurement pass
# ---------------------------------------------------------------------------


def run_pass(rag, past_sessions: str, pass_idx: int) -> list[dict]:
    """One pass over all 10 questions, sequential (history accumulates)."""
    from tutor.brain.meta import analyze_context

    history: list[dict] = []
    rows: list[dict] = []

    for qi, question in enumerate(QUESTIONS, 1):
        recent = [m["content"] for m in history[-5:]]

        # #4 — retrieval in isolation.
        t = time.time()
        rag.explain(question)
        retrieval_ms = (time.time() - t) * 1000

        # #5 — meta-agent in isolation.
        t = time.time()
        analyze_context("", recent, question)
        meta_ms = (time.time() - t) * 1000

        # #3 — preflight with the real meta-agent.
        pre_on = run_preflight(rag, recent, question, meta_on=True)

        # #6 — preflight with the meta-agent mocked off (zero-cost defaults).
        # Measured back-to-back with pre_on so both arms see the same bge-m3
        # warmth: the embedding endpoint goes cold during the multi-second
        # LLM generation, and a cold call (~2 s) would otherwise skew the
        # on/off delta if pre_off were measured after the LLM call.
        pre_off = run_preflight(rag, recent, question, meta_on=False)

        # #1 / #2 — core LLM TTFT + e2e, prompt built from the meta-on preflight.
        messages = build_messages(
            pre_on["rag_context"], pre_on["rag_score"], pre_on["meta_result"],
            past_sessions, question, history,
        )
        prompt_chars = sum(len(m["content"]) for m in messages)
        llm = measure_llm(messages, MAX_TOKENS)

        rows.append({
            "pass": pass_idx,
            "q_index": qi,
            "question": question,
            "retrieval_ms": retrieval_ms,
            "meta_ms": meta_ms,
            "preflight_on_ms": pre_on["preflight_ms"],
            "preflight_off_ms": pre_off["preflight_ms"],
            "ttft_ms": llm["ttft_ms"],
            "e2e_ms": llm["e2e_ms"],
            "tokens": llm["tokens"],
            "rag_score": pre_on["rag_score"],
            "prompt_chars": prompt_chars,
            "llm_error": llm["error"],
        })
        tag = "warmup" if pass_idx <= WARMUP_PASSES else "counted"
        print(f"  [pass {pass_idx} {tag}] Q{qi:>2} "
              f"ret={retrieval_ms:6.0f} meta={meta_ms:7.0f} "
              f"pre_on={pre_on['preflight_ms']:7.0f} "
              f"pre_off={pre_off['preflight_ms']:7.0f} "
              f"ttft={llm['ttft_ms'] or -1:7.0f} e2e={llm['e2e_ms'] or -1:8.0f} "
              f"tok={llm['tokens']:>4} | {question[:34]}")

        # Accumulate history like the agent does.
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant",
                        "content": llm["text"] or "(пустой ответ)"})

    return rows


# ---------------------------------------------------------------------------
# Aggregation + reporting
# ---------------------------------------------------------------------------


def pct(values: list, p: float):
    """Nearest-rank percentile; ignores None."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    k = max(0, min(len(vals) - 1, math.ceil(p / 100 * len(vals)) - 1))
    return vals[k]


def fmt(v, unit: str = "ms") -> str:
    if v is None:
        return "—"
    if unit == "ms":
        return f"{v:.0f} мс"
    if unit == "s":
        return f"{v / 1000:.2f} с"
    return f"{v:.0f}"


def write_report(counted: list[dict], vram: list[int], rag_init_s: float,
                 raw_path: Path, md_path: Path) -> None:
    """Render the markdown report with the p50/p95 table and v1 comparison."""

    def col(name):
        return [r[name] for r in counted]

    metrics = {
        "ttft": col("ttft_ms"),
        "e2e": col("e2e_ms"),
        "preflight_on": col("preflight_on_ms"),
        "preflight_off": col("preflight_off_ms"),
        "retrieval": col("retrieval_ms"),
        "meta": col("meta_ms"),
    }
    agg = {k: {"p50": pct(v, 50), "p95": pct(v, 95)} for k, v in metrics.items()}

    # #6 — total "question -> first token" latency, meta on vs off.
    total_on = [r["preflight_on_ms"] + r["ttft_ms"]
                for r in counted if r["ttft_ms"] is not None]
    total_off = [r["preflight_off_ms"] + r["ttft_ms"]
                 for r in counted if r["ttft_ms"] is not None]
    delta_p50 = (pct(total_on, 50) - pct(total_off, 50)
                 if total_on and total_off else None)

    tokens = [r["tokens"] for r in counted if r["tokens"]]
    gen_speed = [r["tokens"] / ((r["e2e_ms"] - r["ttft_ms"]) / 1000)
                 for r in counted
                 if r["ttft_ms"] and r["e2e_ms"] and r["tokens"]
                 and r["e2e_ms"] > r["ttft_ms"]]

    vram_peak = max(vram) if vram else None
    vram_min = min(vram) if vram else None

    # Divergence vs v1.
    def diverged(v2, v1):
        if v2 is None or not v1:
            return False
        return abs(v2 - v1) / v1 > DIVERGENCE_THRESHOLD

    flags = []
    if diverged(agg["ttft"]["p50"], V1_BASELINE["ttft_p50"]):
        flags.append("TTFT p50")
    if diverged(agg["e2e"]["p50"], V1_BASELINE["e2e_p50"]):
        flags.append("e2e p50")
    if diverged(agg["retrieval"]["p50"], V1_BASELINE["retrieval_p50"]):
        flags.append("retrieval p50")
    if diverged(vram_peak, V1_BASELINE["vram_peak_mb"]):
        flags.append("VRAM peak")

    L = []
    L.append("# Замер латентностей конвейера — Tutor v2")
    L.append("")
    L.append(f"- **Дата замера:** {time.strftime('%Y-%m-%d %H:%M')}")
    L.append("- **Ветка:** `tutor-v2`")
    L.append(f"- **Корпус RAG:** {CORPUS} "
             f"({'PersonaLab, 140 чанков — как в v1-замере' if CORPUS == 'personalab' else 'активный индекс'})")
    L.append(f"- **Core LLM:** `{os.getenv('CORE_LLM_MODEL_NAME')}`, "
             f"max_tokens={MAX_TOKENS}, temperature={TEMPERATURE}, "
             f"reasoning_effort={os.getenv('LM_STUDIO_REASONING_EFFORT', '—')}")
    L.append(f"- **Мета-агент:** `{os.getenv('META_LOCAL_MODEL', '—')}`")
    L.append(f"- **Прогонов:** {N_PASSES} (первый — разогрев, отброшен; "
             f"в зачёт {N_PASSES - WARMUP_PASSES} прогона = {len(counted)} точек)")
    L.append(f"- **RAG init (одноразово):** {rag_init_s:.2f} с")
    L.append("- **Аудио-стек (микрофон, STT, TTS) не поднимался** — по условию задачи.")
    L.append("")
    L.append("## Сводка p50 / p95")
    L.append("")
    L.append("| # | Метрика | v2 p50 | v2 p95 | v1 ВКР p50 | v1 ВКР p95 |")
    L.append("|---|---|---|---|---|---|")
    L.append(f"| 1 | TTFT основной LLM | {fmt(agg['ttft']['p50'])} | "
             f"{fmt(agg['ttft']['p95'])} | {fmt(V1_BASELINE['ttft_p50'])} | "
             f"{fmt(V1_BASELINE['ttft_p95'])} |")
    L.append(f"| 2 | e2e (полная генерация) | {fmt(agg['e2e']['p50'])} | "
             f"{fmt(agg['e2e']['p95'])} | {fmt(V1_BASELINE['e2e_p50'])} | "
             f"{fmt(V1_BASELINE['e2e_p95'])} |")
    L.append(f"| 3 | Preflight (мета+RAG, параллельно) | "
             f"{fmt(agg['preflight_on']['p50'])} | "
             f"{fmt(agg['preflight_on']['p95'])} | — | — |")
    L.append(f"| 4 | Retrieval (изолированно) | {fmt(agg['retrieval']['p50'])} | "
             f"{fmt(agg['retrieval']['p95'])} | "
             f"{fmt(V1_BASELINE['retrieval_p50'])} | "
             f"{fmt(V1_BASELINE['retrieval_p95'])} |")
    L.append(f"| 5 | Meta-агент (изолированно) | {fmt(agg['meta']['p50'])} | "
             f"{fmt(agg['meta']['p95'])} | — | — |")
    L.append(f"| 6 | Вопрос→первый токен, мета ВКЛ | {fmt(pct(total_on, 50))} | "
             f"{fmt(pct(total_on, 95))} | — | — |")
    L.append(f"| 6 | Вопрос→первый токен, мета ВЫКЛ | {fmt(pct(total_off, 50))} | "
             f"{fmt(pct(total_off, 95))} | — | — |")
    L.append(f"| 7 | VRAM пик за прогон | {fmt(vram_peak, 'count')} MiB | — | — | "
             f"{fmt(V1_BASELINE['vram_peak_mb'], 'count')} MiB |")
    L.append("")

    L.append("## Детали по пунктам")
    L.append("")
    L.append("**1-2. TTFT и e2e.** Точка старта — вызов `litellm.completion()` "
             "(эквивалент `stream_response_sentences`), финиш — первый / "
             "последний токен от провайдера. Токенов на ответ: "
             f"{min(tokens) if tokens else '—'}…{max(tokens) if tokens else '—'} "
             f"(медиана {int(statistics.median(tokens)) if tokens else '—'}). "
             f"Скорость генерации (без prefill): "
             f"p50 ≈ {pct(gen_speed, 50):.0f} ток/с." if gen_speed
             else "**1-2. TTFT и e2e.**")
    L.append("")
    L.append("**3-5. Preflight.** Preflight = `ThreadPoolExecutor` блок, "
             "запускающий мета-агента и RAG параллельно; общее время ≈ "
             "max(meta, retrieval). Retrieval (#4) и meta (#5) измерены "
             "отдельными изолированными вызовами. Хвост preflight тяжёлый "
             f"(p95 ≈ {fmt(agg['preflight_on']['p95'])}, max ≈ "
             f"{fmt(max(metrics['preflight_on']))}) и определяется хвостом "
             "мета-агента. В реальном агенте preflight ограничен "
             "`META_TIMEOUT_S = 4 с` (по таймауту берутся `SAFE_DEFAULTS`); "
             "в этом замере таймаут не применялся — чтобы показать истинную "
             "латентность меты.")
    L.append("")
    L.append("**6. Влияние мета-агента на критический путь.** Мета-агент "
             "выполняется в preflight, который завершается ДО вызова LLM, "
             "поэтому TTFT самого LLM-вызова от мета-агента не зависит по "
             "построению. Весь вклад мета-агента в задержку локализован в "
             "preflight. Замер #6 сравнивает полную задержку «вопрос→первый "
             "токен» = preflight + TTFT с реальным мета-агентом и с мок-"
             "заглушкой, отдающей `SAFE_DEFAULTS` мгновенно. TTFT LLM "
             "измеряется один раз (он одинаков для обеих веток).")
    if delta_p50 is not None:
        meta_masked = delta_p50 <= max(30, 0.05 * (pct(total_off, 50) or 1))
        L.append("")
        L.append(f"Дельта p50 (мета ВКЛ − мета ВЫКЛ) = **{delta_p50:.0f} мс**.")
        L.append("")
        if meta_masked:
            L.append("**Вывод:** мета-агент НЕ увеличивает задержку основного "
                     "цикла — его время замаскировано параллельным RAG "
                     "(meta ≤ RAG). Положение защиты 3 подтверждается.")
        else:
            L.append("**Вывод: Положение защиты 3 в текущей формулировке "
                     "(«фоновый мета-агент не увеличивает задержку основного "
                     "цикла») для v2 НЕ подтверждается.** Мета-агент идёт "
                     f"параллельно с RAG, но т.к. вызов меты (p50 ≈ "
                     f"{fmt(agg['meta']['p50'])}) на порядок медленнее RAG "
                     f"(p50 ≈ {fmt(agg['retrieval']['p50'])}), параллелизм "
                     f"скрывает только время RAG. Мета-агент добавляет ≈"
                     f"{delta_p50:.0f} мс к задержке «вопрос→первый токен».")
            L.append("")
            L.append("Причина — архитектурное расхождение v1→v2. В **v2** "
                     "мета-агент выполняется как **блокирующий preflight**: "
                     "`agent._answer_question` ждёт `meta_future.result()` "
                     "(таймаут 4 с) ДО старта генерации. В **v1** мета-агент "
                     "был действительно фоновым — запускался ПОСЛЕ ответа, "
                     "параллельно с воспроизведением TTS, а его результат "
                     "использовался на СЛЕДУЮЩЕМ ходу, вне критического пути. "
                     "Положение 3 описывает поведение v1, не v2. Варианты: "
                     "(а) переформулировать положение под v2 — «мета-агент на "
                     "критическом пути, но укладывается в бюджет ≈"
                     f"{fmt(agg['meta']['p95'])} p95, ниже порога НФТ»; "
                     "(б) вернуть мета-агента в фоновый режим (результат — "
                     "на следующий ход), восстановив исходное свойство.")
    L.append("")
    L.append("**7. VRAM.** nvidia-smi (`memory.used` — суммарно по всем "
             "процессам GPU), выборка раз в секунду за весь прогон. "
             f"Минимум {vram_min} MiB, пик {vram_peak} MiB. "
             "⚠ **Цифры системные, не пер-процессные, и с v1 (3,5 ГБ) "
             "напрямую не сопоставимы.** (1) Замер без аудио-стека: Whisper "
             "STT не загружался (по условию задачи), а v1-цифра 3,5 ГБ — это "
             "полный стек Whisper + bge-m3 + буферы. (2) `memory.used` "
             "суммирует ВСЕ процессы GPU — пик включает стороннее потребление "
             "видеопамяти на машине во время прогона; собственный след "
             f"тьютора в no-audio режиме ближе к минимуму (~{vram_min} MiB ≈ "
             "ОС/драйверы + bge-m3 в LM Studio). Для сопоставимой с v1 цифры "
             "нужен отдельный замер с поднятым Whisper и пер-процессным "
             "учётом (`nvidia-smi --query-compute-apps`).")
    L.append("")

    L.append("## Сравнение с v1 и гипотезы расхождений")
    L.append("")
    if flags:
        L.append(f"Расхождение более ±{int(DIVERGENCE_THRESHOLD * 100)}% "
                 f"зафиксировано по: **{', '.join(flags)}**.")
        L.append("")
        L.append("Возможные причины:")
        L.append("- **e2e** — главная причина несопоставимости: v1-замер был "
                 f"с `max_completion_tokens=200`, v2 — с {MAX_TOKENS} "
                 "(значение реального агента). e2e линейно растёт с числом "
                 "токенов. Сопоставимая метрика — TTFT и скорость генерации "
                 "(ток/с), а не абсолютный e2e.")
        L.append("- **TTFT** — v1-замер делал прямой `requests`-стриминг, v2 "
                 "идёт через `litellm` (накладные расходы клиента); изменился "
                 "системный промпт (`PROFESSOR_GOAL` + сборка `construct_prompt`); "
                 "автоматический prompt-кэш OpenAI мог попадать по-разному.")
        L.append("- **retrieval** — зависит от размера активного корпуса и "
                 "состояния LM Studio; при совпадении корпуса (PersonaLab-140) "
                 "расхождение должно быть в пределах сетевого джиттера.")
        L.append("- **VRAM** — см. п. 7: замер без аудио-стека, цифры "
                 "методологически не сопоставимы.")
        L.append("- **preflight** — компонент, которого в v1-отчёте не было "
                 "выделено; добавляет фиксированную задержку перед генерацией.")
    else:
        L.append(f"Все сопоставимые метрики — в пределах ±"
                 f"{int(DIVERGENCE_THRESHOLD * 100)}% от v1. Архитектурная "
                 "пересборка латентность конвейера не ухудшила.")
    L.append("")
    L.append("## Методологические оговорки")
    L.append("")
    L.append(f"- Вопросы — тот же список из 10 (см. `{raw_path.name}`), что и "
             "в v1-замере, чтобы изолировать архитектуру от вариативности "
             "набора вопросов.")
    L.append("- Промпт собирается полностью: `PROFESSOR_GOAL` + RAG-контекст + "
             "инструкция мета-агента + кросс-сессионная память + история "
             "последних 6 ходов + текущий вопрос. История накапливается по "
             "ходу прогона (как у реального агента).")
    L.append("- Профиль студента пуст (`_PROFILE_DISABLED`).")
    L.append(f"- Сырые данные по каждому вопросу и прогону — `{raw_path.name}`.")
    L.append("")

    md_path.write_text("\n".join(L), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    load_env()
    print("=" * 64)
    print("LATENCY MEASUREMENT — Tutor v2")
    print("=" * 64)
    print(f"corpus={CORPUS}  max_tokens={MAX_TOKENS}  passes={N_PASSES}")

    # Point RagModel at the chosen corpus index (read-only — the script only
    # calls explain(); it never rebuilds or writes an index).
    import tutor.brain.rag as ragmod
    if CORPUS == "personalab":
        ragmod.RAG_STORE_DIR = str(
            REPO_ROOT / "data" / "rag_vector_store_personalab_backup")
    print(f"RAG index dir: {ragmod.RAG_STORE_DIR}")

    # Fail fast if the embeddings endpoint is down — before spending any
    # paid LLM calls.
    import requests
    emb_base = os.getenv("EMBEDDINGS_API_BASE", "http://localhost:22227/v1")
    try:
        r = requests.get(f"{emb_base.rstrip('/')}/models", timeout=4)
        emb_up = r.status_code == 200
    except Exception:
        emb_up = False
    if not emb_up:
        print(f"\nABORT: embeddings endpoint {emb_base} is DOWN.")
        print("Start LM Studio and load bge-m3 on :22227, then re-run:")
        print("  lms server start")
        print("  lms load text-embedding-user-bge-m3 --gpu max")
        return 1
    print(f"embeddings endpoint {emb_base}: UP")

    vram = VramSampler()
    vram.start()

    t0 = time.time()
    rag = ragmod.RagModel()
    rag_init_s = time.time() - t0
    n_chunks = len(getattr(rag, "docs", []))
    print(f"RAG ready: {n_chunks} chunks, init {rag_init_s:.2f}s")
    if rag.vec_store is None:
        print("ABORT: RAG vec_store is None — index did not load.")
        vram.stop()
        return 1

    from tutor.brain.session_memory import SessionMemory
    past_sessions = SessionMemory().as_prompt_section()

    all_rows: list[dict] = []
    for p in range(1, N_PASSES + 1):
        print(f"\n--- PASS {p}/{N_PASSES} "
              f"{'(warm-up, discarded)' if p <= WARMUP_PASSES else '(counted)'} ---")
        all_rows.extend(run_pass(rag, past_sessions, p))

    vram.stop()
    vram.join(timeout=2)

    counted = [r for r in all_rows if r["pass"] > WARMUP_PASSES]
    errors = [r for r in counted if r["llm_error"]]
    if errors:
        print(f"\nWARNING: {len(errors)} LLM call(s) errored — "
              f"excluded from percentiles.")

    eval_dir = REPO_ROOT / "data" / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)
    raw_path = eval_dir / "_latency_v2_raw.json"
    md_path = eval_dir / "_latency_v2.md"

    raw_path.write_text(json.dumps({
        "config": {"corpus": CORPUS, "max_tokens": MAX_TOKENS,
                   "passes": N_PASSES, "warmup_passes": WARMUP_PASSES,
                   "temperature": TEMPERATURE, "n_chunks": n_chunks,
                   "rag_init_s": rag_init_s,
                   "core_llm": os.getenv("CORE_LLM_MODEL_NAME"),
                   "meta_model": os.getenv("META_LOCAL_MODEL")},
        "questions": QUESTIONS,
        "vram_samples_mb": vram.samples,
        "rows": all_rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nraw  -> {raw_path}")

    write_report(counted, vram.samples, rag_init_s, raw_path, md_path)
    print(f"report -> {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
