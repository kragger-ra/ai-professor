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
        model_hf_repo = os.getenv(
            "FASTER_WHISPER_MODEL_NAME",
            "dvislobokov/faster-whisper-large-v3-turbo-russian",
        )
        # model_dir = os.path.join(
        #     REPO_DATA_PATH,
        #     "speech"
        # )
        self.model = WhisperModel(
            model_hf_repo,  # "base",  # model_hf_repo,
            device=device,
            # model_root=model_dir,
        )

    def pipeline(self, pcm: bytes, *args, **kwargs):
        """Pipeline for speech-to-text processing

        INPUT FORMAT: WAV BYTES WITH HEADING!
        """
        segments, info = self.model.transcribe(
            pcm,
            language="ru",
            multilingual=True,
            # initial_prompt="Я ОЧЕНЬ ЗОЛ! *angry*\nБраво! *claps*\nСейчас я говорю с NetTyan, автономной # нейростримершей. Мы играем в Minecraft. *serios*\nЧтобы телепортироваться на spawn, я могу # попросить её написать команду /spawn.",
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
    bad_audio = AudioSegment.from_mp3(
        r"C:\Pets\NetTyan\MC\NetTyanNew\run\voicechat_recordings\2025-03-08-12-44-35-678\Chochok.mp3"
    )
    audio = AudioSegment.from_wav(
        r"C:\Pets\NetTyan\MC\NetTyanNew\run\voicechat_recordings\2025-03-08-12-44-35-678\ПропишиSpawn.wav"
    )
    recognizer = FasterWhisperSTT("cuda")
    print("11111?")
    print("Recognized:", recognizer.transcribe_audio(audio))
