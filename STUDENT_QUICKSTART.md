# Студенческий quick-start

Пошаговая установка `AI Professor — Tutor` для индивидуальной работы.
Ориентировочное время: **40–60 минут** (включая скачивание моделей ~10 ГБ).

---

## 0. Что должно быть до начала

- **Windows 10/11** (x64)
- **NVIDIA GPU**, минимум 8 ГБ VRAM (для Whisper + Gemma одновременно)
- **Python 3.10** (только 3.10! не 3.11/3.12 — некоторые зависимости pin'нуты)
  - Скачать: https://www.python.org/downloads/release/python-31011/
- **Git** (https://git-scm.com)
- **Микрофон** (USB или встроенный) и **наушники/динамики**
- **20 ГБ свободного места** на диске

> VoiceMeeter Banana **не нужен** для Tutor-сборки. Звук берётся из системных устройств.

---

## 1. Клонирование репозитория

```powershell
git clone -b student-release https://github.com/kragger-ra/ai-professor.git AI-Professor-Tutor
cd AI-Professor-Tutor
```

---

## 2. LM Studio (локальная LLM + embeddings)

Tutor использует **две модели**, обе раздаются одним сервером LM Studio:

| Модель | Назначение | Размер | Точное имя в LM Studio |
|---|---|---|---|
| Gemma 3 E4B (IQ4_XS) | Основной LLM — ответы агента | ~5.9 ГБ | `google/gemma-4-e4b` |
| BGE-M3 | Эмбеддинги для RAG (поиск по материалам курса) | ~600 МБ | `text-embedding-bge-m3` (любой квант) |

### 2.1. Установка LM Studio

1. Скачай LM Studio: <https://lmstudio.ai>
2. Установи и запусти. При первом запуске LM Studio предложит обновить runtime — соглашайся (требуется runtime 2.13.0+ для Gemma 4)

### 2.2. Скачать обе модели

Вкладка **Discover** (значок лупы слева):

1. В поиск ввести `gemma-4-e4b` → выбрать **`bartowski/google/gemma-4-e4b-it-GGUF`** (или альтернативный публикатор) → нажать **Download** возле варианта **IQ4_XS**
2. В поиск ввести `bge-m3` → выбрать **`text-embedding-bge-m3`** → **Download** (любой квант, Q4 хватит)

Дождись окончания обоих download (LM Studio показывает прогресс).

### 2.3. Запустить локальный сервер

1. Перейди во вкладку **Developer** (значок `< >` слева)
2. В выпадающем списке моделей сверху выбери **gemma-4-e4b** → щёлкни **Load** или дождись автозагрузки
3. В правой панели **Load parameters** выстави:
   - **Context Length:** `4096`
   - **GPU Offload:** **Max** (двигатель ползунка до конца вправо)
   - **CPU Threads:** оставить default
4. В списке моделей **дополнительно** выбери **bge-m3** → **Load**. Обе модели должны быть загружены одновременно
5. Внизу-слева раздел **Server**:
   - **Port:** `22227` (важно — порт зашит в `.env.example`)
   - Нажми **Start Server**
6. Должна появиться зелёная индикация и URL `http://127.0.0.1:22227`

### 2.4. Проверка

```powershell
curl http://localhost:22227/v1/models
```

В ответе JSON должен содержать **обе** модели:
- `"id": "google/gemma-4-e4b"`
- `"id": "text-embedding-bge-m3"`

Если одной не хватает — вернись к шагу 2.3 пункту 4 и загрузи недостающую.

> Подробности по моделям, замеры VRAM, альтернативные кванты — `docs/LM_STUDIO_SETUP.md`.

### 2.5. Важно для бюджета VRAM

На RTX 4070 (12 ГБ) одновременно умещается: Gemma (~5.9 ГБ) + BGE-M3 (~0.6 ГБ) + Whisper-small из Tutor (~1 ГБ). Итого ~7.5 ГБ. Запас для пиков. Если VRAM меньше 10 ГБ — нагрузка на грани, может вылетать. См. альтернативы в `docs/LM_STUDIO_SETUP.md`.

---

## 3. Vosk TTS сервер

Vosk TTS сервер **встроен в репозиторий** (`vosk_tts_server/`). Отдельно ничего ставить не нужно — bat-скрипт стартует его автоматически через тот же venv.

При первом запуске библиотека `vosk_tts` скачает модель `vosk-model-tts-ru-0.9-multi` (~150 МБ). Это разовое действие, потом запускается мгновенно.

Проверка после запуска (выполнить пока bat работает):
```powershell
curl http://localhost:22232/health
```
Должен вернуть `{"status":"ok",...}`.

---

## 4. Python-окружение и зависимости

Проект использует `uv` — быстрый менеджер пакетов от Astral. Он автоматически создаёт `.venv/`, читает `pyproject.toml` и устанавливает зависимости из всех групп одной командой.

### Установить uv (если ещё нет)

```powershell
# Вариант 1: PowerShell-инсталлер (рекомендуется)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Вариант 2: winget
winget install --id=astral-sh.uv -e

# Вариант 3: через pip (если установлен Python)
pip install uv
```

Проверь установку:
```powershell
uv --version   # должно показать uv 0.x.x
```

### Установить зависимости проекта

```powershell
uv sync --all-groups
```

Команда сделает за ~3-5 минут:
- Скачает Python 3.10.9 в кэш uv (если в системе нет)
- Создаст `.venv/` в корне проекта
- Установит `pyproject.toml` deps + группы `dev` / `stt` / `simpletts` / `gpu`

После завершения `.venv\Scripts\python.exe` — это твой venv-Python. Bat-скрипты уже знают про него и используют автоматически.

### Альтернатива через pip (без uv)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e .
pip install pytest-bdd faster-whisper vosk-tts edge-tts scipy onnxruntime-gpu
```

GPU-вариант ctranslate2 (для `STT_COMPUTE_DEVICE=cuda`) faster-whisper подтянет автоматически при первом запуске.

---

## 5. Конфигурация `.env`

```powershell
copy .env.example .env
```

Открой `.env` и проверь / заполни:

| Поле | Что вписать |
|---|---|
| `USE_LOCAL_LLM` | `true` (используем LM Studio) |
| `LM_STUDIO_MODEL_NAME` | `google/gemma-4-e4b` (как в LM Studio) |
| `VOSK_TTS_URL` | `http://localhost:22232` |
| `MISTRAL_API_KEY` | оставь пустым (fallback не обязателен) |
| `SOUND_DEVICE_OUT` | пусто = системный default. Можно указать имя (см. ниже) |
| `MIC_DEVICE_NAME` | пусто = системный default |

Узнать имена аудиоустройств:
```powershell
.venv\Scripts\python.exe -c "import sounddevice as sd; print(sd.query_devices())"
```

Скопируй точное имя нужного устройства в `.env` если default не подходит.

---

## 6. Подготовка учебных материалов

### Быстрый путь — встроенный образец

В репо лежит готовый RAG-пакет для проверки: `samples/vyshmat/` — три раздела по высшей математике (производные, интегралы, матрицы). Не нужно ничего готовить, чтобы протестировать систему.

После запуска Tutor (см. шаг 7) просто скажи в микрофон:

> «Загрузи предмет Вышмат из папки [полный путь до клона]\\samples\\вышмат»

Или, чтобы не диктовать длинный путь — скопируй пакет в простую папку:
```powershell
xcopy samples\vyshmat D:\vyshmat\ /E /I
```
Потом голосом:
> «Загрузи предмет Вышмат из папки D двоеточие вышмат»

Подробнее об образце — [samples/README.md](samples/README.md).

### Свой курс через CLI

Чтобы добавить материалы своего курса, упакуй их в RAG-пакет:

```powershell
uv run tools\prepare_rag_package.py `
    --source D:\my_lectures `
    --out D:\courses\linal `
    --course-name "Линейная алгебра" `
    --course-topic "векторы и матрицы" `
    --short-name "ЛинАл" `
    --teaching-style "строго"
```

> Без uv: `.venv\Scripts\python.exe tools\prepare_rag_package.py ...`

Подробности — [docs/RAG_PACKAGE_GUIDE.md](docs/RAG_PACKAGE_GUIDE.md).

---

## 7. Запуск

```powershell
.\start_professor_tutor.bat
```

Скрипт:
1. Запустит Vosk TTS (если ещё не запущен)
2. Запустит главное приложение (Gradio)
3. Откроет http://localhost:22229 в браузере (~15 сек ожидания)

В Gradio:
1. Вкладка **Chat** — нажми **Start** (зелёный индикатор «Active»)
2. Скажи в микрофон: «Привет, я Алексей» (представься — для профиля)
3. «Загрузи предмет ЛинАл из папки D двоеточие курсес линал»
4. Дождись «Готово, загружено N фрагментов»
5. «Расскажи мне про матрицы» — начнётся мини-лекция
6. Молчи или задавай вопросы — после тишины запустится quiz

---

## 8. Остановка

```powershell
.\stop_professor.bat
```

Закроет все процессы (Python + Vosk TTS).

---

## Частые проблемы

| Симптом | Что проверить |
|---|---|
| `Connection refused localhost:22227` | LM Studio Developer-сервер не запущен / порт другой |
| `Connection refused localhost:22232` | Vosk TTS сервер не запущен |
| TTS не слышно | `python -c "import sounddevice as sd; print(sd.default.device)"` — есть ли default output |
| STT не реагирует | Микрофон Windows-default? Уровень громкости? Попробуй `MIC_DEVICE_NAME="ИМЯ ИЗ sd.query_devices"` |
| `CUDA out of memory` | Закрой браузер / другие GPU-приложения; модель Whisper в `.env` поставь `small` |
| Долгий первый ответ | Это **прогрев KV-cache** в LM Studio (~5 с при первом запросе). Дальше будет быстро. |

---

## Приватность и состояние данных

После клонирования репо и до первого запуска **никаких данных о тебе в системе нет**. Папка `data/` создаётся пустой при первом запуске Tutor.

Что хранится локально на твоей машине после первой сессии:

| Файл | Что внутри |
|---|---|
| `data/student_profiles.db` | SQLite-профиль: имя, общие интересы, слабые темы (заполняется автоматически меж-агентом по итогам интеракций) |
| `data/rag_vector_store/` | FAISS-индекс по твоим учебным материалам |
| `data/current_course.json` | Активный курс (имя + путь к материалам) |
| `data/transcripts/*.jsonl` | Сырые транскрипты твоих голосовых интеракций (по дням) |
| `data/lecture_summaries/*.md` | Автоконспекты прочитанных агентом лекций |
| `data/metrics.db` | Технические метрики latency и количеств интеракций |

**Никакой информации о других пользователях в репо нет** — папка `data/` исключена из git (`.gitignore`), её содержимое создаётся локально твоим экземпляром Tutor.

Чтобы **сбросить состояние** (например, для повторной апробации с чистого листа):
```powershell
.\stop_professor.bat
Remove-Item -Recurse -Force data
```

Профиль создаётся только если ты явно представишься агенту голосом («Привет, я Алексей»). Без представления записи о тебе не появятся.

---

## Обратная связь для апробации

Все наблюдения / баги / неожиданное поведение пиши в `APROBATION_LOG.md` (Markdown-таблица в корне проекта).
Если файл не создан — создай по шаблону:

```markdown
| Timestamp | Сценарий | Наблюдение | Ожидалось | Severity | Repro |
|---|---|---|---|---|---|
| 2026-05-12 14:33 | B.2.2 voice load | "Папка не найдена" хотя путь правильный | Загрузка курса | HIGH | "загрузи предмет линал из папки D двоеточие курсес линал" |
```

Severity: `BLOCKER` / `HIGH` / `MEDIUM` / `LOW` / `UX`.
