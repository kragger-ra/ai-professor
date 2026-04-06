# AI Professor — ИИ-агент-преподаватель PersonaLab Workshop

## Что это

ИИ-агент-преподаватель для 8-недельного воркшопа по созданию цифровых персонажей.
Форк NetTyan, адаптированный под образовательный контекст (голосовой диалог, RAG по курсу).

- **Платформа:** ИТМО AI Talent Hub / PersonaLab
- **Трек ВКР:** Образовательный

## Быстрый старт

```bash
cp .env.example .env
# Заполнить API ключи и настройки аудио в .env
pip install -e .
# Запустить Vosk TTS сервер (отдельный проект)
python src/main.py
```

## Структура проекта

```
src/
  main.py                  # точка входа (Gradio UI + multiprocessing)
  agent/                   # CoreAgent, streaming_orchestrator, RAG, промпты, инструменты
    core_agent.py          # главный агент: step() loop, interrupt, stop commands
    streaming_orchestrator.py  # LLM streaming с queue+thread timeout
    meta_agent.py          # фоновый анализ контекста (Haiku)
    rag.py                 # FAISS RAG по материалам курса
    prompt_generation/     # prompt_constructor, format helpers
  lecture/                 # student_profiles, transcript_buffer, summarizer
  data_flow/               # ctx_handler, ctx_host (shared state)
  data_collectors/stt/     # STT через faster-whisper + interrupt + STT corrections
  tts/                     # Vosk TTS (primary), Fish Speech (legacy)
    simple_tts_handler.py  # queue-level prefetch streaming
    vosk/                  # vosk_tts.py client + sentence splitting
resources/
  Prompts/                 # personalities_professor.yml, instructions, tool_fewshots
  RAG/                     # course_materials/ (4 лекции), lecture_summaries/
  Audio/tts_cache/         # pre-synthesized common phrases
data/
  student_profiles.db      # SQLite (студент-профили)
  rag_vector_store/        # FAISS index (автосоздаётся)
```

## Архитектура (3 процесса)

```
STT Process (faster-whisper, CUDA)
  → ctx_chat (shared via multiprocessing.Manager)
  → interrupt TTS on real speech recognition

CoreAgent (main process)
  → construct_prompt (RAG, student profile, history)
  → stream Mistral (queue+thread, 10s timeout)
  → SentenceBuffer → tts_queue
  ← interrupt on new student message in ctx_chat

TTS Process (Vosk)
  → queue-level prefetch (synthesize next while playing current)
  → interrupt support
```

### Ключевые механизмы

- **Interrupt**: студент говорит → STT транскрибирует → interrupt TTS queue + break LLM stream
- **Stop commands**: "стоп/подождите/помолчите" → "Хорошо, слушаю." без вызова LLM
- **Post-interrupt re-entry**: после прерывания агент сразу обрабатывает новое сообщение
- **Spoken tracking**: в историю сохраняется только озвученная часть + [прервано студентом]
- **Prefetch TTS**: следующее предложение синтезируется пока текущее играет
- **LLM timeout**: queue.get(timeout=10) — если Mistral виснет, 10с и восстановление
- **Meta-agent guard**: только один meta-agent одновременно, не во время стрима

## Конфигурация

- `.env` — модели, API ключи, аудио-устройства (LiteLLM синтаксис)
- `resources/Prompts/personalities_professor.yml` — персонаж преподавателя
- TTS backend: `TTS_BACKEND=vosk`, `VOSK_SPEAKER_ID=4`, `VOSK_TTS_URL=http://localhost:22232`
- LLM: `CORE_LLM_MODEL_NAME=mistral/mistral-large-latest`

## Правила разработки

- Язык кода: Python 3.10+
- Код и комментарии: на английском
- Промпты и персонаж: на русском
- Конфиги: YAML
- **Весь неиспользуемый код NetTyan — удалять немедленно**
- **Хардкод "NetTyan" — заменять на get_name() / удалять**
- Новый функционал — в `src/lecture/` и `src/agent/`
