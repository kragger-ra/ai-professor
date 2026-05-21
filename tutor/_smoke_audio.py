"""Audio-output check — synthesize one sentence via Vosk and play it.

Isolates the TTS + playback chain from the microphone/agent side:
  Vosk server reachable?  ->  synthesis returns audio?  ->  playback errors?

Run (from the repo root, with the Vosk TTS server up):
    python -m tutor._smoke_audio
"""
from __future__ import annotations

import traceback

from tutor.util import log


def main() -> None:
    log("audio-test", "importing vosk client + AudioProcessor...")
    from tutor.tts.vosk_client import vosk_tts_sentence
    from tutor.audio.playback import SOUND_DEVICE_OUT, AudioProcessor

    log("audio-test", f"SOUND_DEVICE_OUT = {SOUND_DEVICE_OUT!r}")

    log("audio-test", "synthesizing a test sentence via Vosk...")
    try:
        audio, sr = vosk_tts_sentence("Проверка звука. Раз, два, три.", "neutral")
    except Exception as exc:
        log("audio-test", f"FAIL: Vosk synthesis raised {type(exc).__name__}: {exc}")
        log("audio-test", "  -> is the Vosk TTS server running on :22232?")
        traceback.print_exc()
        return

    log("audio-test", f"Vosk returned: samples={len(audio)}, sr={sr}, "
                      f"dtype={getattr(audio, 'dtype', '?')}")
    if len(audio) == 0:
        log("audio-test", "FAIL: Vosk returned EMPTY audio — server down or bad response.")
        return

    log("audio-test", "creating AudioProcessor...")
    try:
        ap = AudioProcessor()
    except Exception as exc:
        log("audio-test", f"FAIL: AudioProcessor init raised {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return

    log("audio-test", ">>> PLAYING NOW — you should HEAR it <<<")
    try:
        ap.play_sound(audio, sr, blocking=True)
    except Exception as exc:
        log("audio-test", f"FAIL: playback raised {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return

    log("audio-test", "playback call returned with no error.")
    log("audio-test", "If you heard NOTHING: device/volume issue (check the output device).")
    log("audio-test", "If you heard it: the audio chain works — the bug is elsewhere.")


if __name__ == "__main__":
    main()
