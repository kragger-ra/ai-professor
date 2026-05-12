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

## 2. LM Studio (локальная LLM)

Gemma 3 E4B — основной LLM. Работает офлайн, без облачных ключей.

1. Скачай и установи **LM Studio**: https://lmstudio.ai
2. Открой LM Studio → вкладка **Discover** → найди модель `google/gemma-4-e4b` (квант `IQ4_XS` ~5.9 ГБ) → Download
3. Перейди во вкладку **Developer** (значок `< >` слева)
4. Загрузи модель → выставь:
   - **Context length:** `4096`
   - **GPU offload:** Max
   - **Port:** `22227` (важно — порт зашит в `.env.example`)
5. Также скачай через **Discover** модель эмбеддингов `text-embedding-bge-m3` (квант любой, ~600 МБ). Она нужна для RAG.
6. Нажми **Start Server** — должен появиться `http://localhost:22227/v1` в статусе

Проверка:
```powershell
curl http://localhost:22227/v1/models
```
Должен вернуть JSON с двумя моделями: `google/gemma-4-e4b` и `text-embedding-bge-m3`.

> Подробности по моделям, замеры VRAM, альтернативные кванты — `docs/LM_STUDIO_SETUP.md`.

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

Чтобы тьютор «знал» твой курс, нужно собрать RAG-пакет из своих `.md`/`.txt` файлов:

```powershell
uv run tools\prepare_rag_package.py `
    --source D:\my_lectures `
    --out D:\courses\linal `
    --course-name "Линейная алгебра" `
    --course-topic "векторы и матрицы" `
    --short-name "ЛинАл" `
    --teaching-style "строго"
```

> Без uv можно через venv-Python напрямую: `.venv\Scripts\python.exe tools\prepare_rag_package.py ...`

Подробности и примеры — [docs/RAG_PACKAGE_GUIDE.md](docs/RAG_PACKAGE_GUIDE.md).

> Можно подготовить пакет позже — при первом запуске Tutor работает с дефолтным курсом из `resources/course_config.yml`. Свой курс загружается голосом или CLI.

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

## Обратная связь для апробации

Все наблюдения / баги / неожиданное поведение пиши в `APROBATION_LOG.md` (Markdown-таблица в корне проекта).
Если файл не создан — создай по шаблону:

```markdown
| Timestamp | Сценарий | Наблюдение | Ожидалось | Severity | Repro |
|---|---|---|---|---|---|
| 2026-05-12 14:33 | B.2.2 voice load | "Папка не найдена" хотя путь правильный | Загрузка курса | HIGH | "загрузи предмет линал из папки D двоеточие курсес линал" |
```

Severity: `BLOCKER` / `HIGH` / `MEDIUM` / `LOW` / `UX`.
