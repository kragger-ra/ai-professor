"""faster-whisper STT engine — clean wrapper, no IPC (ported from src/)."""
try:
    from faster_whisper import WhisperModel
except ImportError:
    import traceback

    print(
        "faster_whisper is not installed. Please install it via `pip install faster_whisper`"
    )
    traceback.print_exc()
import os

import numpy as np
from pydub import AudioSegment


class FasterWhisperSTT:
    def __init__(self, device: str = "cuda"):
        if device == "gpu":
            device = "cuda"
        self.device = device
        model_name = os.getenv("FASTER_WHISPER_MODEL_NAME", "large-v3-turbo")
        compute_type = os.getenv("STT_COMPUTE_TYPE", "").strip()
        if not compute_type:
            compute_type = "float16" if device == "cuda" else "int8"
        cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "whisper-models")
        self.model_name = model_name
        self.model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root=cache_dir,
        )
        print(
            f"[STT] Loaded {model_name} on {device} (compute_type={compute_type})",
            flush=True,
        )

    def pipeline(self, pcm: bytes, *args, **kwargs):
        """Pipeline for speech-to-text processing

        INPUT FORMAT: WAV BYTES WITH HEADING!

        Returns ``{"text": str, "language_probability": float}``. Callers that
        only read ``["text"]`` keep working; the new key lets the mic handler
        skip low-confidence chunks (noise / hallucinations).
        """
        beam = 1 if self.device == "cpu" else 5
        segments, info = self.model.transcribe(
            pcm,
            language="ru",
            beam_size=beam,
            # vad_filter is OFF on purpose: CaptureThread already gates speech
            # with its own energy VAD, and faster-whisper's internal Silero VAD
            # was discarding short clear utterances ("да давайте") as non-speech
            # — the whole clip came back empty. One VAD is enough.
            vad_filter=False,
            # condition_on_previous_text=True is the faster-whisper default and
            # drags the model into looping/echoing earlier turns once a session
            # runs long. Off for chat use.
            condition_on_previous_text=False,
        )
        got_text = "".join(segment.text for segment in segments)
        lang_prob = float(getattr(info, "language_probability", 1.0) or 0.0)
        return {"text": got_text, "language_probability": lang_prob}

    def transcribe_audio(self, audio: AudioSegment) -> str:
        # audio.export("tmp.wav", format="wav")
        # pcm =  np.array(audio.get_array_of_samples())
        asr = self.pipeline(audio.export(format="wav"))
        return asr["text"]
