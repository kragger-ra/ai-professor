# AI Professor — Tutor (v2)

Голосовой ИИ-тьютор для **индивидуальной работы студента** с собственным
учебным материалом. Загружает курс из своих файлов (`.md` / `.txt` / `.pdf` /
`.docx`), отвечает на вопросы голосом со ссылкой на материал, ведёт
кросс-сессионную память и адаптируется к манере общения студента.

**Платформа:** ИТМО AI Talent Hub · **Трек ВКР:** Образовательный · **Ветка:** `tutor-v2`

> ⚠️ Research prototype. Не production. Используется для пилотной апробации
> с реальными участниками и сбора метрик. API-ключи и веса моделей в репо
> не хранятся — поднимаются локально / через переменные окружения.

---

## Что умеет

- **Свободный голосовой Q&A с RAG** — студент задаёт вопрос, тьютор отвечает
  голосом, опираясь на загруженный курс. Перебивание любой фразой, продолжение
  по «продолжай / дальше», возврат по «вернёмся / назад».
- **Команды стоп/пауза без вызова LLM** — «стоп / подождите / помолчите» →
  мгновенная пауза.
- **Кросс-сессионная память + профиль студента** — тезисный rolling summary
  предыдущих сессий, сохраняется между запусками.
- **Манеры общения** — «говори формально / дружелюбно / нейтрально» (3 пресета
  стиля ответа).
- **Board sidecar (опционально)** — отдельный PySide6-процесс: chalk-доска
  с KaTeX, Telegram-чат, ридер PDF/DOCX/MD. См. `board/` и
  `docs/ARCHITECTURE.md`.

## Два режима работы

| | Облачный (по умолчанию) | Полностью локальный |
|---|---|---|
| LLM | OpenAI / любой litellm-провайдер | Gemma E4B через LM Studio |
| Эмбеддинги RAG | OpenAI `text-embedding-3-small` | bge-m3 через LM Studio |
| Внешние зависимости | только `OPENAI_API_KEY` | LM Studio на `:22227`, веса локально |
| Когда выбирать | быстрый старт, апробация | без интернета / приватность |

«Из коробки» (`.env.example`) включён **облачный** режим: достаточно одного
`OPENAI_API_KEY`, LM Studio запускать не нужно. Для полностью локального режима —
`USE_LOCAL_LLM=true` + LM Studio (см. `docs/BETA_QUICKSTART.md`).

## Архитектура

Один процесс, 3 рабочих потока, связанные двумя `queue.Queue` и одним
`threading.Event` прерывания. Опциональный board sidecar — отдельный процесс,
общается через два JSONL-файла.

```
capture/STT  --input_q-->  agent  --tts_q-->  playback
     |                                            ^
     +------------------ interrupt ---------------+
```

Детали (потоки, очереди, preflight pool RAG ‖ мета-агент, объект «Ответ»,
board IPC) — `docs/ARCHITECTURE.md`.

## Быстрый старт

```powershell
# 1. Клон
git clone -b tutor-v2 https://github.com/kragger-ra/ai-professor.git AI-Professor-Tutor
cd AI-Professor-Tutor

# 2. Установка одной командой (идемпотентно: создаёт .venv на Python 3.10,
#    ставит все extras, разворачивает .env из шаблона)
setup.bat

# 3. Конфигурация: открой .env и впиши OPENAI_API_KEY
#    (облачный режим — больше ничего не нужно)

# 4. Запуск
start_tutor_v2.bat
```

Лаунчер `start_tutor_v2.bat` автоматически:
- поднимает встроенный Vosk-TTS сервер (`scripts/_run_vosk_tts.bat`);
- проверяет LM Studio на `:22227` — если запущен, доступны локальные LLM
  и эмбеддинги; если нет — тьютор работает на облаке (LM Studio не обязателен);
- запускает board sidecar, если установлен PySide6;
- запускает голосовой конвейер.

`stop_tutor_v2.bat` — остановка всех процессов. `start_board.bat` — поднять
только board-панель отдельно.

### Установка вручную (без `setup.bat`)

```powershell
py -3.10 -m venv .venv          # Python 3.10 строго — 3.11/3.12 ломают зависимости
.venv\Scripts\activate

# через uv (pyproject использует PEP-735 dependency-groups):
uv sync --group stt --group simpletts --group gpu --group board

# либо через pip:
pip install -e .
copy .env.example .env
```

Подготовка своего курса (RAG-пакета из `.md` / `.txt` / `.pdf` / `.docx`) —
`docs/RAG_PACKAGE_GUIDE.md`, CLI `tools/prepare_rag_package.py` или drag-and-drop
в Course Builder панели board.

## Системные требования

| Компонент | Минимум | Рекомендуется (тестовый стенд) |
|---|---|---|
| ОС | Windows 10 x64 | Windows 11 |
| GPU | NVIDIA, 8 ГБ VRAM (для STT) | NVIDIA RTX 4070, 12 ГБ VRAM |
| RAM | 16 ГБ | 32 ГБ |
| Диск | 20 ГБ (модели) | SSD |
| Python | 3.10 (строго) | 3.10.11 |
| Микрофон / выход | любой USB или встроенный | USB-микрофон + наушники |

> В облачном режиме GPU нужен только для STT (faster-whisper). Полностью
> локальный режим дополнительно требует VRAM под Gemma E4B + bge-m3.

VoiceMeeter Banana НЕ требуется в одиночном режиме (`AUDIO_MODE=none`).
Нужен только для маршрутизации в созвоны / OBS (`AUDIO_MODE=meeting`).

## Reproducibility

Стенд, на котором собирались числа в ВКР:

- **GPU:** NVIDIA RTX 4070, 12 ГБ VRAM, CUDA 12.x
- **Python:** 3.10.11
- **OS:** Windows 11 Pro 22631
- **Ключевые зависимости** (точные версии — `pyproject.toml`):
  - `faster-whisper` (STT, ctranslate2 backend)
  - `litellm` (LLM provider abstraction) + `openai` (прямые вызовы)
  - `langchain-community` + `faiss-cpu` (RAG)
  - `vosk-tts` (TTS, CPU) · `stressrnn` + `onnxruntime-gpu` (авто-ударения, extra `[gpu]`)
  - `PySide6` (extra `[board]`, для sidecar)

Веса моделей **не хранятся в репо**. Подтягиваются:
- Whisper — автоматически через `faster_whisper` при первом запуске;
- эмбеддинги — облачные (`text-embedding-3-small`) без локальных весов, либо
  bge-m3 через LM Studio в локальном режиме;
- Gemma E4B + bge-m3 (локальный режим) — вручную через LM Studio CLI
  (см. `docs/BETA_QUICKSTART.md`);
- Vosk-TTS — встроен в `vosk_tts_server/` (русский голос).

> Эвалы RAG в ВКР (`research/eval_results/`) считались на bge-m3 —
> локальной модели эмбеддингов.

## Структура проекта

```
tutor/                  # ядро v2
  app.py                # entry point: потоки, очереди, interrupt event
  audio/                # capture (VAD) + STT + playback + ambient
  brain/                # agent, answer, llm, rag, embeddings, meta, prompt,
                        #   commands, course, profile, session_memory
  tts/vosk_client.py    # Vosk-TTS клиент
  board_log.py          # IPC: tutor → board (JSONL append)
  commands_tail.py      # IPC: board → tutor (JSONL tail)
  document_store.py     # документы, поднятые в системный промпт через board
board/                  # PySide6 sidecar (опционально, extra [board])
  app.py, ui.py         # KaTeX-доска, чат, PDF/DOCX-ридер
  course_builder.py     # drag-and-drop индексация курса
docs/
  BETA_QUICKSTART.md    # пошаговый запуск на чистой машине
  ARCHITECTURE.md       # живая справка по архитектуре v2
  VOICE_COMMANDS.md     # справочник голосовых команд
  RAG_PACKAGE_GUIDE.md  # как собрать свой курс
  TROUBLESHOOTING.md    # частые проблемы при запуске
tools/
  prepare_rag_package.py  # CLI: папка → RAG-пакет
resources/
  Prompts/personalities_professor.yml
  RAG/course_materials/   # дефолтные .md/.txt для preset-курса
  course_config.yml       # placeholders COURSE_NAME / COURSE_TOPIC
data/                   # gitignored: FAISS index, профиль, память сессий
  rag_vector_store/ · session_memory.json · student_profile.json · metrics.db
setup.bat               # one-shot установка (.venv + extras + .env)
start_tutor_v2.bat      # лаунчер (Vosk + board + tutor)
start_board.bat         # запуск только board-панели
stop_tutor_v2.bat       # остановка всех процессов
reset_memory.bat        # сброс session_memory + student_profile + board log
```

> `research/` (эвалы и данные апробации) и часть внутренних dev-доков —
> приватные, исключены из публичной сборки через `.gitignore`. Раздел ниже
> описывает их для контекста ВКР, в клоне их нет.

## Конфигурация

Полный список — `.env.example`. Главные переменные:

| Переменная | Назначение | Default |
|---|---|---|
| `USE_LOCAL_LLM` | `true` — Gemma через LM Studio; `false` — облако | `false` |
| `CORE_LLM_MODEL_NAME` | Облачная модель (litellm-формат) | `openai/gpt-4o-mini` |
| `OPENAI_API_KEY` | Ключ для облачного режима | — |
| `EMBEDDINGS_MODEL` | Модель эмбеддингов RAG | `text-embedding-3-small` |
| `LM_STUDIO_MODEL_NAME` | Локальная LLM (при `USE_LOCAL_LLM=true`) | `google/gemma-4-e4b` |
| `FASTER_WHISPER_MODEL_NAME` | STT-модель | `large-v3-turbo` (рус: `dvislobokov/...-russian`) |
| `VOSK_SPEAKER_ID` | Голос TTS, 0..4 | `3`/`4` |
| `META_BACKEND` | Бэкенд мета-агента: `local` / `cloud` | `local` |
| `AUDIO_MODE` | `none` / `meeting` (через VoiceMeeter) | `none` |
| `AMBIENT_SOUND` | `on`/`off` (off лучше для STT) | `off` |

## Research artifacts

Числа и графики для ВКР (защита 09.06):

- `research/aprobation/` — pilot N=9 на курсе PersonaLab Workshop:
  pre/post-тесты (24 вопроса, варианты A/B), анкета восприятия, скрипты
  брифинга, протоколы. Прирост знаний +10.75/24 в среднем (21%→66%).
- `research/aprobation_whitecoding/` — pilot N=3 на курсе «Программирование
  на естественном языке» (вайб-кодинг): pre/mid/post, 16 вопросов, 3 формы.
- `research/eval_results/`:
  - `01_inventory.md` — стек, VRAM peak, TTFT, retrieval p50
  - `02_rag_retrieval.md`, `02b_*` — RAG-метрики, corpus ablation
  - `03_faithfulness.md`, `03b_faithfulness_n100.md` — фактологическая
    точность (N=20 → N=97; halluc 22%→7.2% после disclaimer-фикса)
  - `04_external_validation.md` — bge-m3 на публичном RuBQRetrieval
    (nDCG@10=0.69, hit@1=0.61 на 1692q/56826p)
  - `05_ablation_rag_prompt.md` — абляция RAG×персона (2×2)
  - `charts/` — PNG/SVG для презентации
  - `_*.json` — raw данные всех прогонов

## Лицензия и контекст

Research prototype. Используется при апробации с реальными студентами
для сбора UX-наблюдений, метрик latency и багов перед следующей итерацией.
Для сообщений об ошибках при апробации — заполни запись в любом из
протоколов `research/aprobation/`.
