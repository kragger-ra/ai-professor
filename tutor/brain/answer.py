"""The Answer object and the answer stack — core of interrupt-resume.

An `Answer` is the professor's response stored SEPARATELY from its voicing:
the generator (LLM stream) fills `.sentences`; the voicer reads them and
advances `.voiced_index`. Because the two are decoupled, an interrupted
answer survives intact in memory and can be re-voiced later with NO LLM call.
That is what makes a resume after a (minor) interruption instant and
hang-proof.

The `AnswerStack` gives nested follow-up questions
(question -> sub-question -> sub-sub-question) with a hard depth cap: a 4th
level is refused, not pushed, so the dialogue cannot spiral. The refused
question is parked via `defer` and raised again once the stack unwinds.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

# question + 2 nested follow-ups. A 4th follow-up is deferred, not pushed —
# the user's rule: "больше человек не вытерпит".
MAX_STACK_DEPTH = 3


@dataclass
class Answer:
    """One professor response: stored thoughts, decoupled from voicing.

    The generator only appends to `sentences` and flips `generating` off.
    The voicer only reads `sentences` and advances `voiced_index`. They run
    on different threads and never block each other.
    """

    question: str
    sentences: list[str] = field(default_factory=list)
    voiced_index: int = 0          # how many sentences have been voiced
    generating: bool = True        # is the LLM still producing this answer
    # Sub-sentence resume: when a sentence is cut mid-playback (button pause
    # or a live interrupt that turns into a resume), we remember which
    # sentence was cut and at what sample offset (in source SR samples) so
    # the next play continues from the same point instead of restarting
    # the whole sentence. -1 means "no partial — start the sentence fresh".
    partial_idx: int = -1
    partial_offset: int = 0

    def add_sentence(self, text: str) -> None:
        """Generator side: store one freshly produced sentence."""
        self.sentences.append(text)

    def finish_generation(self) -> None:
        """Generator side: the LLM stream for this answer is complete."""
        self.generating = False

    def mark_voiced(self, count: int = 1) -> None:
        """Voicer side: record that `count` more sentences were spoken."""
        self.voiced_index = min(self.voiced_index + count, len(self.sentences))

    @property
    def unvoiced(self) -> list[str]:
        """Sentences not yet spoken — exactly what a resume would voice."""
        return self.sentences[self.voiced_index:]

    @property
    def fully_voiced(self) -> bool:
        """True once generation is done and every sentence has been voiced."""
        return not self.generating and self.voiced_index >= len(self.sentences)


class AnswerStack:
    """Stack of in-progress answers for nested follow-up questions.

    depth 0 = the root answer; `MAX_STACK_DEPTH` caps how deep follow-ups go.
    `push` returns False when the cap is hit — the caller then speaks the
    "let's finish this first" line and parks the question via `defer`.
    """

    def __init__(self) -> None:
        self._stack: list[Answer] = []
        self._deferred: list[str] = []   # questions refused at the depth cap
        self._lock = threading.Lock()

    @property
    def depth(self) -> int:
        with self._lock:
            return len(self._stack)

    @property
    def current(self) -> Answer | None:
        """The answer currently on top — the one being voiced."""
        with self._lock:
            return self._stack[-1] if self._stack else None

    def push(self, answer: Answer) -> bool:
        """Add a new (sub-)answer. False if the depth cap is already reached."""
        with self._lock:
            if len(self._stack) >= MAX_STACK_DEPTH:
                return False
            self._stack.append(answer)
            return True

    def pop(self) -> Answer | None:
        """Drop the finished top answer; return the one to resume, or None."""
        with self._lock:
            if self._stack:
                self._stack.pop()
            return self._stack[-1] if self._stack else None

    def defer(self, question: str) -> None:
        """Park a question refused at the depth cap, to raise on unwind."""
        with self._lock:
            self._deferred.append(question)

    def take_deferred(self) -> str | None:
        """Pull the next parked question once the stack has unwound."""
        with self._lock:
            return self._deferred.pop(0) if self._deferred else None

    def clear(self) -> None:
        """Reset — used on a fresh top-level question or a hard recovery."""
        with self._lock:
            self._stack.clear()
            self._deferred.clear()


if __name__ == "__main__":
    # --- self-test: Answer decoupling ------------------------------------
    a = Answer(question="что такое RAG")
    a.add_sentence("RAG — это поиск по материалам курса.")
    a.add_sentence("Он находит нужный фрагмент.")
    a.add_sentence("И передаёт его модели.")
    a.mark_voiced(1)                       # interrupted after 1 sentence
    assert a.unvoiced == [
        "Он находит нужный фрагмент.",
        "И передаёт его модели.",
    ], a.unvoiced
    assert not a.fully_voiced
    a.finish_generation()
    a.mark_voiced(2)
    assert a.fully_voiced

    # --- self-test: AnswerStack depth cap + defer ------------------------
    s = AnswerStack()
    assert s.push(Answer("q1")) is True    # depth 1
    assert s.push(Answer("q2")) is True    # depth 2
    assert s.push(Answer("q3")) is True    # depth 3
    assert s.push(Answer("q4")) is False   # cap hit -> refuse
    s.defer("q4")
    assert s.depth == 3
    assert s.current.question == "q3"
    assert s.pop().question == "q2"        # unwind
    assert s.pop().question == "q1"
    assert s.pop() is None                 # empty
    assert s.take_deferred() == "q4"       # parked question resurfaces
    assert s.take_deferred() is None

    print("answer.py self-test PASSED")
