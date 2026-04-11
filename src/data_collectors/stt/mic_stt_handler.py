"""Direct microphone → faster-whisper STT handler.

Captures audio from a physical microphone using sounddevice,
detects speech via energy-based VAD, and transcribes with faster-whisper.
Does NOT depend on RealtimeSTT or VB-Cable.
"""

import io
import os
import sys
import time

import numpy as np
import sounddevice as sd

if __name__ == "__main__":
    sys.path.append(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )

from data_collectors.stt.stt_fasterwhisper import FasterWhisperSTT
from data_flow.ctx_handler import CtxHandler
from data_schema.chat_structures import EventBase
from data_schema.ctx_structures import CtxSwarmType
from utils.time_helper import eztime
from utils.patterns import BACKCHANNEL_PATTERNS

# Audio params
SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_DURATION_MS = 100  # ms per read block
BLOCK_SIZE = int(SAMPLE_RATE * BLOCK_DURATION_MS / 1000)

# VAD params — energy-based
SILENCE_THRESHOLD = 200  # RMS threshold (tuned for fifine on low gain)
SPEECH_MIN_BLOCKS = 4  # min blocks (~0.4s) to count as speech
SILENCE_AFTER_SPEECH_BLOCKS = 10  # ~1.0s of silence to finalize (was 5/0.5s)


def find_mic_device(device_name: str) -> int:
    """Find input device by name, prefer MME (lowest idx)."""
    devices = sd.query_devices()
    matches = []
    for i, d in enumerate(devices):
        if d["max_input_channels"] > 0 and device_name.lower() in d["name"].lower():
            matches.append((i, d["name"]))
    if matches:
        # Prefer lowest index (MME) for best compatibility
        best = min(matches, key=lambda x: x[0])
        _stt_log(f"[MIC-STT] Selected device {best[0]}: {best[1]}")
        return best[0]
    _stt_log(f"[MIC-STT] Device '{device_name}' not found, using default")
    return sd.default.device[0]


def _stt_log(msg):
    """Log to file since subprocess stdout is lost on Windows."""
    import datetime
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open("data/stt_log.txt", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


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
            curr_row.append(min(prev_row[j + 1] + 1, curr_row[j] + 1, prev_row[j] + (c1 != c2)))
        prev_row = curr_row
    return prev_row[-1]


def _correct_with_vocabulary(text: str, rag_vocab: set) -> str:
    """Apply fuzzy correction using RAG vocabulary terms."""
    if not rag_vocab or not text:
        return text
    words = text.split()
    corrected = []
    for word in words:
        word_clean = word.strip(".,;:!?")
        # Skip short words — too many false positives at dist=2
        if len(word_clean) < 5:
            corrected.append(word)
            continue
        word_lower = word_clean.lower()
        best_match = None
        best_dist = 3  # max distance threshold
        for term in rag_vocab:
            if len(term) < 5:
                continue  # don't match against short terms either
            if abs(len(word_lower) - len(term.lower())) > 3:
                continue
            dist = _levenshtein(word_lower, term.lower())
            if 0 < dist <= 2 and dist < best_dist:
                best_match = term
                best_dist = dist
        if best_match:
            _stt_log(f"[STT-CORRECT] '{word}' -> '{best_match}' (dist={best_dist})")
            corrected.append(best_match)
        else:
            corrected.append(word)
    return " ".join(corrected)


# STT accumulator state
_stt_accumulator = []
_stt_last_segment_time = 0.0
_STT_ACCUMULATE_PAUSE = 2.0  # seconds of silence = "end of thought"
_STT_ACCUMULATE_MAX_CHARS = 500


def _flush_accumulator(ctx_handler: CtxHandler, ctx_swarm: CtxSwarmType):
    """Send accumulated STT segments as one message."""
    global _stt_accumulator
    if not _stt_accumulator:
        # No speech content — was noise. Clear flag.
        ctx_swarm["voice"]["student_speaking"] = False
        return
    full_text = " ".join(_stt_accumulator)
    _stt_accumulator = []
    _stt_log(f"[MIC-STT] Flushed accumulator: '{full_text}'")

    user = ctx_swarm["game"].get("last_talking_player", "Student") or "Student"
    event = EventBase(
        processing_timestamp=time.time_ns(),
        date=eztime(),
        env="voice",
        user=user,
        type="chat",
        msg=full_text,
        filter_results={"acceptable": True},
    )
    ctx_handler.add_message(event)
    # Student finished speaking — message is ready for agent
    ctx_swarm["voice"]["student_speaking"] = False


def mic_stt_handler(
    ctx_swarm: CtxSwarmType,
    audio_device_index: int = None,
    audio_device_name: str = "",
):
    """Main loop: capture mic → VAD → transcribe → accumulate → add to ctx_chat."""
    global _stt_accumulator, _stt_last_segment_time
    # Clear log
    try:
        open("data/stt_log.txt", "w").close()
    except Exception:
        pass
    _stt_log("[MIC-STT] Starting...")
    ctx_handler = CtxHandler(ctx_swarm)
    device = os.getenv("STT_COMPUTE_DEVICE", "cuda")

    if audio_device_index is None and audio_device_name:
        audio_device_index = find_mic_device(audio_device_name)

    # RAG vocabulary for contextual STT correction (loaded lazily from ctx_swarm)
    rag_vocab = set()
    rag_vocab_loaded = False

    _stt_log(f"[MIC-STT] Device index: {audio_device_index}, name: {audio_device_name}")
    _stt_log(f"[MIC-STT] Loading Whisper on {device}...")
    recognizer = FasterWhisperSTT(device=device)
    _stt_log("[MIC-STT] Ready! Listening...")

    speech_buffer = []
    silence_count = 0
    is_speaking = False

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=BLOCK_SIZE,
            device=audio_device_index,
        ) as stream:
            while ctx_swarm["env"]["actived"]:
                data, overflowed = stream.read(BLOCK_SIZE)
                audio_chunk = data[:, 0]  # mono
                rms = np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2))

                # Lazy-load RAG vocabulary once available
                if not rag_vocab_loaded:
                    raw = ctx_swarm["env"].get("rag_vocabulary", [])
                    if raw:
                        rag_vocab = set(raw)
                        rag_vocab_loaded = True
                        _stt_log(f"[MIC-STT] RAG vocabulary loaded: {len(rag_vocab)} terms")

                # Check accumulator flush (every VAD block = ~100ms)
                if _stt_accumulator:
                    pause = time.time() - _stt_last_segment_time
                    total_chars = sum(len(s) for s in _stt_accumulator)
                    if pause > _STT_ACCUMULATE_PAUSE or (total_chars > _STT_ACCUMULATE_MAX_CHARS and pause > 1.0):
                        _flush_accumulator(ctx_handler, ctx_swarm)

                if rms > SILENCE_THRESHOLD:
                    # Speech detected
                    if not is_speaking:
                        is_speaking = True
                        speech_buffer.clear()
                        silence_count = 0
                        _stt_log(f"[MIC-STT] Speech started (RMS={rms:.0f})")
                        # IMMEDIATE interrupt: stop TTS + signal agent to pause
                        tts_q = ctx_swarm["tts_queue"]
                        tts_q[:] = []
                        tts_q.append({"text": "interrupt", "emotion": "interrupt"})
                        ctx_swarm["voice"]["student_speaking"] = True
                        _stt_log("[MIC-STT] Immediate TTS interrupt + student_speaking=True")
                    speech_buffer.append(audio_chunk.copy())
                    silence_count = 0
                else:
                    if is_speaking:
                        speech_buffer.append(audio_chunk.copy())
                        silence_count += 1
                        if silence_count >= SILENCE_AFTER_SPEECH_BLOCKS:
                            # Speech ended — clear student_speaking after transcription
                            is_speaking = False
                            if len(speech_buffer) >= SPEECH_MIN_BLOCKS:
                                _transcribe_and_accumulate(
                                    recognizer, speech_buffer, ctx_handler, ctx_swarm, rag_vocab
                                )
                            else:
                                print("[MIC-STT] Too short, skipping")
                                ctx_swarm["voice"]["student_speaking"] = False
                            speech_buffer.clear()
    except Exception as e:
        _stt_log(f"[MIC-STT] Error: {e}")
        import traceback
        traceback.print_exc()

    print("[MIC-STT] Exiting")


def _transcribe_and_accumulate(
    recognizer: FasterWhisperSTT,
    speech_buffer: list,
    ctx_handler: CtxHandler,
    ctx_swarm: CtxSwarmType,
    rag_vocab: set,
):
    """Transcribe buffered speech, accumulate segments, handle backchannels."""
    global _stt_accumulator, _stt_last_segment_time

    audio = np.concatenate(speech_buffer)
    duration = len(audio) / SAMPLE_RATE
    _stt_log(f"[MIC-STT] Transcribing {duration:.1f}s audio...")

    # Convert to WAV bytes for faster-whisper
    from pydub import AudioSegment

    audio_segment = AudioSegment(
        data=audio.tobytes(),
        sample_width=2,  # int16
        frame_rate=SAMPLE_RATE,
        channels=1,
    )
    wav_io = io.BytesIO()
    audio_segment.export(wav_io, format="wav")
    wav_io.seek(0)

    try:
        result = recognizer.pipeline(wav_io)
        text = result.get("text", "").strip()
    except Exception as e:
        print(f"[MIC-STT] Transcription error: {e}")
        return

    if not text or len(text) < 2:
        print("[MIC-STT] Empty result, skipping")
        return

    # STT corrections: common misrecognitions in course context
    import re as _re
    _STT_FIXES = [
        (_re.compile(r'\bрак\b', _re.IGNORECASE), 'RAG'),
        (_re.compile(r'\bРГ\b'), 'RAG'),
    ]
    for pattern, replacement in _STT_FIXES:
        text = pattern.sub(replacement, text)

    # RAG vocabulary correction (feature 7)
    text = _correct_with_vocabulary(text, rag_vocab)

    _stt_log(f"[MIC-STT] >>> {text}")

    # Backchannel detection: "угу/ага" — don't trigger agent, but allow accumulation
    text_stripped = text.strip().lower().rstrip(".!?,")
    if text_stripped in BACKCHANNEL_PATTERNS:
        _stt_log(f"[STT] Backchannel: '{text}'")
        # Mark as noise so agent can ignore it
        ctx_swarm["env"]["last_stt_backchannel"] = True
        return

    # Mark as real speech (not noise/backchannel)
    ctx_swarm["env"]["last_stt_backchannel"] = False

    # Accumulate segments — interrupt already happened at speech start
    _stt_accumulator.append(text)
    _stt_last_segment_time = time.time()


if __name__ == "__main__":
    from data_schema.structure_templates import create_ctx_swarm

    ctx_swarm = create_ctx_swarm()
    device_name = os.getenv("SOUND_DEVICE_IN", "fifine")
    mic_stt_handler(ctx_swarm, audio_device_name=device_name)
