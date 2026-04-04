# Speech Pipeline

## Overview

Voice recognition for NetTyan. Mic audio goes through STT, arrives as events in the main ChatAgent pipeline — same as Discord/Twitch messages, just with `env=voice` and higher priority.

No separate speech agent. No separate LLM history. Voice is just another input source.

## Architecture

```text
[Mic] (soundcard, 16kHz mono)
  |  float32 chunks (100ms)
  v
[Simple VAD] (numpy amplitude check)
  |  voice detected → accumulate
  |  silence > 1s → send to STT
  v
[Parakeet STT] ── HTTP POST ──> [Docker: parakeet-onnx :22233]
  |                                 (NVIDIA Parakeet TDT v3 0.6B, ONNX, CPU)
  |                                 OpenAI-compatible /v1/audio/transcriptions
  |  recognized text
  v
[speech_processor.py] → EventBase(env="voice") → ctx_chat → ChatAgent
  |
  v
[ChatAgent] (same LLM, same tools, same history)
  |  response text
  v
[tts_queue] → [Fish-TTS Docker] → [Virtual Cable]
```

Voice events from the local mic can get higher priority than text chat, configurable via env.

## STT Backend Selection

Configured via `STT_BACKEND` in `.env`:

| Value | Description |
| --- | --- |
| `parakeet` (default) | HTTP call to Parakeet ONNX Docker container. Fast, CPU-only, no GPU needed |
| `fasterwhisper_local` | Local faster-whisper model, loaded in-process. Needs `faster_whisper` pip package |

## Parakeet Docker Service

Lives in `docker/stt/parakeet/`. OpenAI-compatible endpoint (`/v1/audio/transcriptions`).

- Model: `nvidia/parakeet-tdt-0.6b-v3` (ONNX, INT8 quantized)
- CPU-only, ~2GB RAM, 18-30x faster than real-time
- Outputs punctuation and capitalization natively
- 25 languages including Russian, English, Ukrainian

```bash
docker compose -f docker-compose.stt.yml up
```

## Code-Switching (RU + EN)

Neither Parakeet nor Whisper handle mixed-language speech well (e.g. Russian sentence with English game commands). This is an unsolved problem in ASR.

Practical workaround: STT outputs Russian, LLM interprets context. "напиши слэш спавн" → LLM understands intent → `/spawn`. Game-specific terms can be post-processed with a dictionary if needed.

## Future: Enrichment Pipeline

After basic STT works, optional enrichment layer (separate Docker service):

1. **Speaker diarization** (pyannote) — who said what. Runs independently on audio, results merged with STT output by timestamps. Does NOT need to run before transcription.
2. **Emotion detection** (emotion2vec / wav2vec2) — per-segment emotion tags. Separate model, separate inference.
3. **Audio tagging** (PANNs / YAMNet) — music detection, ambient sounds.

These run asynchronously. If diarization finds multiple speakers, dialogue history gets updated retroactively.

## Key Files

| File | Purpose |
| --- | --- |
| `src/data_collectors/stt/speech_processor.py` | Voice input queue processor, VAD, silence detection, sends events to ctx_chat |
| `src/data_collectors/stt/stt_fasterwhisper.py` | Local faster-whisper STT backend |
| `src/data_collectors/stt/stt_parakeet.py` | HTTP client for Parakeet Docker endpoint (TODO) |
| `src/data_collectors/stt/stt_utils.py` | Audio format conversions, PCM constants |
| `src/data_collectors/stt/mic_capture.py` | Soundcard mic capture, callback-based |
| `docker/stt/parakeet/` | Dockerfile + server for Parakeet ONNX |

## Env Variables

```env
# STT backend: "parakeet" (default) or "fasterwhisper_local"
STT_BACKEND="parakeet"

# Parakeet Docker endpoint
PARAKEET_API_URL="http://127.0.0.1:22233/v1/audio/transcriptions"
PARAKEET_LANGUAGE="ru"

# Local faster-whisper (if STT_BACKEND=fasterwhisper_local)
FASTER_WHISPER_MODEL_NAME="tiny"
STT_COMPUTE_DEVICE="cpu"

# Mic capture
SPEECH_MIC_DEVICE=""

# Voice input processor
SPEECH_VAD_THRESHOLD=0.05
SPEECH_VOICE_USER="Developer"
```
