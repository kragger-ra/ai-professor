"""PCM constants"""

import io

import librosa
import numpy as np
from pydub import AudioSegment

# Import our new simple resampling function
from utils.audio_utils import resample_audio_segment

CHUNK = 1024
TARGET_SAMPLE_WIDTH = 1
TARGET_CHANNELS = 1
TARGET_SR = 16000

SPEECH_THRESHOLD = 30
RECORD_INTERVAL = 2


def stt_callback(ctx_chat, channel, text):
    print(f"{channel}: {text}")


def audio_format_discord_wav(input_wav: io.BytesIO) -> AudioSegment:
    audio = AudioSegment.from_file(input_wav, format="wav")
    return (
        audio.set_frame_rate(TARGET_SR)
        .set_channels(TARGET_CHANNELS)
        .set_sample_width(TARGET_SAMPLE_WIDTH)
    )


def pydub_to_np(asg: AudioSegment) -> np.ndarray:
    dtype = getattr(
        np, "int{:d}".format(asg.sample_width * 8)
    )  # Or could create a mapping: {1: np.int8, 2: np.int16, 4: np.int32, 8: np.int64}
    arr = np.ndarray(
        (int(asg.frame_count()), asg.channels), buffer=asg.raw_data, dtype=dtype
    )
    print(
        "\n",
        asg.frame_rate,
        arr.shape,
        arr.dtype,
        arr.size,
        len(asg.raw_data),
        len(asg.get_array_of_samples()),
    )  # @TODO: Comment this line!!!
    return arr  # arr.astype(np.float32) / np.iinfo(np.int16).max  #, asg.frame_rate


def pydub_to_np_my(audio: AudioSegment) -> np.ndarray:
    """
    Converts pydub audio segment into np.float32 of shape [duration_in_seconds*sample_rate, channels],
    where each value is in range [-1.0, 1.0].
    Returns tuple (audio_np_array, sample_rate).
    """
    data = np.array(audio.get_array_of_samples())
    data = data.astype(np.float32) / np.iinfo(np.int16).max
    return data


# def pydub_to_np_stackoverflow(audio: AudioSegment) -> np.ndarray:
# return np.array(
#     audio.get_array_of_samples(), dtype=np.float32
# ).reshape((-1, audio.channels)) / ( 1 << (8 * audio.sample_width - 1))


def np_to_pydub(audio: np.ndarray, sample_width, frame_rate, channels) -> AudioSegment:
    """
    Converts np.float32 audio array into pydub audio segment.
    """
    if channels > 1:
        print("[STT WARNING DEBUG] Channels > 1, bad audio! Will be converted to mono")
    channel_one = audio
    audio_segment = AudioSegment(
        channel_one.tobytes(),
        frame_rate=frame_rate,
        sample_width=channel_one.dtype.itemsize,
        channels=1,
    )
    return audio_segment


def audio_format_bytes(
    input_wav: bytes, sr: int = 48000, channels: int = 1, sample_width_bits: int = 16
) -> AudioSegment:
    """Convert bytes to AudioSegment

    Args:
        input_wav (bytes): input bytes. Got from java array of type short[] of raw audio (mono channel, 48khz). In python short[] equals int16 array.
    """

    # sample width (in bytes) is 1 = 8bit audio, 2 = 16bit, ...
    # frame rate = sample rate
    # channels - mono/stereo
    sample_width = (int)(sample_width_bits // 8)  # 16 bits = 2 bytes
    audio: AudioSegment = AudioSegment.from_raw(
        io.BytesIO(input_wav),
        sample_width=sample_width,
        frame_rate=sr,
        channels=channels,
    )

    # TODO resample to TARGET values *TODO NEED TEST*
    # TODO deal with channels *TODO NEED TEST*

    # Resample if needed using our simplified function
    if sr != TARGET_SR:
        audio = resample_audio_segment(audio, TARGET_SR)

    # i think we no need to just change the metadata, we need to convert the entire AUDIO
    # and only then change it
    # Handle channels if needed
    # if audio.channels != TARGET_CHANNELS:
    #     audio = audio.set_channels(TARGET_CHANNELS)

    # ADDING NOISE! TODO INVESTIGATE!
    # # Handle sample width if needed
    # if audio.sample_width != TARGET_SAMPLE_WIDTH:
    #     audio = audio.set_sample_width(TARGET_SAMPLE_WIDTH)

    return audio


if __name__ == "__main__":
    audio: AudioSegment = AudioSegment.from_wav(
        r"D:\Pets\NetTyan\MC\NetTyanNew\run\voicechat_recordings\2025-03-08-12-44-35-678\Chochok_clip.wav"
    )
    print(
        "!!! 1",
        audio.channels,
        audio.frame_rate,
        audio.sample_width,
        str(audio.get_array_of_samples()),
    )
    audiof = audio_format_bytes(
        audio.raw_data,
        sr=audio.frame_rate,
        channels=audio.channels,
        sample_width_bits=audio.sample_width * 8,
    )
    print(
        "!!! 2 ", audiof.channels, audiof.frame_rate, audiof.sample_width
    )  # , str(audiof.get_array_of_samples()))
    audiof.export(
        "D:\\Pets\\NetTyan\\MC\\NetTyanNew\\run\\voicechat_recordings\\2025-03-08-12-44-35-678\\Chochok_clip_fixed.wav",
        format="wav",
    )
