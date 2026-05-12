# AI Professor — Lecture build

Голосовой ИИ-преподаватель для аудитории. Читает лекцию по теме, отвечает на свободные вопросы во время и после, проводит проверочный quiz, пишет автоконспект в `.md`.

- **Платформа:** ИТМО AI Talent Hub
- **Трек ВКР:** Образовательный
- **Парная сборка:** Tutor (ветка `student-release`) — для индивидуальной работы со студентом

## Быстрый старт

```powershell
copy .env.example .env
# Заполнить API ключи и аудио-устройства
pip install -e .

# Запустить LM Studio (порт 22227) + Vosk TTS (22232) + VoiceMeeter Banana
.\start_professor.bat
```

UI: http://localhost:22228

## Структура проекта

```
src/
  main.py                       # Gradio UI + multiprocessing entry
  agent/
    core_agent.py                # step() loop, interrupt, streaming, FSM
    streaming_orchestrator.py    # LLM stream с queue+thread timeout
    meta_agent.py                # фоновый анализ профиля
    rag.py                       # FAISS RAG
    prompt_generation/           # prompt_constructor + helpers
  lecture/
    integration.py               # LectureManager — фасад FSM
    summarizer.py                # map-reduce суммаризация
    transcript_buffer.py         # буфер STT-сегментов
    student_profiles.py          # SQLite профили студентов
    wake_word.py                 # детекция обращений
  data_flow/                     # ctx_handler, ctx_host (shared state)
  data_collectors/stt/           # faster-whisper STT + VAD
  tts/
    simple_tts_handler.py        # queue-level prefetch streaming
    vosk/                        # Vosk client + sentence splitter + stress
  utils/voicemeeter_control.py   # VoiceMeeter Banana routing (Lecture-only)
resources/
  Prompts/                       # personalities_professor.yml, instructions
  RAG/                           # course_materials/, lecture_summaries/
data/
  student_profiles.db            # SQLite (создаётся автоматически)
  rag_vector_store/              # FAISS index
  lecture_summaries/             # автоконспекты .md после лекций
  metrics.db                     # SQLite метрики latency
```

## Архитектура (3 процесса)

```
STT (faster-whisper, CUDA)      CoreAgent (main)             TTS (Vosk)
     ↓                              ↑    ↓                       ↑
     ctx_chat ←─── multiprocessing.Manager ─────── tts_queue (prefetch)
                                    ↓
                       [LLM stream + RAG + profile]
```

### LLM-стек

- **Default:** LM Studio Gemma 3 E4B (IQ4_XS, локальный, `USE_LOCAL_LLM=true`)
- **Fallback:** Mistral / Claude / OpenRouter — переключается через Settings tab (требует restart)
- **ThinkingFilter**: streaming с `TRIGGER_START` маркером отсекает leaked reasoning
- **Skeleton mechanism**: двухпроходная подготовка лекции (outline → delivery, `[END]` stop). В Lecture **отключён** — Pass 2 ломает stop sequence на длинных запросах

### Ключевые механизмы

- **Interrupt**: студент говорит → STT транскрибирует → interrupt TTS queue + break LLM stream
- **Stop-commands**: «стоп / подождите / помолчите» → мгновенная остановка без вызова LLM
- **Post-interrupt re-entry**: после прерывания агент сразу обрабатывает новое сообщение
- **Spoken tracking**: в историю сохраняется только озвученная часть + `[прервано студентом]`
- **Prefetch TTS**: следующее предложение синтезируется пока текущее играет
- **LLM timeout**: `queue.get(timeout=10)` — защита от зависания провайдера
- **FSM лекции**: `idle → delivering → qa_audience → qa_quiz → farewell`
- **Auto-summary**: фоновый поток из `_enter_farewell` пишет `.md` в `data/lecture_summaries/`

## Конфигурация

- `.env` — модели, API ключи, аудио-устройства (LiteLLM синтаксис). Шаблон в `.env.example`
- `resources/Prompts/personalities_professor.yml` — персонаж преподавателя
- `resources/course_config.yml` — `{COURSE_NAME}` / `{COURSE_TOPIC}` placeholders
- TTS: `TTS_BACKEND=vosk`, `VOSK_SPEAKER_ID=4`, `VOSK_TTS_URL=http://localhost:22232`
- LLM (default): `LM_STUDIO_MODEL_NAME=google/gemma-4-e4b`
- Audio: `AUDIO_MODE=local` (VoiceMeeter) / `meeting` (Zoom routing) / `none` (без VM)

## Правила разработки

- Язык кода: Python 3.10 (только!)
- Код и комментарии: на английском
- Промпты и персонаж: на русском
- Конфиги: YAML
- **Любой обнаруженный хардкод "NetTyan" — удалять немедленно**
- **Изменения в индивидуальном режиме** идут в ветку `student-release` (репо `kragger-ra/ai-professor`), не в `main`
- Новый функционал — в `src/lecture/` или `src/agent/`

## Тестирование

- BDD: `pytest-bdd` 8.x, ~23 Lecture сценария в `tests/bdd/`
- Ручные сценарии: `MANUAL_BDD_TESTS.md` в корне (часть A)
