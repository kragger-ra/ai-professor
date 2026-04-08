"""Voice Input Queue Automatic Speech Recognition Processor

Parallel processing of voice input data from the audio feed queue grouped by user.

TODO
- Stopping and recognizing when too long talking
- Queue limiting
- Max user processing limiting
- Clearing user after user inactivity
- EASY DISABLING OF ALL VOICE INPUT QUEUE

FAR TODO:
- Implementing voice activity detection
    - Wakewords experiments
        - + Priority for wakewords + on events to trigger
"""

import json
import os
import queue
import threading
import time
from collections import defaultdict
from datetime import datetime
from typing import Dict, Union

import numpy as np
from pydub import AudioSegment

from data_collectors.stt.stt_fasterwhisper import FasterWhisperSTT
from data_collectors.stt.stt_utils import SPEECH_THRESHOLD, audio_format_bytes
from data_flow.ctx_handler import CtxHandler
from data_schema.chat_structures import EventBase
from data_schema.ctx_structures import AudioFeedEntry, CtxSwarmType
from utils.time_helper import eztime

MAX_PARALLEL_USERS: int = 3
RECOGNIZE_AFTER_SILENCE_TIME: float = 1
MAX_USER_VOICE_TIME: float = 10


class AudioProcessingEntry(AudioFeedEntry, total=False):
    """Inner audio feed entry for voice processor"""

    audio: AudioSegment
    last_activity: float  # last voice detected
    last_silence_detected: float  # last silence detected
    last_any_activity: float  # last sound packed got, voice/silence
    last_recognized: float
    listening: bool


class VoiceInputProcessor:
    def __init__(self, ctx_swarm: CtxSwarmType, device: str = "cuda"):
        self.records = defaultdict(AudioSegment)
        self.ctx_swarm = ctx_swarm
        self.ctx_handler = CtxHandler(ctx_swarm)
        self.active_users = set()
        self.last_data_entries: Dict[str, AudioProcessingEntry] = dict()
        self.last_activity = dict()
        self.need_to_process = set()
        self.lock = threading.Lock()
        self.queue = queue.Queue()

        # self.recognizer = RealtimeSpeechToText(device)
        self.recognizer = FasterWhisperSTT(device)

        self.external_queue_thread = threading.Thread(
            target=self._external_queue_handler, daemon=True
        )
        self.external_queue_thread.start()
        self.processing_thread = threading.Thread(
            target=self._process_queue, daemon=True
        )
        self.processing_thread.start()

    def stream_audio(self, user: str, audio: Union[AudioSegment, AudioProcessingEntry]):
        """Добавляет аудиоданные в буфер и обновляет время активности"""
        with self.lock:
            if isinstance(audio, AudioSegment):
                audio = AudioProcessingEntry(
                    env="voice",
                    user=user,
                    audio=audio,
                )
            audio_chunk = audio["audio"]
            if self._speech_in_audio(audio_chunk):
                # print("есть слова!")
                self.need_to_process.add(user)
                self.last_activity[user] = time.time()
            if user in self.last_data_entries:
                for k, v in audio.items():
                    self.last_data_entries[user][k] = v
            else:
                self.last_data_entries[user] = audio
            self.records[user] = (
                self.records.get(user, AudioSegment.empty()) + audio_chunk
            )

        self._start_listening(user)

    @staticmethod
    def _speech_in_audio(audio_chunk: AudioSegment):
        samples = np.array(audio_chunk.get_array_of_samples())
        # print("[STT DEBUG] SPEECH ACTIVITY IN AUDIO", np.max(samples))
        return np.max(samples) > SPEECH_THRESHOLD

    def _start_listening(self, user: str):
        """Запускает постоянный поток проверки тишины для канала"""
        if user in self.active_users:
            return

        if len(self.active_users) >= MAX_PARALLEL_USERS:
            # remove oldest active user if his last speech time was > 5s ago
            should_cleanup = False
            # Step 1. Sort by first VOICED activity
            sorted_users = sorted(
                self.active_users, key=lambda x: self.last_activity.get(x, 100)
            )
            # Step 2. Remove last user if his last VOICED activity was > 5s ago
            last_user = sorted_users[0]
            if time.time() - self.last_activity.get(last_user, 100) > 5:
                should_cleanup = True
                print(
                    "[STT DEBUG] Replaced user "
                    + last_user
                    + " with "
                    + user
                    + " due to last inactivity"
                )
                self.active_users.remove(last_user)
            if not should_cleanup:
                return

        self.active_users.add(user)
        threading.Thread(
            target=self._monitor_silence, args=(user,), daemon=True
        ).start()

    def _monitor_silence(self, user: str):
        """Постоянно проверяет, была ли тишина более 3 секунд"""
        # TODO add VAD
        # TODO FAR add SMART phraze end detection
        started_listening_time = time.time()
        while user in self.active_users:
            # print("check for silence")
            time.sleep(0.5)
            with self.lock:
                if user not in self.need_to_process:
                    continue
                cur_time = time.time()
                is_speaking = (
                    cur_time - self.last_activity.get(user, 0)
                    <= RECOGNIZE_AFTER_SILENCE_TIME
                )
                too_long_speaking = (
                    cur_time - started_listening_time > MAX_USER_VOICE_TIME
                )

                if is_speaking and not too_long_speaking:
                    continue
                else:
                    self.queue.put(user)
                    try:
                        self.need_to_process.remove(user)
                        if user in self.active_users:
                            self.active_users.remove(user)
                    except KeyError:
                        pass

                    break

    def _external_queue_handler(self):
        """Обрабатывает файлы из очереди"""
        while True:
            audio_entry = self.ctx_handler.ctx_swarm["audio_feed_queue"].get()
            user = audio_entry.get("user", "MainframeOperator")
            env = audio_entry.get("env", "voice")
            sr = audio_entry.get("sr", 48000)
            channels = audio_entry.get("channels", 1)
            sample_width_bits = audio_entry.get("sample_width_bits", 16)
            # print("[STT] RECEIVED AUDIO FROM " + user + " env " + env + f" {str(sr)}khz;ch" + str(channels) + ";b" + str(sample_width_bits))
            # print("AUDIO DEBUG " + str(audio_entry["audio"]))
            audio_chunk = audio_format_bytes(
                audio_entry["audio"],
                sr=sr,
                channels=channels,
                sample_width_bits=sample_width_bits,
            )
            entry = AudioProcessingEntry(
                env=env,
                user=user,
                audio=audio_chunk,
            )
            # print("AUDIO DEBUG2 ", audio_chunk.channels, audio_chunk.frame_rate, audio_chunk.sample_width, str(audio_chunk.get_array_of_samples()))
            self.stream_audio(user, entry)

    def _process_queue(self):
        """Обрабатывает файлы из очереди"""
        while True:  # while self.running / ctx_swarm["env"]["actived"]
            user = self.queue.get()
            with self.lock:
                wav = self.records.get(user)
                self.records[user] = AudioSegment.empty()
            text = self.recognizer.transcribe_audio(wav)
            with self.lock:
                print("[STT] RECOGNIZED FROM " + user + " TEXT=" + str(text))
                if text:
                    text = text.strip()
                    if text and text.replace("silence", "").replace("*", "").replace(
                        " ", ""
                    ):
                        self._send_to_ctx_chat(text, user)

    _LIVE_TRANSCRIPT_LOG = os.path.join("data", "lecture_notes", "_live_stream.jsonl")

    def _send_to_ctx_chat(self, text, user):
        # user = self.ctx_handler.ctx_swarm["game"].get("last_talking_player", "Developer")
        last_data = self.last_data_entries.get(user)
        if last_data:  # should be present since we're always adding it
            if not user:
                user = "Developer"
            event = EventBase(
                processing_timestamp=time.time_ns(),
                date=eztime(),
                env=last_data["env"],
                user=user,
                type="chat",  # should be 'voice' in future
                msg=text,
                # FAR TODO will be fun add like LOUDNESS, processing_time, etc.
            )
            self.ctx_handler.add_message(event)

            # Write to live transcript log for LectureManager
            if text and len(text) > 3:
                try:
                    os.makedirs(os.path.dirname(self._LIVE_TRANSCRIPT_LOG), exist_ok=True)
                    with open(self._LIVE_TRANSCRIPT_LOG, "a", encoding="utf-8") as f:
                        f.write(json.dumps({
                            "time": datetime.now().isoformat(),
                            "speaker": user,
                            "text": text,
                        }, ensure_ascii=False) + "\n")
                except Exception:
                    pass


def run_voice_processor(ctx_swarm):
    processor = VoiceInputProcessor(
        ctx_swarm, device=os.getenv("STT_COMPUTE_DEVICE", "cpu")
    )
    processor.external_queue_thread.join()
    processor.processing_thread.join()
