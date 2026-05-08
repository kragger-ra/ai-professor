# AI Professor

ИИ-агент-преподаватель для воркшопа PersonaLab Workshop по созданию цифровых персонажей.
Голосовой диалог в реальном времени, RAG по материалам курса, адаптация под студента.

**Платформа:** ИТМО AI Talent Hub / PersonaLab  
**Трек:** Образовательный (ВКР)

## Быстрый старт

```bash
cp .env.example .env
# Заполнить API ключи и настройки аудио
pip install -e .

# Запустить Vosk TTS сервер (отдельный проект, порт 22232)
python src/main.py
```

## Архитектура

3 процесса, связанные через `multiprocessing.Manager`:

```
STT Process (faster-whisper, CUDA)
  → ctx_chat (shared state)
  → interrupt TTS при распознавании речи
  → JSONL лог для конспектирования лекций

CoreAgent (main process)
  → construct_prompt (RAG + student profile + history)
  → stream Mistral (queue+thread, 10s timeout)
  → SentenceBuffer → tts_queue
  ← interrupt при новом сообщении студента

TTS Process (Vosk)
  → queue-level prefetch (синтез следующего пока играет текущее)
  → interrupt support
```

## Ключевые возможности

- **Streaming LLM** — ответ начинает звучать через 2-3с (Mistral Large)
- **Interrupt** — студент может перебить в любой момент
- **Stop commands** — "стоп/подождите" → мгновенная остановка без LLM
- **RAG** — FAISS по 4 лекциям курса, score-based аннотации контекста
- **Student Profiles** — SQLite, обновляются meta-agent (Claude Haiku) в фоне
- **Конспектирование лекций** — STT → JSONL → periodic summarization → RAG
- **Метрики** — SQLite логирование взаимодействий, latency, weekly stats
- **Audio routing** — VoiceMeeter Banana: режим созвона (любое приложение через VB-Cable) и локальный режим

## Структура проекта

```
src/
  main.py                  # точка входа (Gradio UI + multiprocessing)
  agent/
    core_agent.py           # главный агент: step() loop, interrupt, streaming
    streaming_orchestrator.py  # LLM streaming с queue+thread timeout
    meta_agent.py           # фоновый анализ контекста (Claude Haiku)
    rag.py                  # FAISS RAG по материалам курса
    prompt_generation/      # prompt_constructor, format helpers
  lecture/
    integration.py          # LectureManager — фасад конспектирования
    transcript_buffer.py    # буфер STT-сегментов
    summarizer.py           # map-reduce суммаризация через LLM
    wake_word.py            # детекция обращений к профессору
    student_profiles.py     # SQLite профили студентов
  data_collectors/stt/      # STT через faster-whisper + interrupt
  tts/
    simple_tts_handler.py   # queue-level prefetch streaming
    vosk/                   # Vosk TTS client + sentence splitting
  metrics/
    logger.py               # SQLite логирование метрик
resources/
  Prompts/                  # personalities_professor.yml, instructions
  RAG/                      # course_materials/ (4 лекции), lecture_summaries/
  Audio/tts_cache/          # pre-synthesized common phrases
data/
  student_profiles.db       # SQLite профили студентов
  rag_vector_store/         # FAISS index (автосоздаётся)
  metrics.db                # SQLite метрики
  lecture_notes/            # JSONL лог + конспекты лекций
```

## Конфигурация

Основные переменные в `.env`:

| Переменная | Описание |
|---|---|
| `CORE_LLM_MODEL_NAME` | LLM для диалога (`mistral/mistral-large-latest`) |
| `MISTRAL_API_KEY` | API ключ Mistral (LLM + embeddings) |
| `TTS_BACKEND` | TTS бэкенд (`vosk`) |
| `VOSK_TTS_URL` | URL Vosk TTS сервера (`http://localhost:22232`) |
| `VOSK_SPEAKER_ID` | ID голоса Vosk (`4` — male_1) |
| `SOUND_DEVICE_IN` | Микрофон для STT |
| `OPENAI_API_KEY` | Ключ AWstore для Claude (meta-agent) |
| `LECTURE_WEEK` | Номер текущей недели курса |

## Зависимости

- Python 3.10+
- NVIDIA GPU (faster-whisper CUDA)
- Vosk TTS сервер (отдельный проект)
- Mistral API
- Опционально: AWstore API (Claude для meta-agent)
