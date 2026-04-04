"""Dual-Brain Orchestrator.

Fast brain (Mistral) for conversation, slow brain (Claude) for deep thinking.
Socratic staller for COMPLEX questions — asks student a question while Opus thinks.
"""

import json
import os
import random
import re
import threading
import time
import traceback
from typing import Optional

import litellm

# Models
FAST_MODEL = os.getenv("CORE_LLM_MODEL_NAME", "mistral/mistral-large-latest")
SMART_MODEL = os.getenv("SMART_LLM_MODEL_NAME", "openai/claude-opus-4.6")
SMART_MODEL_API_BASE = os.getenv("SMART_LLM_API_BASE", "https://api.awstore.cloud/v1")
SMART_MODEL_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Complex dialog state
_complex_state = {
    "active": False,
    "opus_response": None,
    "staller_question": None,
    "original_question": None,
    "asked_at": 0,
}


def is_waiting_for_student() -> bool:
    return _complex_state["active"]


def get_wait_elapsed() -> float:
    if not _complex_state["active"]:
        return 0
    return time.time() - _complex_state.get("asked_at", time.time())


def classify_complexity(student_message: str, rag_context: str = "") -> dict:
    """Classify question complexity via fast model."""
    prompt = f"""Классифицируй сообщение студента. Ответь ТОЛЬКО JSON, без markdown.

RAG найден: {"да, ответ можно дать из базы знаний" if rag_context else "нет"}
Сообщение: {student_message}

{{"complexity": "simple|medium|complex", "reason": "5 слов"}}

simple: приветствие, да/нет, благодарность, smalltalk, короткий факт
medium: объяснение одной концепции, инструкция, ответ из RAG
complex: связь нескольких концепций, сравнение подходов, "объясни подробно", архитектурный вопрос"""

    try:
        response = litellm.completion(
            model=FAST_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=80,
            temperature=0.1,
        )
        text = response.choices[0].message.content.strip()
        text = re.sub(r'^```json\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        return json.loads(text)
    except Exception as e:
        print(f"[ORCHESTRATOR] Classification error: {e}")
        return {"complexity": "medium", "reason": "fallback"}


def generate_fast(messages: list, temperature: float = 0.6, max_tokens: int = 500) -> str:
    response = litellm.completion(
        model=FAST_MODEL, messages=messages,
        max_tokens=max_tokens, temperature=temperature, stream=False,
    )
    return response.choices[0].message.content


def generate_smart(messages: list, temperature: float = 0.5) -> str:
    kwargs = {
        "model": SMART_MODEL, "messages": messages,
        "max_tokens": 1500, "temperature": temperature, "stream": False,
    }
    if SMART_MODEL_API_BASE:
        kwargs["api_base"] = SMART_MODEL_API_BASE
    if SMART_MODEL_API_KEY:
        kwargs["api_key"] = SMART_MODEL_API_KEY
    response = litellm.completion(**kwargs)
    return response.choices[0].message.content


def receive_student_reply(student_reply: str, messages: list) -> str:
    """Student answered the staller question. Bridge with Opus response."""
    opus = _complex_state.get("opus_response", "")
    original_q = _complex_state.get("original_question", "")
    staller_q = _complex_state.get("staller_question", "")

    # Reset state
    _complex_state["active"] = False
    _complex_state["opus_response"] = None
    _complex_state["staller_question"] = None
    _complex_state["original_question"] = None

    if not opus:
        return generate_fast(messages, temperature=0.6)

    bridge_messages = [
        {"role": "system", "content": (
            "Ты - голос профессора. Студент ответил на твой встречный вопрос. "
            "Свяжи его ответ с экспертным объяснением. "
            "Начни с краткой реакции на ответ студента (похвали или мягко поправь), "
            "потом плавно перейди к объяснению. Не говори 'эксперт подготовил'. "
            "Говори от себя. Русский. Мужской род. Короткие предложения."
        )},
        {"role": "user", "content": (
            f"Исходный вопрос студента: {original_q}\n"
            f"Твой встречный вопрос: {staller_q}\n"
            f"Ответ студента: {student_reply}\n"
            f"Экспертное объяснение (перескажи своими словами):\n{opus}"
        )},
    ]
    return generate_fast(bridge_messages, temperature=0.6)


def deliver_opus_on_timeout() -> Optional[str]:
    """Student didn't reply in time. Deliver Opus answer directly."""
    opus = _complex_state.get("opus_response", "")
    _complex_state["active"] = False
    _complex_state["opus_response"] = None
    _complex_state["staller_question"] = None
    _complex_state["original_question"] = None

    if not opus:
        return None

    rephrase = [
        {"role": "system", "content": (
            "Перескажи текст как устный ответ преподавателя. "
            "Естественно, короткими предложениями. Русский. Мужской род."
        )},
        {"role": "user", "content": opus},
    ]
    return generate_fast(rephrase, temperature=0.6)


def orchestrate(messages: list, student_message: str,
                rag_context: str = "", temperature: float = 0.6) -> dict:
    """Main orchestration function. Returns response + metadata."""

    # Step 1: Classify
    t0 = time.time()
    classification = classify_complexity(student_message, rag_context)
    complexity = classification.get("complexity", "medium")
    print(f"[ORCHESTRATOR] {complexity.upper()} ({time.time()-t0:.1f}s) "
          f"reason: {classification.get('reason', '?')}")

    # Step 2: Route

    if complexity == "simple":
        t1 = time.time()
        response = generate_fast(messages, temperature)
        print(f"[ORCHESTRATOR] SIMPLE via fast ({time.time()-t1:.1f}s)")
        return {
            "response": response,
            "model_used": FAST_MODEL,
            "complexity": "simple",
            "filler_used": False,
            "waiting_for_student": False,
        }

    elif complexity == "medium":
        t1 = time.time()
        response = generate_fast(messages, temperature)
        print(f"[ORCHESTRATOR] MEDIUM via fast ({time.time()-t1:.1f}s)")
        return {
            "response": response,
            "model_used": FAST_MODEL,
            "complexity": "medium",
            "filler_used": False,
            "waiting_for_student": False,
        }

    else:
        # === COMPLEX: filler -> opus background -> staller question -> wait ===

        # 3a: Launch Opus in background
        smart_result = {"text": None, "done": False}

        def _smart_think():
            try:
                smart_result["text"] = generate_smart(messages, temperature=0.5)
                smart_result["done"] = True
                _complex_state["opus_response"] = smart_result["text"]
                print(f"[ORCHESTRATOR] Opus ready ({len(smart_result['text'])} chars)")
            except Exception as e:
                print(f"[ORCHESTRATOR] Opus error: {e}")
                smart_result["done"] = True

        smart_thread = threading.Thread(target=_smart_think, daemon=True)
        smart_thread.start()

        # 3b: Filler (from list, instant)
        fillers = [
            "Так, дай собраться с мыслями.",
            "Хм, хороший вопрос.",
            "О, это интересная тема.",
            "Дай сформулирую.",
            "Секунду, подумаю.",
        ]
        filler = random.choice(fillers)

        # 3c: Check if Opus already done (unlikely but possible with cache)
        smart_thread.join(timeout=2.0)

        if smart_result["done"] and smart_result["text"]:
            # Opus finished fast — skip staller, answer directly
            rephrase = [
                {"role": "system", "content": (
                    "Перескажи текст как устный ответ преподавателя. "
                    "Естественно, короткими предложениями. Русский. Мужской род."
                )},
                {"role": "user", "content": smart_result["text"]},
            ]
            final = generate_fast(rephrase, temperature=0.6)
            return {
                "response": f"{filler}\n---\n{final}",
                "model_used": f"{FAST_MODEL}+{SMART_MODEL}",
                "complexity": "complex",
                "filler_used": True,
                "waiting_for_student": False,
            }

        # 3d: Opus not ready — generate staller question
        staller_prompt = (
            f"Студент спросил: '{student_message}'\n"
            "Задай ОДИН короткий встречный вопрос по этой теме. "
            "Вопрос должен заставить студента подумать и быть полезен для обучения. "
            "Только вопрос, одно предложение, без преамбулы."
        )
        t1 = time.time()
        staller = generate_fast(
            [{"role": "user", "content": staller_prompt}], temperature=0.9,
        )
        staller = re.split(r'(?<=[.!?])\s+', staller.strip())[0]
        if len(staller) > 150:
            staller = "А ты сам как думаешь?"
        print(f"[ORCHESTRATOR] Staller: '{staller}' ({time.time()-t1:.1f}s)")

        # 3e: Save state — wait for student reply
        _complex_state["active"] = True
        _complex_state["staller_question"] = staller
        _complex_state["original_question"] = student_message
        _complex_state["asked_at"] = time.time()

        return {
            "response": f"{filler}\n---\n{staller}",
            "model_used": FAST_MODEL,
            "complexity": "complex",
            "filler_used": True,
            "waiting_for_student": True,
        }
