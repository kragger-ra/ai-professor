"""Functional test of the skeleton mechanism end-to-end via real LLM.

Simulates Pass 1 (outline) and Pass 2 (delivery with [END] stop) against the
running LM Studio. Reports outline text, length, point count, Pass 2 token count
and whether [END] was reached.
"""
import json
import re
import time

import requests

API = "http://127.0.0.1:22227/v1/chat/completions"
MODEL = "bartowski/gemma-4-e4b-it"

SYSTEM_PERSONA = (
    "Ты — преподаватель курса по созданию цифровых персонажей. "
    "Отвечай естественно, как живой человек, без формальных структур и "
    "буллет-пойнтов в речи."
)

OUTLINE_REQUEST = (
    "Сначала кратко составь план будущего ответа: 4-7 пунктов "
    "в формате нумерованного списка. Только короткие заголовки пунктов, "
    "без раскрытия и пояснений. После списка ничего не пиши. "
    "Этот план будет основой подробного объяснения студенту."
)

DELIVERY_INSTRUCTIONS_TMPL = (
    "Теперь развёрнуто объясни студенту по плану выше. "
    "Каждый пункт — 2-4 связных предложения, говори естественно, "
    "не цитируй сам план буквально, не пиши номера пунктов как часть текста. "
    "Когда полностью раскроешь все пункты, напиши {marker} "
    "и больше ничего не пиши."
)

END_MARKER = "[END]"


def chat(messages, max_tokens, temperature=0.5, stop=None):
    """Streaming call, returns (text, token_count, stopped_by, elapsed_s)."""
    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "reasoning_effort": "none",
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if stop:
        payload["stop"] = stop

    t0 = time.perf_counter()
    text = ""
    completion_tokens = None
    finish_reason = None
    with requests.post(API, json=payload, stream=True, timeout=180) as r:
        r.encoding = "utf-8"
        for line in r.iter_lines(decode_unicode=True):
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
            for ch in chunk.get("choices", []):
                if ch.get("finish_reason"):
                    finish_reason = ch["finish_reason"]
                content = (ch.get("delta") or {}).get("content")
                if content:
                    text += content
    elapsed = time.perf_counter() - t0

    if "TRIGGER_START" in text:
        text = text.rsplit("TRIGGER_START", 1)[-1].strip()

    return text.strip(), completion_tokens, finish_reason, elapsed


def run_case(label, student_msg):
    print(f"\n{'='*70}\n  {label}\n  STUDENT: {student_msg}\n{'='*70}")

    # Pass 1: outline
    outline_messages = [
        {"role": "system", "content": SYSTEM_PERSONA},
        {"role": "user", "content": student_msg},
        {"role": "system", "content": OUTLINE_REQUEST},
    ]
    print("\n--- PASS 1: outline ---")
    outline, tok1, fin1, t1 = chat(outline_messages, max_tokens=250, temperature=0.4)
    points = re.findall(r"^\s*\d+[\.\)].*$", outline, flags=re.MULTILINE)
    print(f"  tokens: {tok1}, time: {t1:.2f}s, finish: {fin1}, points: {len(points)}")
    print(f"  outline:\n{outline}")

    if len(points) < 2:
        print("  ! outline rejected (less than 2 points)")
        return

    # Pass 2: delivery with [END] stop
    delivery = [
        {"role": "system", "content": SYSTEM_PERSONA},
        {"role": "user", "content": student_msg},
        {"role": "assistant", "content": outline},
        {"role": "system", "content": DELIVERY_INSTRUCTIONS_TMPL.format(marker=END_MARKER)},
    ]
    print("\n--- PASS 2: delivery (stop=[END]) ---")
    answer, tok2, fin2, t2 = chat(delivery, max_tokens=5000, temperature=0.6, stop=[END_MARKER])
    print(f"  tokens: {tok2}, time: {t2:.2f}s, finish: {fin2}")
    print(f"  stopped_by_marker: {fin2 == 'stop'}")
    print(f"  answer ({len(answer)} chars):\n{answer[:600]}{'...' if len(answer) > 600 else ''}")
    if "[END]" in answer:
        print("  ! WARN: [END] marker leaked into output")
    if "[ПУНКТ" in answer:
        print("  i [ПУНКТ N] markers present (expected to be stripped client-side)")


def main():
    cases = [
        ("Long explanation (RAG)", "Расскажи подробно как работает RAG-система."),
        ("Comparison", "Сравни трансформер и RNN, какой лучше для диалоговых ассистентов и почему."),
        ("Short / no skeleton", "Привет"),  # would skip skeleton in real Prof, but we'll force-test it
    ]
    for label, msg in cases:
        run_case(label, msg)


if __name__ == "__main__":
    main()
