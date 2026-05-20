"""Live measurement probe for inventory: VRAM + LLM latencies + retrieval timing.

Run inside the Tutor .venv. Reads .env for the OpenAI key.
"""
from __future__ import annotations

import io
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

# Force UTF-8 so Cyrillic prints don't crash on Windows cp1251
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

# Load .env manually (avoid importing project_schema for now)
ENV = {}
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    if "=" not in line:
        continue
    k, v = line.split("=", 1)
    v = v.strip().strip('"').strip("'")
    ENV[k.strip()] = v
    os.environ[k.strip()] = v


def gpu_snapshot(label: str):
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,memory.free,utilization.gpu",
             "--format=csv,noheader,nounits"],
            text=True, encoding="utf-8",
        ).strip()
        used, free, util = [x.strip() for x in out.split(",")]
        print(f"[GPU {label}] used={used} MiB | free={free} MiB | util={util}%")
        return int(used)
    except Exception as e:
        print(f"[GPU {label}] error: {e}")
        return None


print("=" * 60)
print("BASELINE")
print("=" * 60)
base_mb = gpu_snapshot("baseline")

# ----------------------------------------------------------------------
# 1. STT VRAM — load Faster-Whisper large-v3-turbo-russian on CUDA
# ----------------------------------------------------------------------
print()
print("=" * 60)
print("STT: Faster-Whisper load + transcribe")
print("=" * 60)
sys.path.insert(0, str(ROOT / "src"))
from data_collectors.stt.stt_fasterwhisper import FasterWhisperSTT  # noqa

t0 = time.time()
stt = FasterWhisperSTT(device="cuda")
load_dt = time.time() - t0
post_load_mb = gpu_snapshot("after STT load")
print(f"[STT] load took {load_dt:.2f}s")
print(f"[STT] VRAM delta (load) = {post_load_mb - base_mb if post_load_mb and base_mb else '?'} MiB")

# Transcribe sample WAV if present
sample = ROOT.parent / "tts_probe.wav"
if not sample.exists():
    sample = ROOT / "vosk_tts_server" / "samples" / "sample.wav"
if sample.exists():
    print(f"[STT] transcribing {sample}")
    with open(sample, "rb") as f:
        wav_bytes = f.read()
    t1 = time.time()
    try:
        result = stt.pipeline(io.BytesIO(wav_bytes))
        stt_dt = time.time() - t1
        print(f"[STT] transcribed in {stt_dt*1000:.0f} ms: {result.get('text', '')[:80]!r}")
    except Exception as e:
        print(f"[STT] transcribe failed: {e}")
post_inf_mb = gpu_snapshot("after STT inference")

# ----------------------------------------------------------------------
# 2. LLM latency — 10 calls to OpenAI gpt-5.4 with realistic system prompt
# ----------------------------------------------------------------------
print()
print("=" * 60)
print("LLM: 10 calls to gpt-5.4 (TTFT + e2e)")
print("=" * 60)

import requests

# Realistic system prompt — base manera "professor_simpler"
SYS = (ROOT / "resources" / "Prompts" / "personalities_professor.yml").read_text(encoding="utf-8")
# crude split: take professor_simpler block
sys_prompt = SYS.split("professor_simpler:", 1)[1].split("professor_neutral:", 1)[0]
# strip yaml indent
sys_prompt = "\n".join(l[2:] if l.startswith("  ") else l for l in sys_prompt.splitlines())
sys_prompt = sys_prompt.replace("{COURSE_NAME}", "PersonaLab Workshop")
sys_prompt = sys_prompt.replace("{COURSE_TOPIC}", "создание цифрового персонажа (LLM + STT + TTS)")

# Realistic RAG payload (load 2 chunks from canonical doc)
rag_text = (ROOT / "resources" / "RAG" / "course_materials" / "00_personalab_canonical.md").read_text(encoding="utf-8")
rag_snippet = rag_text[:1800]

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

base_url = os.environ.get("LM_STUDIO_API_BASE", "https://api.openai.com/v1").rstrip("/")
api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LM_STUDIO_API_KEY")
model = os.environ.get("LM_STUDIO_MODEL_NAME", "gpt-5.4")
reasoning = os.environ.get("LM_STUDIO_REASONING_EFFORT", "none")

results = []
for i, q in enumerate(QUESTIONS):
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "system", "content": f"Контекст из материалов курса:\n{rag_snippet}"},
        {"role": "user", "content": q},
    ]
    body = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": 200,
        "temperature": 0.6,
        "stream": True,
    }
    if reasoning:
        body["reasoning_effort"] = reasoning
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    t_call = time.time()
    t_first = None
    tokens = 0
    full = []
    try:
        resp = requests.post(f"{base_url}/chat/completions", json=body, headers=headers,
                             stream=True, timeout=30)
        if resp.status_code != 200:
            print(f"[LLM #{i+1}] HTTP {resp.status_code}: {resp.text[:200]}")
            continue
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
                delta = chunk["choices"][0].get("delta", {})
                content = delta.get("content")
                if content:
                    if t_first is None:
                        t_first = time.time()
                    tokens += 1
                    full.append(content)
            except Exception:
                continue
        e2e = time.time() - t_call
        ttft = (t_first - t_call) if t_first else None
        results.append({
            "q": q,
            "ttft_ms": int(ttft * 1000) if ttft else None,
            "e2e_ms": int(e2e * 1000),
            "tokens": tokens,
            "answer_preview": "".join(full)[:140],
        })
        print(f"[LLM #{i+1:>2}] TTFT={int(ttft*1000) if ttft else 'NA'}ms "
              f"e2e={int(e2e*1000)}ms tokens={tokens}  | {q[:40]}")
    except Exception as e:
        print(f"[LLM #{i+1}] error: {e}")

# Aggregate
ttfts = [r["ttft_ms"] for r in results if r["ttft_ms"] is not None]
e2es = [r["e2e_ms"] for r in results if r["e2e_ms"] is not None]
print()
print("LLM AGGREGATE:")
if ttfts:
    ttfts.sort()
    print(f"  TTFT p50 = {ttfts[len(ttfts)//2]} ms")
    print(f"  TTFT p95 = {ttfts[int(len(ttfts)*0.95) if len(ttfts) > 5 else -1]} ms")
    print(f"  TTFT min/max = {ttfts[0]} / {ttfts[-1]} ms")
if e2es:
    e2es.sort()
    print(f"  E2E  p50 = {e2es[len(e2es)//2]} ms")
    print(f"  E2E  p95 = {e2es[int(len(e2es)*0.95) if len(e2es) > 5 else -1]} ms")
    print(f"  E2E  min/max = {e2es[0]} / {e2es[-1]} ms")

# Save full results
(ROOT / "_inventory_llm_results.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(f"  saved → _inventory_llm_results.json")

# ----------------------------------------------------------------------
# 3. FAISS retrieval timing — requires embeddings endpoint
# ----------------------------------------------------------------------
print()
print("=" * 60)
print("RAG: FAISS retrieval timing")
print("=" * 60)

# Probe embeddings endpoint
emb_base = os.environ.get("EMBEDDINGS_API_BASE", "http://localhost:22227/v1")
try:
    r = requests.get(f"{emb_base}/models", timeout=2)
    emb_up = r.status_code == 200
except Exception:
    emb_up = False
print(f"[RAG] embeddings endpoint {emb_base}: {'UP' if emb_up else 'DOWN'}")

if emb_up:
    try:
        from agent.rag import RagModel
        rag = RagModel()
        ret_times = []
        for q in QUESTIONS:
            t = time.time()
            rag.retrieve_full(q)
            ret_times.append((time.time() - t) * 1000)
        ret_times.sort()
        print(f"[RAG] retrieve_full timings ms (10 q):")
        for q, t in zip(QUESTIONS, ret_times):
            print(f"   {int(t):>5} ms  {q[:50]}")
        print(f"[RAG] p50={int(ret_times[len(ret_times)//2])} ms")
        print(f"[RAG] p95={int(ret_times[int(len(ret_times)*0.95) if len(ret_times) > 5 else -1])} ms")
    except Exception as e:
        print(f"[RAG] error: {e}")
        import traceback; traceback.print_exc()
else:
    print("[RAG] skipped — LM Studio with bge-m3 not running on 22227.")

# Final GPU snapshot
print()
print("=" * 60)
print("FINAL GPU STATE")
print("=" * 60)
final_mb = gpu_snapshot("final")
print(f"\nVRAM peak across measurement: STT alone = {(post_load_mb or 0) - (base_mb or 0)} MiB above idle")
