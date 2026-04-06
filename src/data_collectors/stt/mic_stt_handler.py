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


def mic_stt_handler(
    ctx_swarm: CtxSwarmType,
    audio_device_index: int = None,
    audio_device_name: str = "",
):
    """Main loop: capture mic → VAD → transcribe → add to ctx_chat."""
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

                if rms > SILENCE_THRESHOLD:
                    # Speech detected
                    if not is_speaking:
                        is_speaking = True
                        speech_buffer.clear()
                        silence_count = 0
                        _stt_log(f"[MIC-STT] Speech started (RMS={rms:.0f})")
                    speech_buffer.append(audio_chunk.copy())
                    silence_count = 0
                else:
                    if is_speaking:
                        speech_buffer.append(audio_chunk.copy())
                        silence_count += 1
                        if silence_count >= SILENCE_AFTER_SPEECH_BLOCKS:
                            # Speech ended
                            is_speaking = False
                            if len(speech_buffer) >= SPEECH_MIN_BLOCKS:
                                _transcribe_and_send(
                                    recognizer, speech_buffer, ctx_handler, ctx_swarm
                                )
                            else:
                                print("[MIC-STT] Too short, skipping")
                            speech_buffer.clear()
    except Exception as e:
        _stt_log(f"[MIC-STT] Error: {e}")
        import traceback
        traceback.print_exc()

    print("[MIC-STT] Exiting")


def _transcribe_and_send(
    recognizer: FasterWhisperSTT,
    speech_buffer: list,
    ctx_handler: CtxHandler,
    ctx_swarm: CtxSwarmType,
):
    """Transcribe buffered speech and send to agent."""
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

    _stt_log(f"[MIC-STT] >>> {text}")

    # Interrupt TTS when real speech is recognized (not noise)
    if ctx_swarm["voice"]["is_speaking"]:
        tts_q = ctx_swarm["tts_queue"]
        tts_q[:] = []
        tts_q.append({"text": "interrupt", "emotion": "interrupt"})
        _stt_log("[MIC-STT] Interrupted TTS — student said something")

    user = ctx_swarm["game"].get("last_talking_player", "Student")
    if not user:
        user = "Student"
    event = EventBase(
        processing_timestamp=time.time_ns(),
        date=eztime(),
        env="voice",
        user=user,
        type="chat",
        msg=text,
        filter_results={"acceptable": True},
    )
    ctx_handler.add_message(event)


if __name__ == "__main__":
    from data_schema.structure_templates import create_ctx_swarm

    ctx_swarm = create_ctx_swarm()
    device_name = os.getenv("SOUND_DEVICE_IN", "fifine")
    mic_stt_handler(ctx_swarm, audio_device_name=device_name)
