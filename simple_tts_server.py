import os
import re
import tempfile
import time
import traceback
from typing import TypedDict

import gradio as gr

# Try to import vosk_tts (used for synthesis). On failure, we'll surface errors at runtime.
try:
    from vosk_tts import Model, Synth

    VOSK_AVAILABLE = True
except Exception:  # pragma: no cover - allow missing package to be handled gracefully
    Model = None
    Synth = None
    VOSK_AVAILABLE = False

# Try to import edge_tts as fallback
try:
    import asyncio

    import edge_tts

    EDGE_TTS_AVAILABLE = True
except Exception:
    EDGE_TTS_AVAILABLE = False

# Try to import scipy for resampling
try:
    import numpy as np
    from scipy.io import wavfile
    from scipy.signal import resample

    SCIPY_AVAILABLE = True
except Exception:
    print(">> INSTALL SCIPY!")
    SCIPY_AVAILABLE = False


class FishTTSGradioKWArgs(TypedDict):
    """Typed dict describing the Gradio inputs accepted by the API.

    All fields are included so the HTTP/Gradio API accepts them, but only
    `text` is used for synthesis in this emulator.
    """

    text: str
    normalize: bool
    reference_id: str
    reference_audio: str
    reference_text: str
    max_new_tokens: int
    chunk_length: int
    top_p: float
    repetition_penalty: float
    temperature: float
    seed: int
    use_memory_cache: str
    api_name: str


# Default model name (can be changed later if needed)
DEFAULT_MODEL_NAME = os.environ.get("VOSK_MODEL_NAME", "vosk-model-tts-ru-0.7-multi")
# latest for 2025 vosk-model-tts-ru-0.9-multi, but TOO SLOW for startup (120s), 330M
# Stable old vosk-model-tts-ru-0.7-multi is 150M and starts in ~16s

# Initialize model and synth at import time for faster responses
_model = None
_synth = None
_model_init_error = None


def clean_russian_text(text: str) -> str:
    """Clean text to keep only Russian letters, numbers, spaces, and basic punctuation (!?.,)"""
    # Keep Russian letters (А-Яа-яЁё), numbers, spaces, and basic punctuation
    cleaned = re.sub(r"[^А-Яа-яЁё\s!?.,]", "", text)
    # Normalize multiple spaces to single space
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def resample_audio(input_path: str, output_path: str, target_rate: int = 48000) -> bool:
    """Resample audio from 22050 Hz to target sample rate (default 48000 Hz).

    Args:
        input_path: Path to input WAV file
        output_path: Path to output resampled WAV file
        target_rate: Target sample rate in Hz

    Returns:
        True if resampling succeeded, False otherwise
    """
    if not SCIPY_AVAILABLE:
        print("[RESAMPLE] scipy not available, skipping resample")
        return False

    try:
        # Read the input audio file
        sample_rate, audio_data = wavfile.read(input_path)
        print(f"[RESAMPLE] Original sample rate: {sample_rate} Hz")

        # Skip resampling if already at target rate
        if sample_rate == target_rate:
            print(f"[RESAMPLE] Already at {target_rate} Hz, no resampling needed")
            return False

        # Calculate number of samples for target rate
        duration = len(audio_data) / sample_rate
        target_length = int(duration * target_rate)

        # Handle multi-channel audio
        if audio_data.ndim == 1:
            # Mono audio
            resampled_audio = resample(audio_data, target_length)
        else:
            # Multi-channel audio - resample each channel
            resampled_audio = np.zeros(
                (target_length, audio_data.shape[1]), dtype=audio_data.dtype
            )
            for channel in range(audio_data.shape[1]):
                resampled_audio[:, channel] = resample(
                    audio_data[:, channel], target_length
                )

        # Convert to int16 if needed
        if resampled_audio.dtype != np.int16:
            resampled_audio = np.int16(resampled_audio)

        # Write resampled audio
        wavfile.write(output_path, target_rate, resampled_audio)
        print(f"[RESAMPLE] Resampled to {target_rate} Hz")
        return True

    except Exception as e:
        print(f"[RESAMPLE] Failed: {e}")
        traceback.print_exc()
        return False


def _init_model():
    global _model, _synth, _model_init_error

    # Try vosk_tts first if available
    if VOSK_AVAILABLE and Model is not None and Synth is not None:
        try:
            print(
                f"[STARTUP] Loading vosk_tts model '{DEFAULT_MODEL_NAME}'... (typically ~100 secs)"
            )
            start_time = time.time()
            _model = Model(model_name=DEFAULT_MODEL_NAME)
            model_load_time = time.time() - start_time
            print(f"[STARTUP] Model loaded in {model_load_time:.2f}s")

            print("[STARTUP] Initializing synthesizer...")
            start_time = time.time()
            _synth = Synth(_model)
            synth_load_time = time.time() - start_time
            print(f"[STARTUP] Synthesizer initialized in {synth_load_time:.2f}s")
            print(
                f"[STARTUP] Total startup time: {model_load_time + synth_load_time:.2f}s"
            )
            return
        except Exception as e:
            print(f"[STARTUP] Failed to initialize vosk_tts: {e}")
            _model_init_error = None  # Clear error since we'll try edge-tts

    # Fall back to edge-tts
    if EDGE_TTS_AVAILABLE:
        print("[STARTUP] Using edge-tts as TTS engine")
        _model_init_error = None
    else:
        _model_init_error = "Neither vosk_tts nor edge-tts is available"


_init_model()


def predict(
    text: str,
    normalize: bool,
    reference_id: str,
    reference_audio: str | None,
    reference_text: str,
    max_new_tokens: int,
    chunk_length: int,
    top_p: float,
    repetition_penalty: float,
    temperature: float,
    seed: int,
    use_memory_cache: str,
) -> tuple[str | None, str]:
    """Synthesize `text` using vosk_tts or edge-tts and return (audio_filepath, error_html).

    Only `text` is used for synthesis; other inputs are accepted but ignored.
    """

    if _model_init_error:
        return None, f"<div style='color:red'>{_model_init_error}</div>"

    # Use edge-tts if vosk_tts is not available
    use_edge_tts = _synth is None and EDGE_TTS_AVAILABLE

    # Clean text to Russian only
    cleaned_text = clean_russian_text(text)
    if not cleaned_text:
        return None, "<div style='color:red'>No valid Russian text after cleaning</div>"

    # Validate reference_audio to prevent directory path errors
    if reference_audio and os.path.isdir(reference_audio):
        reference_audio = None

    try:
        # Determine speaker ID
        spk_id = 1
        if reference_id:
            try:
                spk_id = int(reference_id)
                if spk_id < 0 or spk_id > 100:
                    spk_id = 1
            except:
                pass

        # Generate audio in-memory using a temporary file in memory
        print(f"[GENERATE] Starting synthesis for text: '{cleaned_text[:50]}...'")
        start_time = time.time()

        # Create temporary file for synthesis
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
            tmp_path = tmp_file.name

        # Create temporary file for resampled output
        with tempfile.NamedTemporaryFile(
            suffix="_resampled.wav", delete=False
        ) as tmp_resampled:
            tmp_resampled_path = tmp_resampled.name

        try:
            if use_edge_tts:
                # Use edge-tts
                voice = "ru-RU-DmitryNeural"  # Default Russian voice
                communicate = edge_tts.Communicate(cleaned_text, voice)
                asyncio.run(communicate.save(tmp_path))
            else:
                # Use vosk_tts
                _synth.synth(cleaned_text, tmp_path, speaker_id=spk_id)

            generation_time = time.time() - start_time
            print(f"[GENERATE] Synthesis completed in {generation_time:.2f}s")

            # Validate output file was created and is readable
            if not os.path.exists(tmp_path):
                return (
                    None,
                    "<div style='color:red'>Synthesis completed but output file was not created</div>",
                )
            if not os.path.isfile(tmp_path):
                return (
                    None,
                    f"<div style='color:red'>Output path is not a file: {tmp_path}</div>",
                )
            if os.path.getsize(tmp_path) == 0:
                return (
                    None,
                    "<div style='color:red'>Generated audio file is empty</div>",
                )

            # Resample from 22050 Hz to 48000 Hz
            resample_start = time.time()
            resampled = resample_audio(tmp_path, tmp_resampled_path, target_rate=48000)
            resample_time = time.time() - resample_start

            if resampled:
                print(f"[GENERATE] Resampling completed in {resample_time:.2f}s")
                # Clean up original file and return resampled
                try:
                    os.unlink(tmp_path)
                except:
                    pass
                return tmp_resampled_path, ""
            else:
                # Resampling failed or skipped, return original
                print(f"[GENERATE] Using original audio (resampling skipped)")
                try:
                    os.unlink(tmp_resampled_path)
                except:
                    pass
                return tmp_path, ""

        except Exception as e:
            # Clean up temp files on error
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except:
                    pass
            if os.path.exists(tmp_resampled_path):
                try:
                    os.unlink(tmp_resampled_path)
                except:
                    pass
            raise
    except Exception as e:
        traceback.print_exc()
        return None, f"<div style='color:red'>Synthesis failed: {e}</div>"


def build_and_launch(server_name: str = "127.0.0.1", server_port: int = 22231):
    """Build the Gradio UI (only to expose the API endpoints) and launch the server.

    The UI contains components that match `FishTTSGradioKWArgs` but the synth uses
    only the `text` input.
    """

    with gr.Blocks(title="FishTTS Gradio Emulator") as demo:
        with gr.Row():
            text_in = gr.Textbox(
                label="Realtime Transform Text", lines=4, value="Hello!!"
            )

        with gr.Row():
            normalize = gr.Checkbox(label="Text Normalization", value=False)
            reference_id = gr.Textbox(label="Reference ID", value="")

        with gr.Row():
            reference_audio = gr.Audio(label="Reference Audio", type="filepath")
            reference_text = gr.Textbox(label="Reference Text", value="")

        with gr.Row():
            max_new_tokens = gr.Slider(0, 2048, value=0, step=1, label="Max New Tokens")
            chunk_length = gr.Slider(0, 2000, value=200, step=1, label="Chunk Length")

        with gr.Row():
            top_p = gr.Slider(0.0, 1.0, value=0.7, step=0.01, label="Top P")
            repetition_penalty = gr.Slider(
                0.1, 5.0, value=1.2, step=0.1, label="Repetition Penalty"
            )

        with gr.Row():
            temperature = gr.Slider(0.0, 2.0, value=0.7, step=0.01, label="Temperature")
            seed = gr.Number(value=0, label="Seed")

        use_memory_cache = gr.Radio(
            choices=["on", "off"], value="on", label="Use Memory Cache"
        )
        audio_out = gr.Audio(label="Generated Audio")
        error_html = gr.HTML()

        generate_btn = gr.Button("Generate")
        generate_btn.click(
            predict,
            inputs=[
                text_in,
                normalize,
                reference_id,
                reference_audio,
                reference_text,
                max_new_tokens,
                chunk_length,
                top_p,
                repetition_penalty,
                temperature,
                seed,
                use_memory_cache,
            ],
            outputs=[audio_out, error_html],
            api_name="partial",
        )

    demo.launch(server_name=server_name, server_port=server_port, share=False)


if __name__ == "__main__":
    # Default local launch for manual testing
    build_and_launch()
