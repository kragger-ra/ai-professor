# AI Professor

Голосовой ИИ-агент-преподаватель: читает лекции, отвечает на вопросы голосом в реальном времени, использует RAG по материалам курса и адаптируется к студенту.

**Платформа:** ИТМО AI Talent Hub
**Трек ВКР:** Образовательный

---

## Две сборки

Репозиторий содержит **две независимые сборки** в разных ветках:

| Ветка | Сценарий | Порт Gradio | VoiceMeeter | Уникальные фичи |
|---|---|---|---|---|
| **`main`** — Lecture | Аудитория: профессор читает лекцию + Q&A | `22228` | требуется (Zoom-mode / локальный) | автоконспект `.md` после лекции |
| **`student-release`** — Tutor | Индивидуальная работа со студентом | `22229` | **не требуется** | voice RAG-load, quiz + remediation, профиль студента |

### Для студентов на апробации

```bash
git clone -b student-release https://github.com/kragger-ra/ai-professor.git AI-Professor-Tutor
cd AI-Professor-Tutor
# дальше — STUDENT_QUICKSTART.md в корне ветки
```

Полная инструкция: [`STUDENT_QUICKSTART.md`](https://github.com/kragger-ra/ai-professor/blob/student-release/STUDENT_QUICKSTART.md) на ветке `student-release`.
Подготовка своего курса: [`docs/RAG_PACKAGE_GUIDE.md`](https://github.com/kragger-ra/ai-professor/blob/student-release/docs/RAG_PACKAGE_GUIDE.md).

### Для преподавателей (Lecture)

Это `main` — аудиторный режим. См. ниже быстрый старт.

---

## Общее ядро (одинаково в обеих сборках)

- **LLM**: локальная Gemma 3 E4B через LM Studio (default), либо облако (Mistral / Claude / OpenRouter)
- **STT**: faster-whisper large-v3 на CUDA, energy-based VAD, ~1с латентность
- **TTS**: Vosk русский голос с автоударениями (StressRNN), эмоциями, паузами по пунктуации
- **RAG**: FAISS + bge-m3 эмбеддинги через LM Studio
- **Streaming + interrupt**: первая фраза слышна через 2–3 с, прерывается голосом
- **Профиль студента**: SQLite, обновляется meta-agentом в фоне

## Быстрый старт (Lecture-сборка, main)

```powershell
git clone https://github.com/kragger-ra/ai-professor.git AI-Professor
cd AI-Professor

copy .env.example .env
# Заполнить API ключи, аудиоустройства

pip install -e .

# Запустить LM Studio (порт 22227) + Vosk TTS (22232) + VoiceMeeter Banana
.\start_professor.bat
```

UI: http://localhost:22228

## Архитектура

3 процесса, связанные через `multiprocessing.Manager`:

```
STT (faster-whisper)        CoreAgent (main)            TTS (Vosk)
     ↓                          ↑    ↓                      ↑
     ctx_chat ←────────────── shared ─────────── tts_queue (prefetch)
                                ↓
                       [LLM stream + RAG + profile]
```

### Ключевые механизмы

- **Interrupt**: студент говорит → STT транскрибирует → interrupt TTS queue + break LLM stream
- **Stop-commands**: «стоп / подождите / помолчите» → мгновенная остановка без LLM
- **Post-interrupt re-entry**: после прерывания агент сразу обрабатывает новое сообщение
- **Prefetch TTS**: следующее предложение синтезируется пока текущее играет
- **LLM timeout**: `queue.get(timeout=10)` — защита от зависания провайдера
- **Skeleton mechanism** (`USE_SKELETON=true`): двухпроходная подготовка — outline → delivery
- **FSM лекции**: `idle → delivering → qa_audience → qa_quiz → farewell`

## Структура проекта

```
src/
  main.py                       # Gradio UI + multiprocessing entry
  agent/
    core_agent.py                # step() loop, interrupt, streaming, FSM
    streaming_orchestrator.py    # LLM stream с queue+thread timeout
    meta_agent.py                # фоновый анализ контекста (профиль)
    rag.py                       # FAISS RAG
    prompt_generation/           # prompt_constructor + helpers
  lecture/
    integration.py               # LectureManager — фасад
    summarizer.py                # map-reduce суммаризация
    student_profiles.py          # SQLite профили студентов
    wake_word.py                 # детекция обращений
  data_collectors/stt/           # faster-whisper STT + VAD
  tts/
    simple_tts_handler.py        # queue-level prefetch streaming
    vosk/                        # Vosk client + sentence splitter + stress
  metrics/logger.py              # SQLite метрики
resources/
  Prompts/                       # personalities_professor.yml
  RAG/                           # course_materials/, lecture_summaries/
data/
  student_profiles.db            # SQLite (создаётся автоматически)
  rag_vector_store/              # FAISS index
  lecture_summaries/             # автоконспекты .md после лекций (только в Lecture)
  metrics.db                     # SQLite метрики latency
```

## Конфигурация

Главные переменные `.env` (полный список — `.env.example`):

| Переменная | Назначение |
|---|---|
| `USE_LOCAL_LLM` | `true` — LM Studio Gemma (default); `false` — облако |
| `LM_STUDIO_MODEL_NAME` | `google/gemma-4-e4b` |
| `CORE_LLM_MODEL_NAME` | Fallback для облака (`mistral/mistral-large-latest`) |
| `MISTRAL_API_KEY` / `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY` | Опциональные ключи |
| `TTS_BACKEND`, `VOSK_TTS_URL`, `VOSK_SPEAKER_ID` | Vosk TTS |
| `FASTER_WHISPER_MODEL_NAME` | `small` / `large-v3-turbo` |
| `AUDIO_MODE` | `local` / `meeting` (Lecture) / `none` (Tutor) |
| `USE_SKELETON` | Двухпроходная подготовка лекции (выкл по умолчанию в Lecture) |

## Зависимости

- Python 3.10 (только 3.10!)
- NVIDIA GPU, минимум 8 ГБ VRAM (рекомендуется RTX 4070 12 ГБ)
- LM Studio с runtime 2.13.0+ для Gemma 4
- Vosk TTS сервер (отдельный проект)
- VoiceMeeter Banana **только для Lecture** (для Tutor не нужен)

Замеры VRAM, выбор кванта, бенчи — `docs/LM_STUDIO_SETUP.md`.

## Тестирование

- **BDD**: `pytest-bdd` 8.x, 57 сценариев total (23 Lecture + 34 Tutor) — `tests/bdd/`
- **Ручное тестирование** для апробации: `MANUAL_BDD_TESTS.md` в корне репо (~30 живых сценариев с микрофоном)

## Лицензия и контекст

Исследовательская сборка ВКР. Используется при апробации с реальными студентами (май 2026) для сбора UX-наблюдений, метрик latency и баг-репортов перед следующей версией.
