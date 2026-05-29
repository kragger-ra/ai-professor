# AI Professor — Tutor (v2)

Голосовой ИИ-тьютор для **индивидуальной работы студента** с собственным
учебным материалом. Загружает курс из своих файлов (`.md` / `.txt` / `.pdf`),
отвечает на вопросы голосом со ссылкой на материал, ведёт кросс-сессионную
память и адаптируется к манере общения студента.

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
- **Голосовая загрузка курса** — «загрузи персоналаб» / «загрузи курс
  программирование» — hot-swap FAISS-индекса без рестарта.
- **Манеры общения** — «говори формально / дружелюбно / нейтрально» (3 пресета
  стиля ответа).
- **Board sidecar (опционально)** — отдельный PySide6-процесс: chalk-доска
  с KaTeX, Telegram-чат, ридер PDF/DOCX/MD. См. `board/` и
  `docs/ARCHITECTURE.md`.

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

# 2. Окружение (Python 3.10 строго — 3.11/3.12 ломают зависимости)
py -3.10 -m venv .venv
.venv\Scripts\activate

# 3. Установка зависимостей через uv (рекомендовано — pyproject использует
# PEP-735 dependency-groups). Если нет uv: pip install uv
uv sync --group stt --group simpletts --group gpu --group board

# Без uv (через pip): основной пакет + ручная установка optional-групп
# pip install -e .
# pip install "faster-whisper~=1.2" "vosk-tts~=0.3" "edge-tts~=6.1" "scipy~=1.15" "stressrnn" "num2words~=0.5" "fastapi~=0.115" "uvicorn~=0.32"
# pip install "onnxruntime-gpu~=1.23"      # для StressRNN на GPU
# pip install "PySide6~=6.7"               # для board sidecar

# 4. Конфигурация
copy .env.example .env
# отредактируй .env: OPENAI_API_KEY (или USE_LOCAL_LLM=true + LM Studio)

# 5. Запуск
start_tutor_v2.bat
```

Лаунчер автоматически:
- проверяет, что LM Studio отвечает на `:22227` (warns если нет — RAG будет
  недоступен);
- поднимает встроенный Vosk-TTS сервер (`vosk_tts_server/`);
- запускает board sidecar, если PySide6 установлен (`pip install -e .[board]`);
- запускает голосовой конвейер.

Подготовка своего курса (RAG-пакета из `.md` / `.txt` / `.pdf` / `.docx`) —
`docs/RAG_PACKAGE_GUIDE.md` или drag-and-drop в Course Builder панели board.

## Системные требования

| Компонент | Минимум | Рекомендуется (тестовый стенд) |
|---|---|---|
| ОС | Windows 10 x64 | Windows 11 |
| GPU | NVIDIA, 8 ГБ VRAM | NVIDIA RTX 4070, 12 ГБ VRAM |
| RAM | 16 ГБ | 32 ГБ |
| Диск | 20 ГБ (модели) | SSD |
| Python | 3.10 (строго) | 3.10.11 |
| Микрофон / выход | любой USB или встроенный | USB-микрофон + наушники |

VoiceMeeter Banana НЕ требуется в одиночном режиме (`AUDIO_MODE=none`).
Нужен только для маршрутизации в созвоны / OBS (`AUDIO_MODE=meeting`).

## Reproducibility

Стенд, на котором собирались числа в ВКР:

- **GPU:** NVIDIA RTX 4070, 12 ГБ VRAM, CUDA 12.x
- **Python:** 3.10.11
- **OS:** Windows 11 Pro 22631
- **Ключевые зависимости** (полный список — `pyproject.toml`):
  - `faster-whisper` ~= 1.0 (STT, ctranslate2 backend)
  - `litellm` (LLM provider abstraction)
  - `openai` (для прямых OpenAI-вызовов)
  - `langchain-community` + `faiss-cpu` (RAG)
  - `vosk-tts` (TTS, CPU)
  - `onnxruntime-gpu` (extra `[gpu]`, для StressRNN)
  - `PySide6` ~= 6.7 (extra `[board]`, для sidecar)

Веса моделей **не хранятся в репо**. Подтягиваются:
- Whisper — автоматически через `faster_whisper` при первом запуске
- Gemma E4B + bge-m3 — вручную через LM Studio CLI (см. `STUDENT_QUICKSTART.md`)
- Vosk-TTS — встроен в `vosk_tts_server/` (русский голос)

## Структура проекта

```
tutor/                  # ядро v2
  app.py                # entry point: потоки, очереди, interrupt event
  audio/                # capture (VAD) + STT + playback + ambient
  brain/                # agent, answer, llm, rag, meta, prompt, commands,
                        #   course, profile, session_memory, board_extract
  tts/vosk_client.py    # Vosk-TTS клиент
  board_log.py          # IPC: tutor → board (JSONL append)
  commands_tail.py      # IPC: board → tutor (JSONL tail)
  document_store.py     # документы, поднятые в системный промпт через board
board/                  # PySide6 sidecar (опционально, extra [board])
  app.py, ui.py         # KaTeX-доска, чат, PDF/DOCX-ридер
  course_builder.py     # drag-and-drop индексация курса
docs/
  ARCHITECTURE.md       # живая справка по архитектуре v2
  VOICE_COMMANDS.md     # справочник голосовых команд
  VOICE_WALKTHROUGH.md  # сценарий первого запуска
  RAG_PACKAGE_GUIDE.md  # как собрать свой курс
tools/
  prepare_rag_package.py  # CLI: папка → RAG-пакет
research/               # эвалы + апробации (см. ниже)
  aprobation/           # PersonaLab Workshop, 9 сессий (pre/post, /24)
  aprobation_whitecoding/  # Программирование на естественном языке, 3 сессии
  eval_results/         # отчёты, графики, raw JSON
resources/
  Prompts/personalities_professor.yml
  RAG/course_materials/   # дефолтные .md/.txt для preset-курса
  course_config.yml       # placeholders COURSE_NAME / COURSE_TOPIC
data/                   # gitignored: FAISS index, профиль, память сессий
  rag_vector_store/
  session_memory.json
  student_profile.json
  metrics.db
start_tutor_v2.bat      # лаунчер (Vosk + board + tutor)
stop_tutor_v2.bat       # остановка всех процессов
reset_memory.bat        # сброс session_memory + student_profile + board log
```

## Конфигурация

Полный список — `.env.example`. Главные переменные:

| Переменная | Назначение |
|---|---|
| `USE_LOCAL_LLM` | `true` — Gemma через LM Studio; `false` — облако |
| `CORE_LLM_MODEL_NAME` | Облачная модель (litellm-формат: `openai/gpt-5.4`) |
| `OPENAI_API_KEY` | Ключ для облачного режима |
| `LM_STUDIO_MODEL_NAME` | `google/gemma-4-e4b` (default) |
| `FASTER_WHISPER_MODEL_NAME` | `large-v3-turbo` или `dvislobokov/faster-whisper-large-v3-turbo-russian` |
| `VOSK_SPEAKER_ID` | 0..4, рекомендован 3 или 4 |
| `META_BACKEND` | `local` или `cloud` (мета-агент: тот же LM Studio или отдельная облачная mini-модель) |
| `AUDIO_MODE` | `none` (default) / `meeting` (через VoiceMeeter) |
| `AMBIENT_SOUND` | `on`/`off` — тихий комнатный тон (off лучше для STT) |

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
  - `05_whitecoding_inventory.md` — стек для второго курса
  - `charts/` — 10 PNG/SVG для презентации
  - `_*.json` — raw данные всех прогонов

## Лицензия и контекст

Research prototype. Используется при апробации с реальными студентами
для сбора UX-наблюдений, метрик latency и багов перед следующей итерацией.
Для сообщений об ошибках при апробации — заполни запись в любом из
протоколов `research/aprobation/`.
