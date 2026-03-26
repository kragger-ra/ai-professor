"""
Simple test script for real-time STT using audio input device.
Tests audio capture and STT processing with minimal complexity.
"""

import os
import queue
import sys
import time
from threading import Thread

import numpy as np
import sounddevice as sd
from RealtimeSTT import AudioToTextRecorder

if __name__ == "__main__":
    sys.path.append(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )


def list_audio_devices():
    """List all available audio input devices"""
    print("\nAvailable audio input devices:")
    devices = sd.query_devices()
    for i, device in enumerate(devices):
        if device["max_input_channels"] > 0:  # Only show input devices
            print(f"{i}: {device['name']}")
    print()


def audio_callback(indata, frames, time, status):
    """Callback for sounddevice to handle incoming audio data"""
    if status:
        print(f"Status: {status}")

    # Ensure audio data is mono and in correct format
    audio_data = indata.flatten()  # Flatten in case of stereo

    # Convert to PCM format that RealtimeSTT expects
    audio_data = (audio_data * 32767).astype(np.int16)

    # Put audio data in queue for processing
    if audio_queue.qsize() < 5:  # Reduced queue size to prevent overflow
        audio_queue.put(audio_data.tobytes())


if __name__ == "__main__":
    DEBUG = True
else:
    DEBUG = False


def process_audio():
    """Process audio data from queue and feed to STT"""
    # Initialize RealtimeSTT recorder with more aggressive settings
    recorder = AudioToTextRecorder(
        model="base",
        language="ru",
        sample_rate=16000,
        device="cpu",
        print_transcription_time=True,
        # initial_prompt="some prompt",  # https://github.com/KoljaB/RealtimeSTT?tab=readme-ov-file#configuration
        use_microphone=False,
        spinner=DEBUG,  # spinner animation in console, need only for one-module console debug
    )

    buffer = b""  # Accumulate audio data
    CHUNK_SIZE = (
        32000  # Process in ~1 second chunks (16000 samples * 2 bytes per sample)
    )

    def on_transcription(text):
        if text and len(text.strip()) > 0:
            print(f"Transcribed: {text}")

    def transription_loop():
        while True:
            text = recorder.text(on_transcription_finished=on_transcription)

    with recorder:
        Thread(target=transription_loop, daemon=True).start()
        while True:
            try:
                # Get data from queue
                audio_chunk = audio_queue.get(timeout=0.1)
                buffer += audio_chunk

                # Process when we have enough data
                if len(buffer) >= CHUNK_SIZE:
                    recorder.feed_audio(buffer[:CHUNK_SIZE])
                    buffer = buffer[CHUNK_SIZE:]  # Keep remaining data

                    # Check for transcription

            except queue.Empty:
                continue
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error processing audio: {e}")
                time.sleep(0.1)  # Prevent tight loop on errors


if __name__ == "__main__":
    # Initialize queue for audio data
    audio_queue = queue.Queue()

    # Show available devices
    list_audio_devices()

    # Get device selection from user
    device_id = input("Enter the number of the audio device to use: ")
    try:
        device_id = int(device_id)
    except ValueError:
        print("Please enter a valid number")
        sys.exit(1)

    # Start audio processing thread
    process_thread = Thread(target=process_audio, daemon=True)
    process_thread.start()

    # Start recording with smaller blocksize
    try:
        with sd.InputStream(
            device=device_id,
            channels=1,
            callback=audio_callback,
            blocksize=2000,  # Smaller chunks for more frequent processing
            dtype=np.int16,
            samplerate=16000,
        ):
            print(f"\nRecording from device {device_id}. Press Ctrl+C to stop.\n")
            while True:
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nRecording stopped.")
    except Exception as e:
        print(f"\nError: {str(e)}")
