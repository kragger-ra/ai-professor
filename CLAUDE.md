# AI Professor — Tutor build (v2)

Голосовой ИИ-тьютор для индивидуальной работы студента. Один процесс, линейный
голосовой конвейер: микрофон → STT → агент (RAG + LLM) → Vosk-TTS. Загружает свой
курс из `.md`/`.txt`, отвечает на вопросы голосом, читает мини-лекции по запросу,
ведёт кросс-сессионную память и профиль студента.

- **Платформа:** ИТМО AI Talent Hub
- **Трек ВКР:** Образовательный
- **Ветка:** `tutor-v2`
- **Парная сборка:** Lecture (ветка `main`) — для аудиторного режима

> v2 — переписанное ядро. Легаси-архитектура (4 процесса + `multiprocessing.Manager`,
> унаследованная от стримингового агента NetTyan) удалена в Фазе 7. План фаз и
> статус — `tutor/README.md`.

## Быстрый старт

```powershell
copy .env.example .env
pip install -e .

# Запустить LM Studio (порт 22227): модель LLM + bge-m3 для эмбеддингов RAG
.\start_tutor_v2.bat        # поднимает Vosk-TTS и запускает конвейер
```

Прямой запуск без bat: `python -m tutor.app`. Это консольное приложение — Gradio-UI
в v2 нет, лог идёт в консоль и `tutor_v2.log`.

> **VoiceMeeter Banana НЕ требуется** в Tutor-сборке. Звук берётся из системных
> устройств ОС (свой аудио-роутер — отложенная Фаза 8).

## Структура проекта

```
tutor/                  # v2 пакет — всё ядро здесь
  app.py                # entry point: поднимает потоки, очереди, interrupt event
  audio/
    capture.py          # микрофон + энергетический VAD
    stt.py              # faster-whisper STT (CUDA)
    playback.py         # озвучка Answer через Vosk, resumable
    ambient.py          # тихий эмбиент (луп комнаты + мур кота)
  brain/
    agent.py            # цикл агента, перебивание, стек ответов, голос-команды
    answer.py           # объект «Ответ» + стек (ядро interrupt-resume)
    llm.py              # стриминг-оркестратор: токены → предложения → TTS
    lm_client.py        # клиент OpenAI-совместимого LLM (OpenAI / LM Studio)
    rag.py              # FAISS RAG + reload_from_path (hot-swap корпуса)
    embeddings.py       # фабрика эмбеддингов (bge-m3)
    meta.py             # мета-агент: лёгкий пред-полёт перед Q&A
    prompt.py           # конструктор системного промпта
    commands.py         # роутер голосовых команд (манера, загрузка курса, пауза)
    course.py           # конфигурация курса (универсальный преподаватель)
    profile.py          # профиль студента (одиночный, переживает рестарт)
    session_memory.py   # кросс-сессионная память (тезисный rolling summary)
  tts/vosk_client.py    # Vosk-TTS клиент: стриминг, кэш фраз, пост-обработка
  _smoke_phase*.py      # автотесты фаз 2-4
tools/
  prepare_rag_package.py  # CLI: папка с .md/.txt → RAG-пакет + course_config.yml
resources/
  Prompts/                # personalities_professor.yml
  RAG/course_materials/   # дефолтные материалы курса (.md/.txt)
  course_config.yml       # {COURSE_NAME}/{COURSE_TOPIC} placeholders
data/
  rag_vector_store/        # FAISS index (заполняется при загрузке курса)
  session_memory.json      # кросс-сессионная память
  student_profile.json     # профиль студента
start_tutor_v2.bat         # launcher (Vosk-TTS + конвейер)
reset_memory.bat           # сброс session_memory.json + student_profile.json
```

## Архитектура (один процесс, 3 потока)

```
capture/STT  --input_q-->  agent  --tts_q-->  playback
     |                                            ^
     +------------------ interrupt ---------------+
```

Потоки связаны двумя `queue.Queue` и одним `threading.Event` прерывания. Ни
`multiprocessing.Manager`, ни IPC, ни прокси.

### Ключевые механизмы

- **Объект «Ответ»**: генерация расцеплена с озвучкой. Возврат после перебивания
  = до-озвучка из памяти БЕЗ повторного LLM-вызова.
- **Стек ответов**: вложенность 3 уровня, 4-й отбивается фразой + парковка.
  «продолжай» дочитывает текущий, «вернёмся/назад» поднимает к родителю.
- **Перебивание**: студент говорит → STT → interrupt event → стоп TTS + break
  LLM-стрима. Stop-команды («стоп / подождите») — без вызова LLM.
- **Мета-агент**: лёгкий пред-полёт параллельно RAG (stt_garbled, анафора,
  stuck-петли, mood, style_hint). Таймаут ожидания 4с.
- **Кросс-сессионная память + профиль**: тезисный конспект и имя/бэкграунд
  студента переживают рестарт; сброс — `reset_memory.bat`.

### LLM / RAG / TTS стек

- **LLM**: OpenAI-совместимый API. По умолчанию — локальная Gemma E4B через
  LM Studio (`USE_LOCAL_LLM=true`); облачный fallback (Mistral / Claude /
  OpenRouter) переключается в `.env` + рестарт.
- **RAG**: FAISS, эмбеддинги bge-m3. Hot-swap корпуса через
  `rag.reload_from_path` (голосовая команда «загрузи <название>»).
- **STT**: faster-whisper на CUDA, энергетический VAD в `capture.py`.
- **TTS**: Vosk-TTS сервер (порт 22232) — русский голос с авто-ударениями,
  паузами по пунктуации, пост-обработкой.

## Конфигурация

- `.env` — модели, ключи, аудио-устройства. Шаблон — `.env.example`.
- `resources/Prompts/personalities_professor.yml` — персонаж преподавателя.
- `resources/course_config.yml` — `{COURSE_NAME}` / `{COURSE_TOPIC}` placeholders.
- Подготовка своего курса (RAG-пакета) — `docs/RAG_PACKAGE_GUIDE.md`,
  CLI `tools/prepare_rag_package.py`.

## Правила разработки

- Язык кода: Python 3.10 (только!)
- Код и комментарии: на английском
- Промпты и персонаж: на русском
- Конфиги: YAML
- **Любой обнаруженный хардкод "NetTyan" — удалять немедленно**
- Весь код тьютора — в пакете `tutor/`. Каталог `src/` удалён (Фаза 7).
- Эта сборка живёт в ветке `tutor-v2`.

## Тестирование

Автотесты фаз — в самом пакете (нужны запущенные LM Studio + Vosk-TTS):

```
python -m tutor._smoke_phase2   # мозг: вопрос → ответ
python -m tutor._smoke_phase3   # перебивание + возврат
python -m tutor._smoke_phase4   # лимит вложенности (3 уровня)
python -m tutor.brain.answer    # объект «Ответ» и стек
```

План фаз и команды запуска — `tutor/README.md`. Голосовые команды и
справочник — `docs/VOICE_COMMANDS.md`. Квикстарт — `docs/BETA_QUICKSTART.md`.
