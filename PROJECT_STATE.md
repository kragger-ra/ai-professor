# AI Professor — состояние проекта (чекпоинт 2026-04-02 19:40)

## Что работает

Полный голосовой пайплайн: микрофон → STT → RAG → LLM → TTS → аудио через VoiceMeeter.

| Компонент | Технология | Детали |
|---|---|---|
| **STT** | faster-whisper `large-v3` | CUDA float16, ~1s на фразу, отличный русский |
| **LLM** | `mistral/mistral-large-latest` | Mistral API, стриминг с 5s таймаутом |
| **TTS** | Piper TTS `denis-medium` | CPU ONNX, ~0.3s, crossfade+silence compression |
| **RAG** | FAISS + Mistral embeddings | Пропуск для тривиальных фраз ("привет","да","нет") |
| **UI** | Gradio | порт 22228 |
| **Аудио** | VoiceMeeter Banana | TTS → VoiceMeeter Input → A1 (Sound Blaster) |

## Архитектура пайплайна

```
Микрофон (fifine) → sounddevice
    → VAD (energy, 0.5s silence threshold)
    → faster-whisper large-v3 (CUDA)
    → ctx_chat (shared state)
    → CoreAgent.step():
        → wait_for_trigger (ignores self=True events)
        → construct_prompt_messages (personality + RAG + chat history)
        → LLM stream with timeout (5s no-token = end)
        → full response → _flush_sentence → tts_queue
        → save response to ctx_chat (self=True, prevents self-trigger loop)
    → simple_tts_handler:
        → polls tts_queue
        → piper_tts_emo() or fish_tts_emo() (по TTS_BACKEND env)
        → AudioProcessor.play_sound() → VoiceMeeter → наушники
```

## Ключевые файлы (что менялось)

| Файл | Что делает |
|---|---|
| `src/agent/core_agent.py` | Стрим LLM с таймаутом, запись ответов в ctx_chat с self=True |
| `src/agent/prompt_generation/prompt_constructor.py` | PROFESSOR_GOAL + VOICE_RULES, RAG skip для тривиальных фраз |
| `src/agent/tools/base_tools.py` | Парсер эмоций: поддержка (emotion) и *emotion* форматов |
| `resources/Prompts/personalities_professor.yml` | Когнитивно-осознанная персона: режимы А/Б, запреты |
| `src/tts/piper/piper_tts.py` | Piper TTS: SynthesisConfig, crossfade, silence compression |
| `src/tts/simple_tts_handler.py` | Переключение TTS бэкенда по TTS_BACKEND env |
| `src/tts/fish/fish_gr.py` | FishTTS: chunk_length=100, truncate 1000 |
| `src/data_collectors/stt/stt_fasterwhisper.py` | large-v3, beam=1/5 по устройству |
| `src/data_collectors/stt/mic_stt_handler.py` | VAD 5 блоков, файловое логирование |

## Конфигурация (.env, ключевое)

```env
FASTER_WHISPER_MODEL_NAME="large-v3"
STT_COMPUTE_TYPE="float16"
STT_COMPUTE_DEVICE="cuda"
CORE_LLM_MODEL_NAME="mistral/mistral-large-latest"
TTS_BACKEND="piper"
PIPER_MODEL_NAME="ru_RU-denis-medium"
SOUND_DEVICE_IN="fifine"
SOUND_DEVICE_OUT="Voicemeeter Input (VB-Audio Voicemeeter VAIO)"
```

## Piper TTS настройки (в коде)

```
SynthesisConfig:
  length_scale    = 1.3    # скорость (>1 = медленнее)
  noise_scale     = 0.3    # вариативность тона
  noise_w_scale   = 0.1    # вариативность длительности фонем

Постпроцессинг:
  silence threshold = 0.02, max_silence = 30ms (сжатие пауз внутри предложений)
  sentence_pause    = 0.45s (пауза между предложениями)
  crossfade         = 80ms (fade-in/fade-out на стыках)
```

## Известные проблемы / TODO

1. **Повторные приветствия** — модель иногда начинает с "Добрый день" на каждый ответ. Запрет добавлен в промпт, но Mistral не всегда его соблюдает.
2. **Повторные ответы на один вопрос** — фикс self=True в ctx_chat добавлен, нужно проверить работает ли корректно.
3. **Качество голоса** — Piper Denis неплохой, но нет клонирования. FishTTS (TTS_BACKEND="fish") доступен как альтернатива с клонированием, но в 20-40x медленнее.
4. **Скорость речи** — length_scale=1.3, проверить не слишком ли медленно.
5. **STT ловит TTS** — микрофон иногда ловит голос профессора из динамиков, создавая паразитные STT-события (empty result, не критично).
6. **Стриминг LLM→TTS отключён** — сейчас ждём полный ответ LLM, потом озвучиваем. С Piper это норм (~0.3s TTS), но с FishTTS streaming по предложениям был бы полезен. Код streaming сохранён но закомментирован.

## Запуск

```bash
docker start fish-speech        # если TTS_BACKEND="fish"
cd N:\exam\AI-Professor
PYTHONPATH=src python src/main.py --offline --no-filter
```

## Коммиты этой сессии

```
162a6c2 feat: downgrade STT to tiny model, fix voice pipeline bugs
661a26f feat: Piper TTS, cognitive-load professor, stream timeout, self-loop fix  ← ТЕКУЩИЙ
```
