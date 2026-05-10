try:
    from faster_whisper import WhisperModel
except ImportError:
    import traceback

    print(
        "faster_whisper is not installed. Please install it via `pip install faster_whisper`"
    )
    traceback.print_exc()
import os
import sys

import numpy as np
from pydub import AudioSegment

if __name__ == "__main__":
    sys.path.append(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )

from data_schema.structure_templates import REPO_DATA_PATH


class FasterWhisperSTT:
    def __init__(self, device: str = "cuda"):
        self.device = device
        model_name = os.getenv("FASTER_WHISPER_MODEL_NAME", "large-v3")
        compute_type = os.getenv("STT_COMPUTE_TYPE", "float16")
        cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "whisper-models")
        self.model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root=cache_dir,
        )

    def pipeline(self, pcm: bytes, *args, **kwargs):
        """Pipeline for speech-to-text processing

        INPUT FORMAT: WAV BYTES WITH HEADING!
        """
        beam = 1 if self.device == "cpu" else 5
        segments, info = self.model.transcribe(
            pcm,
            language="ru",
            beam_size=beam,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=400,
            ),
        )
        # print(segments, info)
        got_text = "".join(segment.text for segment in segments)
        asr = {"text": got_text}
        return asr

    def transcribe_audio(self, audio: AudioSegment) -> str:
        # audio.export("tmp.wav", format="wav")
        # pcm =  np.array(audio.get_array_of_samples())
        asr = self.pipeline(audio.export(format="wav"))
        return asr["text"]


if __name__ == "__main__":
    sample_path = os.getenv("STT_SAMPLE_WAV")
    if not sample_path:
        raise SystemExit("Set STT_SAMPLE_WAV to point at a test audio file")
    audio = AudioSegment.from_file(sample_path)
    recognizer = FasterWhisperSTT("cuda")
    print("Recognized:", recognizer.transcribe_audio(audio))
