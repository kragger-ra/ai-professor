try:
    from RealtimeSTT import AudioToTextRecorder
except ImportError:
    print(
        "RealtimeSTT is not installed. Please install it via `pip install RealtimeSTT`"
    )
import os
import sys
import time

if __name__ == "__main__":
    sys.path.append(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )

from data_flow.ctx_handler import CtxHandler
from data_schema.chat_structures import EventBase
from data_schema.ctx_structures import CtxSwarmType
from data_schema.structure_templates import create_ctx_swarm
from utils.time_helper import eztime


def get_audio_device(device_name="") -> int:
    """List all available audio input devices"""
    if not device_name:
        print("\nAvailable audio input devices:")
    import sounddevice as sd

    devices = sd.query_devices()
    for i, device in enumerate(devices):
        if device["max_input_channels"] > 0:  # Only show input devices
            if not device_name:
                print(f"{i}: {device['name']}")
            elif device_name in device["name"]:
                print(f"[STT] Selected audio device {i}: {device['name']}")
                return i

    if not device_name:
        print()
    return sd.default.device[0]


def simple_stt_handler(
    ctx_swarm: CtxSwarmType,
    audio_device_index: int = 7,
    audio_device_name: str = "CABLE-C Output",
):
    print("[STT] Starting...")
    ctx_handler = CtxHandler(ctx_swarm)
    if audio_device_index is None:
        audio_device_index = get_audio_device(audio_device_name)

    def process_text(text):
        if text:
            print(text)
            user = ctx_swarm["game"].get("last_talking_player", "Developer")
            if not user:
                user = "Developer"
            event = EventBase(
                processing_timestamp=time.time_ns(),
                date=eztime(),
                env="voice",
                user=user,
                type="chat",
                msg=text,
            )
            ctx_handler.add_message(event)

    with AudioToTextRecorder(
        language="ru",
        model="base",
        realtime_model_type="base",
        input_device_index=audio_device_index,
        device="cuda",
        spinner=False,  # you can enable it only for debug
    ) as recorder:
        while ctx_swarm["env"]["actived"]:
            text = recorder.text()
            process_text(text)

    print("[STT] exiting")


if __name__ == "__main__":
    from threading import Thread

    get_audio_device()
    # exit()
    ctx_swarm = create_ctx_swarm()

    def debug_chat_print():
        try:
            while True:
                time.sleep(5)
                print("CTX SWARM CHAT:", ctx_swarm["ctx_chat"])
        except KeyboardInterrupt:
            print("Debug chat print interrupted by user.")
            raise KeyboardInterrupt

    Thread(target=debug_chat_print).start()
    simple_stt_handler(ctx_swarm)  # , audio_device_index=2)
