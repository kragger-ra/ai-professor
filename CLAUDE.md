# AI Professor — Tutor build

Голосовой ИИ-тьютор для индивидуальной работы студента. Загружает свой курс из `.md`/`.txt`, читает мини-лекции по запросу, проводит quiz с remediation-циклом, ведёт SQLite-профиль слабых тем.

- **Платформа:** ИТМО AI Talent Hub
- **Трек ВКР:** Образовательный
- **Парная сборка:** Lecture (ветка `main`) — для аудиторного режима

## Быстрый старт

```powershell
copy .env.example .env
# По умолчанию: USE_LOCAL_LLM=true, AUDIO_MODE=none
pip install -e .

# Запустить LM Studio (порт 22227) + Vosk TTS (22232)
.\start_professor_tutor.bat
```

UI: http://localhost:22229

> **VoiceMeeter Banana НЕ требуется** в Tutor-сборке. Звук берётся из системных устройств ОС.

Студенческая инструкция: `STUDENT_QUICKSTART.md`. Подготовка RAG-пакета: `docs/RAG_PACKAGE_GUIDE.md`.

## Структура проекта

```
src/
  main.py                       # Gradio UI + multiprocessing entry (порт 22229)
  agent/
    core_agent.py                # step() loop, interrupt, FSM, voice commands
    streaming_orchestrator.py    # LLM stream с queue+thread timeout
    meta_agent.py                # фоновый анализ профиля
    rag.py                       # FAISS RAG + reload_from_path
    prompt_generation/           # prompt_constructor + helpers
  lecture/
    integration.py               # LectureManager
    quiz_session.py              # quiz + remediation цикл (hard-cap 3 итерации)
    student_profiles.py          # SQLite слабые места + recommendations
    wake_word.py                 # детекция обращений
  data_collectors/stt/           # faster-whisper STT + VAD
  tts/
    simple_tts_handler.py        # queue-level prefetch streaming
    vosk/                        # Vosk client + sentence splitter + stress
tools/
  prepare_rag_package.py         # CLI: папка с .md/.txt → RAG-пакет + course_config.yml
resources/
  Prompts/                       # personalities_professor.yml
  course_config.yml              # дефолтные {COURSE_NAME}/{COURSE_TOPIC} (General)
data/
  student_profiles.db            # SQLite (создаётся автоматически)
  rag_vector_store/              # FAISS index (заполняется при загрузке курса)
  current_course.json            # активный курс (cross-process state через mtime-cache)
  metrics.db                     # SQLite метрики latency / интеракций
```

## Архитектура (3 процесса)

```
STT (faster-whisper, CUDA)      CoreAgent (main)             TTS (Vosk)
     ↓                              ↑    ↓                       ↑
     ctx_chat ←─── multiprocessing.Manager ─────── tts_queue (prefetch)
                                    ↓
                       [LLM stream + RAG + profile + voice commands]
```

### LLM-стек

- **Default:** LM Studio Gemma 3 E4B (IQ4_XS, локальный, `USE_LOCAL_LLM=true`)
- **Fallback:** Mistral / Claude / OpenRouter — переключается через Settings tab (требует restart)
- **ThinkingFilter**: streaming с `TRIGGER_START` маркером отсекает leaked reasoning
- **Skeleton mechanism**: двухпроходная подготовка лекции (outline → delivery, `[END]` stop). В Tutor **включён** (`USE_SKELETON=true`) и протестирован

### Уникальные фичи Tutor (нет в Lecture)

- **Голосовая загрузка RAG**: «загрузи / добавь / подгрузи предмет X из папки Y»
  → `core_agent._handle_tutor_load_subject` → `rag.reload_from_path` + apply `course_config.yml`
- **Голосовой выбор темы**: «расскажи мне про X» → `_handle_tutor_topic_lecture` → запуск лекции из RAG
- **Quiz + remediation**: после лекции 3 вопроса; ≥2 неверных → упрощённое объяснение слабого блока + retest (cap 3 итерации в `quiz_session.MAX_ITERATIONS`)
- **Профиль студента**: «покажи мой профиль» / «над чем мне поработать» → `_handle_profile_query` → SQLite weak_blocks + рекомендации (личностные поля НЕ озвучиваются)
- **CLI упаковки курса**: `tools/prepare_rag_package.py` создаёт самодостаточный RAG-пакет с `course_config.yml`

### Общие механизмы (как в Lecture)

- **Interrupt**: студент говорит → STT транскрибирует → interrupt TTS queue + break LLM stream
- **Stop-commands**: «стоп / подождите / помолчите» → мгновенная остановка без LLM
- **Post-interrupt re-entry**, **prefetch TTS**, **LLM timeout 10s**
- **FSM**: `idle → delivering → qa_audience → qa_quiz → farewell` + remediation branch

## Конфигурация

- `.env` — модели, API ключи. Шаблон в `.env.example`. По умолчанию: `USE_LOCAL_LLM=true`, `AUDIO_MODE=none`
- `resources/Prompts/personalities_professor.yml` — персонаж преподавателя
- `resources/course_config.yml` — `{COURSE_NAME}` / `{COURSE_TOPIC}` placeholders (cross-process через `data/current_course.json` mtime-cache)
- TTS: `TTS_BACKEND=vosk`, `VOSK_SPEAKER_ID=4`, `VOSK_TTS_URL=http://localhost:22232`
- LLM (default): `LM_STUDIO_MODEL_NAME=google/gemma-4-e4b`
- Audio: `AUDIO_MODE=none` (без VM, default) / `local` / `meeting` (последние две — Lecture-сценарий)

## Правила разработки

- Язык кода: Python 3.10 (только!)
- Код и комментарии: на английском
- Промпты и персонаж: на русском
- Конфиги: YAML
- **Любой обнаруженный хардкод "NetTyan" — удалять немедленно**
- **Эта сборка живёт в ветке `student-release`** репо `kragger-ra/ai-professor` (отдельная история от Lecture-main)
- Новый Tutor-only функционал — в `src/lecture/quiz_session.py`, `src/agent/core_agent.py` (handlers `_handle_tutor_*`)

## Тестирование

- BDD: `pytest-bdd` 8.x, ~34 Tutor сценария в `tests/bdd/`
- Ручные сценарии: `MANUAL_BDD_TESTS.md` в корне (часть B)
- Apробационные баги: `APROBATION_LOG.md` (создаётся студентом при апробации)
