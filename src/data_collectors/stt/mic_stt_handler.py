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
SPEECH_MIN_BLOCKS = 5  # min blocks (~0.5s) to count as speech
SILENCE_AFTER_SPEECH_BLOCKS = 15  # ~1.5s of silence to finalize


def find_mic_device(device_name: str) -> int:
    """Find input device by name, prefer MME (higher idx < 30)."""
    devices = sd.query_devices()
    matches = []
    for i, d in enumerate(devices):
        if d["max_input_channels"] > 0 and device_name in d["name"]:
            matches.append((i, d["name"]))
    if matches:
        best = max(matches, key=lambda x: x[0] if x[0] < 30 else 0)
        print(f"[MIC-STT] Selected device {best[0]}: {best[1]}")
        return best[0]
    print(f"[MIC-STT] Device '{device_name}' not found, using default")
    return sd.default.device[0]


def mic_stt_handler(
    ctx_swarm: CtxSwarmType,
    audio_device_index: int = None,
    audio_device_name: str = "",
):
    """Main loop: capture mic → VAD → transcribe → add to ctx_chat."""
    print("[MIC-STT] Starting...")
    ctx_handler = CtxHandler(ctx_swarm)
    device = os.getenv("STT_COMPUTE_DEVICE", "cuda")

    if audio_device_index is None and audio_device_name:
        audio_device_index = find_mic_device(audio_device_name)

    print(f"[MIC-STT] Loading Whisper on {device}...")
    recognizer = FasterWhisperSTT(device=device)
    print("[MIC-STT] Ready! Listening...")

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
                        print("[MIC-STT] Speech started")
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
        print(f"[MIC-STT] Error: {e}")
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
    print(f"[MIC-STT] Transcribing {duration:.1f}s audio...")

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

    print(f"[MIC-STT] >>> {text}")

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
    )
    ctx_handler.add_message(event)


if __name__ == "__main__":
    from data_schema.structure_templates import create_ctx_swarm

    ctx_swarm = create_ctx_swarm()
    device_name = os.getenv("SOUND_DEVICE_IN", "fifine")
    mic_stt_handler(ctx_swarm, audio_device_name=device_name)
