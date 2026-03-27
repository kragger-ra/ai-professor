import librosa
import numpy as np
from pydub import AudioSegment
from scipy.signal import butter, sosfilt


def change_pitch_speed(audio, sr, speed_factor):
    """Speed up/slow down audio while preserving sample rate using time-stretching."""
    stretched = librosa.effects.time_stretch(audio, rate=speed_factor)
    return stretched


def post_process_tts(audio: np.ndarray, sr: int, noise_gate_db: float = -40.0, lowpass_hz: int = 8000) -> np.ndarray:
    """Post-process TTS output: low-pass filter + noise gate + peak normalization."""
    # Low-pass filter to remove electronic/metallic artifacts
    sos = butter(5, lowpass_hz, btype='low', fs=sr, output='sos')
    audio = sosfilt(sos, audio)

    # Noise gate: silence anything below threshold
    threshold = 10 ** (noise_gate_db / 20.0)
    audio = np.where(np.abs(audio) < threshold, 0.0, audio)

    # Peak normalization to -1.0 dB headroom
    peak = np.max(np.abs(audio))
    if peak > 0:
        target = 10 ** (-1.0 / 20.0)  # -1 dB
        audio = audio * (target / peak)

    return audio


def resample_audio_segment(audio_segment: AudioSegment, target_sr: int) -> AudioSegment:
    """
    Simple function to resample pydub AudioSegment to a target sample rate
    without data corruption.

    Args:
        audio_segment (AudioSegment): Input pydub AudioSegment
        target_sr (int): Target sample rate in Hz

    Returns:
        AudioSegment: Resampled audio segment
    """
    # If target rate is already correct, return the original
    if audio_segment.frame_rate == target_sr:
        return audio_segment

    # Get audio data as int16 numpy array
    samples = np.array(audio_segment.get_array_of_samples())

    # Check if stereo and reshape accordingly
    channels = audio_segment.channels
    if channels > 1:
        samples = samples.reshape(-1, channels)

    # Convert to float32 for librosa (normalized between -1 and 1)
    samples = samples.astype(np.float32) / 32768.0

    # Resample using librosa
    if channels > 1:
        # Process each channel separately
        resampled = np.zeros(
            (int(len(samples) * target_sr / audio_segment.frame_rate), channels),
            dtype=np.float32,
        )
        for ch in range(channels):
            resampled[:, ch] = librosa.resample(
                samples[:, ch], orig_sr=audio_segment.frame_rate, target_sr=target_sr
            )
    else:
        # Process mono
        resampled = librosa.resample(
            samples, orig_sr=audio_segment.frame_rate, target_sr=target_sr
        )

    # Convert back to int16
    resampled = (resampled * 32768.0).astype(np.int16)

    # Create new AudioSegment
    return AudioSegment(
        data=resampled.tobytes(),
        sample_width=2,  # 16-bit audio = 2 bytes
        frame_rate=target_sr,
        channels=channels,
    )
