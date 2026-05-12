"""Quiz + remediation loop for Tutor mode.

After a lecture, the tutor asks check questions, grades answers via SMART_MODEL,
identifies weak blocks (mistake count per source_block_id), and feeds them
back into a remediation cycle (re-explain block, retest, repeat).

Used by AI-Professor-Tutor only — Lecture build keeps the simpler quiz path
in core_agent._qa_quiz_step.
"""

import json
import os
import re
import traceback
from typing import Optional

import litellm

SMART_MODEL = os.getenv("SMART_LLM_MODEL_NAME", "anthropic/claude-opus-4-5")
SMART_MODEL_API_BASE = os.getenv("SMART_LLM_API_BASE", "")
SMART_MODEL_API_KEY = os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY", "")


def _smart_call(prompt: str, max_tokens: int = 600, temperature: float = 0.3) -> str:
    """Single SMART_MODEL completion. Returns raw text or raises."""
    kwargs = {
        "model": SMART_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if SMART_MODEL_API_BASE:
        kwargs["api_base"] = SMART_MODEL_API_BASE
    if SMART_MODEL_API_KEY:
        kwargs["api_key"] = SMART_MODEL_API_KEY
    response = litellm.completion(**kwargs)
    return response.choices[0].message.content.strip()


def _extract_json(text: str):
    """Strip markdown fences and parse JSON."""
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


class QuizSession:
    """Tracks quiz questions, answers, grades, and weak block accumulation."""

    MAX_ITERATIONS = 3
    GRADE_FAIL_THRESHOLD = 2  # grade < 2 counts as a mistake on source_block

    def __init__(self, blocks_delivered: list, topic: str = ""):
        # Defensive copy: store only what we need to grade against
        self.blocks = [dict(b) for b in (blocks_delivered or [])]
        self.topic = topic
        self.questions: list = []   # [{q, expected, source_block_id}]
        self.answers: list = []     # [{idx, reply, grade, weak_concepts}]
        self.weak_blocks: dict = {} # block_id (int) -> mistakes (int)
        self.iteration = 0          # remediation iterations consumed

    # --- Question generation -----------------------------------------------

    def generate_questions(self, n: int = 3) -> list:
        """Generate N structured quiz items via SMART_MODEL.

        Each item: {q: str, expected: list[str], source_block_id: int}.
        Falls back to deterministic key_points-based items if LLM fails.
        Returns the list of generated questions (also stored in self.questions).
        """
        if not self.blocks:
            self.questions = []
            return []

        block_lines = []
        for b in self.blocks:
            kp = b.get("key_points", [])
            block_lines.append(f"- блок id={b.get('id', '?')}: {'; '.join(kp[:3])}")
        blocks_text = "\n".join(block_lines)

        prompt = f"""Ты составляешь короткий проверочный квиз по только что прочитанной лекции.
Тема лекции: {self.topic or '(не указана)'}

Блоки лекции и их ключевые тезисы:
{blocks_text}

Составь {n} проверочных вопросов. Для каждого верни JSON-объект с полями:
- q: текст вопроса (одно предложение, на 5-15 секунд размышления, проверяет понимание, не запоминание)
- expected: список из 2-4 ключевых концепций, которые должны прозвучать в правильном ответе
- source_block_id: id блока (целое число), на котором основан вопрос

Покрой разные блоки. Не задавай вопрос, на который ответ — точная цитата.
Ответь ТОЛЬКО JSON-массивом из {n} объектов, без markdown."""

        try:
            text = _smart_call(prompt, max_tokens=800, temperature=0.4)
            data = _extract_json(text)
            if not isinstance(data, list):
                raise ValueError(f"Expected list, got {type(data)}")
            cleaned = []
            for item in data[:n]:
                if not isinstance(item, dict):
                    continue
                q = str(item.get("q", "")).strip()
                expected = item.get("expected", [])
                if isinstance(expected, str):
                    expected = [expected]
                expected = [str(x).strip() for x in expected if str(x).strip()]
                src = item.get("source_block_id")
                try:
                    src = int(src) if src is not None else None
                except (TypeError, ValueError):
                    src = None
                if q:
                    cleaned.append({
                        "q": q,
                        "expected": expected,
                        "source_block_id": src,
                    })
            self.questions = cleaned
            print(f"[QUIZ] Generated {len(cleaned)} structured questions")
            return self.questions
        except Exception as e:
            print(f"[QUIZ] LLM generation failed: {e}; using fallback")
            traceback.print_exc()
            self.questions = self._fallback_questions(n)
            return self.questions

    def _fallback_questions(self, n: int) -> list:
        """Deterministic backup: turn first key_point of each block into a question."""
        out = []
        for b in self.blocks[:n]:
            kp = b.get("key_points", [])
            if not kp:
                continue
            first = str(kp[0]).rstrip(".!? ")
            out.append({
                "q": f"Расскажи коротко про: {first}.",
                "expected": kp[:3],
                "source_block_id": b.get("id"),
            })
        return out

    # --- Grading -----------------------------------------------------------

    def grade_answer(self, idx: int, reply: str) -> dict:
        """Grade student's answer to questions[idx] via SMART_MODEL.

        Returns {grade: 0|1|2, weak_concepts: list[str]} (also appended to self.answers).
        Updates weak_blocks counter when grade < GRADE_FAIL_THRESHOLD.
        """
        if idx >= len(self.questions):
            raise IndexError(f"No question at index {idx} (have {len(self.questions)})")
        q = self.questions[idx]
        result = self._grade_via_llm(q, reply)
        if result is None:
            result = self._grade_heuristic(q, reply)

        record = {
            "idx": idx,
            "reply": reply,
            "grade": result["grade"],
            "weak_concepts": result.get("weak_concepts", []),
        }
        self.answers.append(record)

        # Track weak block on partial/wrong answer
        if record["grade"] < self.GRADE_FAIL_THRESHOLD and q.get("source_block_id") is not None:
            bid = q["source_block_id"]
            self.weak_blocks[bid] = self.weak_blocks.get(bid, 0) + 1

        return record

    def _grade_via_llm(self, q: dict, reply: str) -> Optional[dict]:
        prompt = f"""Оцени ответ студента на проверочный вопрос.

Вопрос: {q['q']}
Ключевые концепции, которые должны прозвучать (для верного ответа):
{json.dumps(q.get('expected', []), ensure_ascii=False)}

Ответ студента: {reply}

Оценка:
- 2 = верно (студент явно понял суть; названы ключевые концепции своими словами)
- 1 = частично (часть концепций упомянута, есть пробелы или неточности)
- 0 = неверно (концепции пропущены, путаница, или ответ не по теме)

Ответь ТОЛЬКО JSON: {{"grade": <0|1|2>, "weak_concepts": [<концепции, которые студент пропустил или ошибся>]}}"""
        try:
            text = _smart_call(prompt, max_tokens=300, temperature=0.2)
            data = _extract_json(text)
            grade = int(data.get("grade", 0))
            grade = max(0, min(2, grade))
            weak = data.get("weak_concepts", [])
            if isinstance(weak, str):
                weak = [weak]
            weak = [str(x).strip() for x in weak if str(x).strip()]
            return {"grade": grade, "weak_concepts": weak}
        except Exception as e:
            print(f"[QUIZ] LLM grading failed: {e}; using heuristic")
            return None

    def _grade_heuristic(self, q: dict, reply: str) -> dict:
        """Fallback grader: word-overlap with expected key concepts."""
        reply_words = set(re.findall(r"\w+", reply.lower()))
        expected = q.get("expected", [])
        if not expected or not reply_words:
            return {"grade": 0, "weak_concepts": expected[:]}
        hits = []
        misses = []
        for concept in expected:
            concept_words = set(re.findall(r"\w+", concept.lower()))
            # Match if any 4+ char word from concept appears in reply
            matched = any(w in reply_words for w in concept_words if len(w) >= 4)
            (hits if matched else misses).append(concept)
        ratio = len(hits) / len(expected)
        if ratio >= 0.7:
            grade = 2
        elif ratio >= 0.3:
            grade = 1
        else:
            grade = 0
        return {"grade": grade, "weak_concepts": misses}

    # --- Remediation control ----------------------------------------------

    def pick_weakest_block(self) -> Optional[int]:
        """Return block_id with most mistakes, or None if no weak blocks."""
        if not self.weak_blocks:
            return None
        return max(self.weak_blocks.items(), key=lambda kv: kv[1])[0]

    def find_block(self, block_id: int) -> Optional[dict]:
        """Look up the original block dict by id."""
        for b in self.blocks:
            if b.get("id") == block_id:
                return b
        return None

    def latest_weak_concepts(self, block_id: int) -> list:
        """Concepts the student missed on the most recent failed answer for this block."""
        for ans in reversed(self.answers):
            q = self.questions[ans["idx"]] if ans["idx"] < len(self.questions) else None
            if q and q.get("source_block_id") == block_id:
                return list(ans.get("weak_concepts", []))
        return []

    def mark_block_resolved(self, block_id: int) -> None:
        self.weak_blocks.pop(block_id, None)

    def bump_iteration(self) -> None:
        self.iteration += 1

    def is_done(self) -> bool:
        return not self.weak_blocks or self.iteration >= self.MAX_ITERATIONS

    # --- Retest -----------------------------------------------------------

    def generate_retest_question(self, block_id: int) -> Optional[dict]:
        """One fresh retest question on the given block, focused on missed concepts."""
        block = self.find_block(block_id)
        if not block:
            return None
        weak = self.latest_weak_concepts(block_id)
        kp = block.get("key_points", [])
        focus = ", ".join(weak) if weak else ", ".join(kp[:2])

        prompt = f"""Студент только что разобрал заново блок лекции и ему нужно проверочное задание.

Блок (тезисы): {kp}
Сфокусируйся на этих концепциях: {focus}

Сформулируй ОДИН короткий проверочный вопрос (одно предложение).
Ответь ТОЛЬКО JSON: {{"q": "...", "expected": ["...", "..."]}}"""
        try:
            text = _smart_call(prompt, max_tokens=250, temperature=0.4)
            data = _extract_json(text)
            q = str(data.get("q", "")).strip()
            expected = data.get("expected", [])
            if isinstance(expected, str):
                expected = [expected]
            expected = [str(x).strip() for x in expected if str(x).strip()]
            if not q:
                raise ValueError("empty q")
            item = {"q": q, "expected": expected, "source_block_id": block_id}
            self.questions.append(item)
            return item
        except Exception as e:
            print(f"[QUIZ] retest generation failed: {e}; fallback")
            item = {
                "q": f"Объясни ещё раз своими словами: {focus}.",
                "expected": weak or kp[:2],
                "source_block_id": block_id,
            }
            self.questions.append(item)
            return item
