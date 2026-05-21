"""Audio capture: microphone + energy VAD + faster-whisper STT.

Ported from src/data_collectors/stt/mic_stt_handler.py.
All multiprocessing.Manager / ctx_swarm / CtxHandler references have been
replaced with plain in-process primitives.

Thread contract (identical to the Phase-1 console stub):
  * speech onset   -> interrupt.set()   (fires as soon as sustained speech is confirmed)
  * utterance done -> input_q.put(text) (plain str, transcribed + cleaned)
"""
from __future__ import annotations

import io
import os
import queue
import re
import threading
import time
from typing import Optional, Set

import numpy as np
import sounddevice as sd
from pydub import AudioSegment

from tutor.audio.stt import FasterWhisperSTT
from tutor.util import log

# ---------------------------------------------------------------------------
# Audio / VAD constants  (lifted verbatim from mic_stt_handler.py)
# ---------------------------------------------------------------------------
SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_DURATION_MS = 100          # ms per read block
BLOCK_SIZE = int(SAMPLE_RATE * BLOCK_DURATION_MS / 1000)

SILENCE_THRESHOLD = 300          # base RMS gate during silence
SILENCE_THRESHOLD_WHILE_TTS = 700  # raised gate while TTS is active
SPEECH_MIN_BLOCKS = 4            # ~0.4s to confirm real speech
SILENCE_AFTER_SPEECH_BLOCKS = 10  # ~1.0s of silence to finalize utterance

# Accumulator: collect short segments before flushing to agent
_STT_ACCUMULATE_PAUSE = 2.0      # seconds of silence = "end of thought"
_STT_ACCUMULATE_MAX_CHARS = 500

# Confidence gate: drop chunks below this language probability
_STT_CONFIDENCE_MIN = 0.6

# Hallucination blacklist: phrases faster-whisper invents on silence/noise
_STT_HALLUCINATIONS: Set[str] = {
    "спасибо за просмотр", "спасибо за внимание",
    "подписывайтесь на канал", "ставьте лайки",
    "продолжение следует", "субтитры подготовил",
    "субтитры подготовлены",
    "до свидания", "до встречи",
    "продолжение в следующей серии",
}

# STT corrections: common misrecognitions in course context
_STT_FIXES = [
    (re.compile(r'\bрак\b', re.IGNORECASE), 'RAG'),
    (re.compile(r'\bРГ\b'), 'RAG'),
]

# Backchannel patterns: brief acknowledgements that should not trigger the agent
_BACKCHANNEL_PATTERNS: Set[str] = {
    "угу", "ага", "ну да", "понятно", "ясно", "окей", "ок", "так",
    "хорошо", "ладно", "да да", "мгм", "ммм", "хм", "ну",
    "понял", "логично", "верно", "точно", "согласен",
}


# ---------------------------------------------------------------------------
# Helpers (lifted verbatim from mic_stt_handler.py)
# ---------------------------------------------------------------------------

def find_mic_device(device_name: str) -> int:
    """Find input device by name; prefer MME (lowest index)."""
    devices = sd.query_devices()
    matches = []
    for i, d in enumerate(devices):
        if d["max_input_channels"] > 0 and device_name.lower() in d["name"].lower():
            matches.append((i, d["name"]))
    if matches:
        best = min(matches, key=lambda x: x[0])
        log("capture", f"selected device {best[0]}: {best[1]}")
        return best[0]
    log("capture", f"device '{device_name}' not found, using default")
    return sd.default.device[0]


def _levenshtein(s1: str, s2: str) -> int:
    """Levenshtein edit distance."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            curr_row.append(
                min(prev_row[j + 1] + 1, curr_row[j] + 1, prev_row[j] + (c1 != c2))
            )
        prev_row = curr_row
    return prev_row[-1]


def _correct_with_vocabulary(text: str, rag_vocab: Set[str]) -> str:
    """Apply fuzzy correction using RAG vocabulary terms."""
    if not rag_vocab or not text:
        return text
    words = text.split()
    corrected = []
    for word in words:
        word_clean = word.strip(".,;:!?")
        if len(word_clean) < 5:
            corrected.append(word)
            continue
        word_lower = word_clean.lower()
        best_match = None
        best_dist = 3
        for term in rag_vocab:
            if len(term) < 5:
                continue
            if abs(len(word_lower) - len(term.lower())) > 3:
                continue
            dist = _levenshtein(word_lower, term.lower())
            if 0 < dist <= 2 and dist < best_dist:
                best_match = term
                best_dist = dist
        if best_match:
            log("capture", f"STT-CORRECT '{word}' -> '{best_match}' (dist={best_dist})")
            corrected.append(best_match)
        else:
            corrected.append(word)
    return " ".join(corrected)


# ---------------------------------------------------------------------------
# CaptureThread
# ---------------------------------------------------------------------------

class CaptureThread(threading.Thread):
    """Microphone capture with energy VAD and faster-whisper transcription.

    Constructor params
    ------------------
    input_q     : queue.Queue  — finished utterances (plain str) go here.
    interrupt   : threading.Event — set on speech onset; cleared by the agent
                  when it begins its response.
    tts_active  : threading.Event (optional) — when set by PlaybackThread,
                  the VAD threshold is raised to reject TTS bleed-through.
    rag_vocab   : set of str (optional) — RAG term vocabulary for fuzzy
                  STT correction; may be replaced live via set_vocabulary().
    device_name : str — substring match for sounddevice input device name.
    """

    def __init__(
        self,
        input_q: queue.Queue,
        interrupt: threading.Event,
        tts_active: Optional[threading.Event] = None,
        rag_vocab: Optional[Set[str]] = None,
        device_name: str = "",
    ):
        super().__init__(name="capture", daemon=True)
        self._input_q = input_q
        self._interrupt = interrupt
        self._tts_active = tts_active  # anti-echo gate
        self._rag_vocab: Set[str] = set(rag_vocab) if rag_vocab else set()
        self._vocab_lock = threading.Lock()
        self._device_name = device_name
        self._running = True
        # Set once the mic stream is open — app.py waits on this to play
        # the audible "ready" cue.
        self.ready = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_vocabulary(self, vocab: Set[str]) -> None:
        """Replace RAG vocabulary for fuzzy STT correction (hot-swap safe)."""
        with self._vocab_lock:
            self._rag_vocab = set(vocab)
        log("capture", f"vocabulary updated: {len(self._rag_vocab)} terms")

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Thread body
    # ------------------------------------------------------------------

    def run(self) -> None:
        device_index: Optional[int] = None
        if self._device_name:
            device_index = find_mic_device(self._device_name)

        stt_device = os.getenv("STT_COMPUTE_DEVICE", "cuda")
        log("capture", f"loading Whisper on {stt_device}...")
        recognizer = FasterWhisperSTT(device=stt_device)
        log("capture", "Whisper ready — listening")

        speech_buffer: list = []
        silence_count = 0
        is_speaking = False
        # True if the professor was voicing when this utterance began — i.e.
        # the student actually interrupted (vs. asking after a finished answer).
        was_interruption = False

        # Per-run accumulator state (avoids module-level mutable globals)
        stt_accumulator: list = []
        stt_last_segment_time: float = 0.0

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=BLOCK_SIZE,
                device=device_index,
            ) as stream:
                self.ready.set()   # mic stream open — pipeline is listening
                while self._running:
                    data, _overflowed = stream.read(BLOCK_SIZE)
                    audio_chunk = data[:, 0]  # mono
                    rms = float(np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2)))

                    # Check accumulator flush (~every 100 ms)
                    if stt_accumulator:
                        pause = time.time() - stt_last_segment_time
                        total_chars = sum(len(s) for s in stt_accumulator)
                        if pause > _STT_ACCUMULATE_PAUSE or (
                            total_chars > _STT_ACCUMULATE_MAX_CHARS and pause > 1.0
                        ):
                            full_text = " ".join(stt_accumulator)
                            stt_accumulator = []
                            log("capture", f"flush accumulator: '{full_text}'")
                            self._input_q.put((full_text, was_interruption))
                            is_speaking = False

                    # Anti-echo: raise the gate while TTS is actively playing
                    _tts_on = (
                        self._tts_active is not None and self._tts_active.is_set()
                    )
                    gate = SILENCE_THRESHOLD_WHILE_TTS if _tts_on else SILENCE_THRESHOLD

                    if rms > gate:
                        # ---- Speech detected ----
                        if not is_speaking:
                            is_speaking = True
                            speech_buffer.clear()
                            silence_count = 0
                            # The professor voicing right now => this is a
                            # real interruption, not an independent question.
                            was_interruption = _tts_on
                            log("capture", f"speech started (RMS={rms:.0f}, "
                                           f"interruption={was_interruption})")
                            # Signal the agent immediately on first speech sample
                            self._interrupt.set()
                        speech_buffer.append(audio_chunk.copy())
                        silence_count = 0
                    else:
                        if is_speaking:
                            speech_buffer.append(audio_chunk.copy())
                            silence_count += 1

                            # Interrupt TTS after SPEECH_MIN_BLOCKS confirmed
                            # (interrupt was already set at speech onset above;
                            # this is a no-op if already set, which is fine).
                            if len(speech_buffer) == SPEECH_MIN_BLOCKS:
                                self._interrupt.set()
                                log(
                                    "capture",
                                    f"TTS interrupt confirmed after "
                                    f"{SPEECH_MIN_BLOCKS} blocks",
                                )

                            if silence_count >= SILENCE_AFTER_SPEECH_BLOCKS:
                                is_speaking = False
                                text = None
                                if len(speech_buffer) >= SPEECH_MIN_BLOCKS:
                                    text = self._transcribe(
                                        recognizer, speech_buffer
                                    )
                                else:
                                    log("capture", "too short, skipping")
                                if text:
                                    stt_accumulator.append(text)
                                    stt_last_segment_time = time.time()
                                    # Flush immediately — one utterance per
                                    # silence window is the simple path.
                                    full_text = " ".join(stt_accumulator)
                                    stt_accumulator = []
                                    log("capture", f"utterance: '{full_text}'")
                                    self._input_q.put((full_text, was_interruption))
                                elif was_interruption:
                                    # Interrupt halted playback but STT got
                                    # nothing usable (cough / noise). Tell the
                                    # agent to resume the cut-off answer.
                                    log("capture",
                                        "interruption, no transcript - resume signal")
                                    self._input_q.put(("", was_interruption))
                                speech_buffer.clear()
        except Exception as exc:
            log("capture", f"error: {exc}")
            import traceback
            traceback.print_exc()
        log("capture", "exiting")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _transcribe(
        self,
        recognizer: FasterWhisperSTT,
        speech_buffer: list,
    ) -> Optional[str]:
        """Transcribe buffered speech; return cleaned text or None."""
        audio = np.concatenate(speech_buffer)
        duration = len(audio) / SAMPLE_RATE
        log("capture", f"transcribing {duration:.1f}s audio...")

        audio_segment = AudioSegment(
            data=audio.tobytes(),
            sample_width=2,
            frame_rate=SAMPLE_RATE,
            channels=1,
        )
        wav_io = io.BytesIO()
        audio_segment.export(wav_io, format="wav")
        wav_io.seek(0)

        try:
            result = recognizer.pipeline(wav_io)
            text = result.get("text", "").strip()
            lang_prob = float(result.get("language_probability", 1.0) or 0.0)
        except Exception as exc:
            log("capture", f"transcription error: {exc}")
            return None

        if not text or len(text) < 2:
            return None

        # Confidence gate
        if lang_prob < _STT_CONFIDENCE_MIN:
            log(
                "capture",
                f"low confidence (lang_prob={lang_prob:.2f}), skipping: "
                f"'{text[:60]}'",
            )
            return None

        # Hallucination blacklist
        text_lower = text.strip().lower().rstrip(".!?,")
        if text_lower in _STT_HALLUCINATIONS:
            log("capture", f"hallucination filtered: '{text}'")
            return None

        # STT corrections
        for pattern, replacement in _STT_FIXES:
            text = pattern.sub(replacement, text)

        # RAG vocabulary fuzzy correction
        with self._vocab_lock:
            vocab_snapshot = self._rag_vocab.copy()
        text = _correct_with_vocabulary(text, vocab_snapshot)

        # Backchannel detection: brief acknowledgements do not reach the agent
        text_stripped = text.strip().lower().rstrip(".!?,")
        if text_stripped in _BACKCHANNEL_PATTERNS:
            log("capture", f"backchannel filtered: '{text}'")
            return None

        log("capture", f">>> {text}")
        return text
