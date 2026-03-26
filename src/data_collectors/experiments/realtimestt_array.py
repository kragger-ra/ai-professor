import threading
import time

from RealtimeSTT import AudioToTextRecorder

file_path = r"C:\Users\Onix\Downloads\output (2).wav"
pcm_file_path = r"C:\Users\Onix\Downloads\output (2)_signed16bitpcm16khz.wav"


def recognize_raw_pcm():
    recorder = AudioToTextRecorder(use_microphone=False, buffer_size=100)

    # time.sleep(10)
    def feed_audio():
        with open(pcm_file_path, "rb") as f:
            audio_chunk = f.read()
            # recorder.start()
        print("Audio feeding...")
        recorder.feed_audio(audio_chunk)
        # recorder._transcription_worker.queue.put(audio_chunk)
        print("Audio fed.")
        print("Transcription: ", recorder.text(lambda a: print("FSDGDSG", a)))

    # recorder.start()
    print("Checkpoint 0")
    time.sleep(10)
    print("Listen")
    recorder.listen()
    time.sleep(1)
    print("Before feeding")
    threading.Thread(target=feed_audio).start()
    # recorder.stop()
    print("Checkpoint 1")
    time.sleep(20)
    # recorder.stop()
    time.sleep(1)
    print("Checkpoint 2")
    recorder.shutdown()


if __name__ == "__main__":
    recognize_raw_pcm()
