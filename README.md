# AI Professor — Tutor edition

Голосовой ИИ-тьютор для **индивидуальной работы студента** с собственным учебным материалом.
Загружает курс из своих файлов, читает лекции по запросу, задаёт проверочные вопросы и адаптируется к слабым местам ответов.

**Платформа:** ИТМО AI Talent Hub
**Трек ВКР:** Образовательный
**Сборка:** Tutor (индивидуальная). Аудиторная версия — ветка `main`.

> Это `student-release` — публичная ветка для апробации с участниками. Если ищешь preset-курс PersonaLab — открой ветку `main`.

---

## Что умеет

- **Голосовая загрузка курса** — «загрузи предмет ЛинАл из папки D двоеточие курсы линал». Любой набор `.md`/`.txt` индексируется в FAISS как RAG.
- **Лекция по запросу** — «расскажи мне про матрицы». Тьютор готовит мини-лекцию по своим материалам.
- **Свободные вопросы** во время лекции — прерывание любой фразой, ответ с RAG-контекстом, продолжение лекции.
- **Quiz + remediation** — после лекции 3 проверочных вопроса; неверные ответы запускают цикл «упрощённое объяснение → retest» (hard-cap 3 итерации).
- **Профиль студента** — SQLite-память слабых тем; «покажи мой профиль» / «над чем мне поработать» зачитывает рекомендации.
- **Локальный LLM** по умолчанию — Gemma 3 E4B через LM Studio. В `Settings` tab можно переключить на Mistral / Claude / OpenRouter.
- **Vosk TTS** — русский голос с авто-ударениями (StressRNN), эмоциями, паузами по пунктуации.
- **Faster-whisper STT** на CUDA — распознавание ≈1 с на фразу.

## Системные требования

| Компонент | Минимум | Рекомендуется |
|---|---|---|
| ОС | Windows 10 (x64) | Windows 11 |
| GPU | NVIDIA, 8 ГБ VRAM | NVIDIA RTX 4070, 12 ГБ VRAM |
| RAM | 16 ГБ | 32 ГБ |
| Диск | 20 ГБ свободно (модели) | SSD |
| Микрофон | любой USB / встроенный | USB-микрофон |
| Аудиовыход | системные наушники/динамики | те же |

> **VoiceMeeter Banana НЕ требуется** в Tutor-сборке. Микрофон и наушники берутся из системных дефолтов ОС, маршрутизация для созвонов нужна только в Lecture-сборке.

## Быстрый старт

См. [STUDENT_QUICKSTART.md](STUDENT_QUICKSTART.md) — установка LM Studio, Vosk TTS, питон-зависимостей, `.env`, запуск.

Подготовка своего курса (RAG-пакета) — [docs/RAG_PACKAGE_GUIDE.md](docs/RAG_PACKAGE_GUIDE.md).

Сценарии ручного тестирования (для апробации) — [MANUAL_BDD_TESTS.md](../MANUAL_BDD_TESTS.md) (часть B).

## Архитектура

3 процесса, связанные через `multiprocessing.Manager`:

```
STT (faster-whisper, CUDA)      CoreAgent (main process)        TTS (Vosk)
  ↓                                 ↑    ↓                       ↑
  ctx_chat (shared)  ─────────────  │    │  ──────────  tts_queue (prefetch)
                                    │    │
                              [LLM stream (LM Studio Gemma)]
                                    │
                              [RAG (FAISS) + profile]
```

- **Streaming**: ответ начинает звучать через 2–3 с, прерывается голосом
- **Stop-commands**: «стоп / подождите / помолчите» → мгновенная пауза без вызова LLM
- **Skeleton mechanism**: двухпроходная подготовка лекции (outline → delivery) — активна
- **Settings tab**: hot-swap LLM-бэкенда между LM Studio / Mistral / Claude / OpenRouter (требует restart)

## Структура проекта

```
src/
  main.py                       # Gradio UI + multiprocessing entry
  agent/
    core_agent.py                # step() loop, interrupt, streaming
    streaming_orchestrator.py    # LLM stream с queue+thread timeout
    meta_agent.py                # фоновый анализ профиля
    rag.py                       # FAISS RAG
    prompt_generation/           # prompt_constructor + helpers
  lecture/
    integration.py               # LectureManager + FSM (delivery → qa → quiz → farewell)
    quiz_session.py              # quiz + remediation
    student_profiles.py          # SQLite профили
    wake_word.py                 # детекция обращений / команд
    voice_commands.py            # «загрузи предмет», «расскажи про», «покажи профиль»
  data_collectors/stt/           # faster-whisper STT + VAD
  tts/
    simple_tts_handler.py        # prefetch streaming
    vosk/                        # Vosk client + sentence splitter + stress
tools/
  prepare_rag_package.py         # CLI: папка с .md/.txt → RAG-пакет + course_config.yml
resources/
  Prompts/                       # personalities_professor.yml, instructions
  course_config.yml              # дефолтные {COURSE_NAME}/{COURSE_TOPIC} (General)
data/
  student_profiles.db            # SQLite (создаётся автоматически)
  rag_vector_store/              # FAISS index (заполняется при загрузке курса)
  current_course.json            # активный курс (cross-process state)
  metrics.db                     # SQLite метрики latency / интеракций
```

## Конфигурация

Главные переменные `.env` (полный список — `.env.example`):

| Переменная | Назначение |
|---|---|
| `USE_LOCAL_LLM` | `true` — LM Studio Gemma; `false` — облако |
| `LM_STUDIO_MODEL_NAME` | `google/gemma-4-e4b` (default) |
| `CORE_LLM_MODEL_NAME` | Fallback для облака (`mistral/mistral-large-latest`) |
| `MISTRAL_API_KEY` / `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY` | Опциональные ключи (пусто = только локально) |
| `TTS_BACKEND`, `VOSK_TTS_URL`, `VOSK_SPEAKER_ID` | Vosk TTS |
| `FASTER_WHISPER_MODEL_NAME` | `small` (быстро) / `large-v3-turbo` (точно) |
| `AUDIO_MODE` | `none` (default, без VM) / `local` / `meeting` (Lecture-сборка) |
| `SOUND_DEVICE_OUT` / `MIC_DEVICE_NAME` | Имена устройств (пусто = системный default) |

## Лицензия и контекст

Это исследовательская сборка к ВКР. Используется при апробации с реальными студентами для сбора UX-наблюдений, метрик latency и багов перед следующей версией.

Для сообщений об ошибках при апробации — заполни `APROBATION_LOG.md` в корне (timestamp / сценарий / наблюдение / ожидаемо / severity).
