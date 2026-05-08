# AI Professor — Полная документация проекта

**Версия:** LocalLLMExperement (экспериментальная ветка с локальной LLM)
**Дата:** 2026-04-14
**Платформа:** ИТМО AI Talent Hub / PersonaLab Workshop
**Трек:** Образовательный (ВКР)

---

## Оглавление

### Часть I — Обзор проекта
1. [Что такое AI Professor](#1-что-такое-ai-professor)
2. [Цели и задачи](#2-цели-и-задачи)
3. [Два режима работы: Cloud vs Local](#3-два-режима-работы-cloud-vs-local)
4. [Технологический стек](#4-технологический-стек)

### Часть II — Архитектура системы
5. [Трёхпроцессная архитектура](#5-трёхпроцессная-архитектура)
6. [Путь сообщения: от микрофона до ответа](#6-путь-сообщения-от-микрофона-до-ответа)
7. [Shared State — ctx_swarm](#7-shared-state--ctx_swarm)
8. [Система прерываний (Interrupt)](#8-система-прерываний-interrupt)

### Часть III — Компоненты
9. [STT — распознавание речи](#9-stt--распознавание-речи)
10. [CoreAgent — мозг системы](#10-coreagent--мозг-системы)
11. [Streaming Orchestrator — потоковая генерация](#11-streaming-orchestrator--потоковая-генерация)
12. [Prompt Constructor — сборка промпта](#12-prompt-constructor--сборка-промпта)
13. [RAG — поиск по материалам курса](#13-rag--поиск-по-материалам-курса)
14. [Meta-Agent — фоновый анализ контекста](#14-meta-agent--фоновый-анализ-контекста)
15. [TTS — синтез речи](#15-tts--синтез-речи)
16. [Профили студентов](#16-профили-студентов)
17. [Система лекций](#17-система-лекций)
18. [Модуль юмора](#18-модуль-юмора)
19. [Инструменты (Tools)](#19-инструменты-tools)
20. [Live2D аватар](#20-live2d-аватар)

### Часть IV — Локальная LLM (LM Studio)
21. [Обзор изменений для локальной LLM](#21-обзор-изменений-для-локальной-llm)
22. [LMStudioClient — клиент локальной модели](#22-lmstudioclient--клиент-локальной-модели)
23. [ThinkingFilter — фильтрация мыслей модели](#23-thinkingfilter--фильтрация-мыслей-модели)
24. [CachedPromptConstructor — оптимизация KV-кеша](#24-cachedpromptconstructor--оптимизация-kv-кеша)
25. [Heartbeat — поддержание KV-кеша](#25-heartbeat--поддержание-kv-кеша)
26. [Маршрутизация Cloud/Local](#26-маршрутизация-cloudlocal)
27. [Протестированные модели](#27-протестированные-модели)
28. [VRAM бюджет](#28-vram-бюджет)

### Часть V — Vosk TTS и постобработка
29. [Vosk TTS — синтез русской речи](#29-vosk-tts--синтез-русской-речи)
30. [StressRNN — автоматические ударения](#30-stressrnn--автоматические-ударения)
31. [De-esser — подавление высокочастотного шума](#31-de-esser--подавление-высокочастотного-шума)

### Часть VI — Эксплуатация
32. [Структура проекта](#32-структура-проекта)
33. [Конфигурация (.env)](#33-конфигурация-env)
34. [Установка и запуск](#34-установка-и-запуск)
35. [Тайминги и производительность](#35-тайминги-и-производительность)
36. [Отладка и логирование](#36-отладка-и-логирование)
37. [Известные проблемы и решения](#37-известные-проблемы-и-решения)

---

# Часть I — Обзор проекта

## 1. Что такое AI Professor

AI Professor — голосовой ИИ-преподаватель для 8-недельного курса PersonaLab Workshop (ИТМО AI Talent Hub). Студент говорит в микрофон, система распознаёт речь, генерирует ответ через LLM, озвучивает его через TTS.

Это форк NetTyan — платформы для цифровых персонажей с Discord/Twitch ботами, поддержкой локальных LLM, prompt caching, RAG и голосом. AI Professor адаптирован под образовательный контекст: персона преподавателя, RAG по материалам курса, профили студентов, конспектирование лекций.

**Ключевые характеристики:**
- Полностью голосовой интерфейс (без текстового чата)
- Streaming LLM → студент слышит ответ через 3-5 секунд
- Прерывание в любой момент (interrupt)
- Адаптация под уровень студента (meta-agent)
- RAG по 10 лекциям курса
- Конспектирование лекций в реальном времени

## 2. Цели и задачи

### Базовая версия (Cloud API)
- Голосовой диалог через Mistral Large API (fast brain)
- Claude Opus API (smart brain) для сложных вопросов
- Claude Haiku для фонового meta-анализа
- Mistral Embeddings для RAG

### Экспериментальная версия (Local LLM)
Цели замены cloud API на локальную модель:
- **Независимость** от внешних API (Mistral, OpenAI)
- **Prompt Caching** через KV cache LM Studio (TTFT ~1-3s при прогретом кеше)
- **Нулевая стоимость** API вызовов
- **Скорость генерации** 90-100 tok/s на RTX 4070

Ограничения:
- 12 GB VRAM должны вместить LLM + Whisper STT одновременно
- Качество ответов локальной модели ниже Mistral Large
- Нет true streaming (batch-then-split из-за ThinkingFilter)

## 3. Два режима работы: Cloud vs Local

Переключение через переменную `USE_LOCAL_LLM` в `.env`:

| Аспект | Cloud (`false`) | Local (`true`) |
|--------|----------------|----------------|
| **LLM** | Mistral Large API | Gemma 4 E4B (LM Studio) |
| **Prompt формат** | LangChain Messages | OpenAI dicts (для KV cache) |
| **Prompt builder** | `prompt_constructor.py` | `cached_prompt_constructor.py` |
| **Streaming** | litellm → queue → yield | LMStudioClient → queue → yield |
| **TTFT** | ~0.8-1.5s | ~2.2s (холодный) / ~1s (прогретый кеш) |
| **Генерация** | ~40-60 tok/s | ~90-100 tok/s |
| **Thinking filter** | Не нужен | ThinkingFilter + TRIGGER_START |
| **Heartbeat** | Не нужен | Каждые 2с для сохранения KV cache |
| **Юмор** | Включён (90%) | Отключён (дублирует ответы) |
| **Meta-agent** | Claude Haiku (awstore) | Claude Haiku (awstore) — не менялся |
| **RAG embeddings** | Mistral Embeddings API | LM Studio local embeddings (bge-m3) |
| **Стоимость** | ~$0.01-0.05/запрос | Бесплатно (только электричество) |

## 4. Технологический стек

| Компонент | Технология | Версия/Модель |
|-----------|-----------|---------------|
| **Язык** | Python | 3.10+ |
| **STT** | faster-whisper | large-v3, CUDA float16 |
| **LLM (cloud)** | Mistral Large | через litellm |
| **LLM (local)** | Gemma 4 E4B | LM Studio, runtime 2.13.0 |
| **Smart brain** | Claude Opus | через awstore.cloud |
| **Meta-agent** | Claude Haiku | через awstore.cloud |
| **TTS** | Vosk TTS | vosk-model-tts-ru-0.9-multi (VITS) |
| **RAG** | FAISS | + Mistral Embeddings / bge-m3 |
| **Ударения** | StressRNN | ONNX, без TensorFlow |
| **UI** | Gradio | порт 22228 |
| **Аудио** | VoiceMeeter Banana | + soundcard, pygame |
| **Аватар** | VTube Studio | Live2D WebSocket |
| **БД** | SQLite | профили студентов + метрики |
| **ОС** | Windows 11 | RTX 4070 12GB VRAM |

---

# Часть II — Архитектура системы

## 5. Трёхпроцессная архитектура

Система работает как 3 процесса, связанные через `multiprocessing.Manager`:

```
┌─────────────────────────────────────────────────────────────┐
│                    Main Process                              │
│                                                              │
│  Gradio UI (порт 22228)                                     │
│  CoreAgent.run() → бесконечный цикл step()                  │
│    ├── construct_prompt() — RAG + profile + history          │
│    ├── stream LLM (Mistral API или LM Studio)               │
│    ├── SentenceBuffer → tts_queue                            │
│    ├── Interrupt detection                                   │
│    └── Background: meta-agent (daemon thread)                │
│                                                              │
│  Фоновые потоки:                                             │
│    ├── CtxHandler._check_changes() — мониторинг ctx_chat     │
│    ├── LMStudioClient._heartbeat_loop() — keepalive KV      │
│    └── Meta-agent thread — анализ после ответа               │
└────────────────┬──────────────────────┬──────────────────────┘
                 │ ctx_swarm            │ ctx_swarm
                 │ (Manager)            │ (Manager)
┌────────────────▼───────────┐ ┌────────▼──────────────────────┐
│      STT Process           │ │       TTS Process             │
│                            │ │                                │
│  sounddevice → mic audio   │ │  tts_queue → Vosk TTS server  │
│  VAD (RMS energy)          │ │  Prefetch (ThreadPoolExecutor) │
│  faster-whisper (CUDA)     │ │  AudioProcessor → VoiceMeeter │
│  → ctx_chat                │ │  Interrupt support             │
│  → interrupt TTS           │ │                                │
└────────────────────────────┘ └────────────────────────────────┘
```

### Почему 3 процесса, а не потоки
- **GIL**: Python GIL блокирует параллельные CPU-bound операции в потоках
- **CUDA**: faster-whisper и LLM модели требуют отдельных CUDA контекстов
- **Изоляция**: падение TTS не убивает STT и наоборот

### Связь между процессами
`multiprocessing.Manager` предоставляет proxy-объекты (list, dict, Queue, Lock), которые автоматически синхронизируются между процессами через сокеты.

## 6. Путь сообщения: от микрофона до ответа

### Полный цикл (E2E ~3-8 секунд)

```
 1. Студент говорит в микрофон (fifine)
         │ sounddevice, 16kHz mono, чанки по 100мс
 2. VAD детектирует речь (RMS > порог)
         │ буфер накапливает аудио
 3. 1.0с тишины → речь закончена
         │ pydub → WAV bytes
 4. faster-whisper транскрибирует (~1-2с)
         │ "Профессор, расскажите про RAG"
 5. STT коррекции (рак→RAG, РГ→RAG)
         │
 6. Если профессор говорит → INTERRUPT TTS
         │
 7. EventBase создаётся, добавляется в ctx_chat
         │ CtxHandler._check_changes() замечает
 8. CoreAgent.step() получает триггер
         │
 9. Проверка стоп-команд ("стоп" → "Хорошо, слушаю.")
         │
10. construct_prompt_messages():
    a. Проверка тривиальности (приветствие → без RAG)
    b. RAG поиск по материалам курса (~0.5-3с)
    c. Сборка промпта: personality + RAG + history + goal
         │
11. stream_response_sentences():
    ┌─────────────────────────────────────────────┐
    │ Cloud mode:                                  │
    │   litellm.completion(stream=True) в потоке   │
    │   → queue → yield token                      │
    │                                              │
    │ Local mode:                                  │
    │   LMStudioClient.stream_chat() → SSE парсинг │
    │   → ThinkingFilter → queue → yield token     │
    └─────────────────────────────────────────────┘
    Токены → SentenceBuffer → готовые предложения
    Каждое предложение → tts_queue
         │
12. TTS Process обрабатывает очередь:
    a. vosk_tts_sentence() → POST к Vosk серверу (~300мс)
    b. audio_processor.play_sound() → VoiceMeeter → колонки
    c. Параллельно: prefetch следующего предложения
         │
13. _save_to_history() → сохраняет ответ в ctx_chat
         │
14. Фоновый meta-agent анализирует диалог
    → обновляет профиль студента
```

## 7. Shared State — ctx_swarm

```python
ctx_swarm = {
    # История сообщений
    "ctx_chat": manager.list(),       # List[EventBase dict]
    "ctx_chat_lock": manager.Lock(),

    # Очереди
    "tts_queue": manager.list(),      # [{"text": ..., "emotion": ...}]
    "fx_queue": manager.Queue(),      # звуковые эффекты

    # Голос
    "voice": manager.dict({
        "is_speaking": False,         # профессор сейчас говорит?
        "student_speaking": False,    # студент сейчас говорит?
        "text_chunk": "",             # текущий текст
    }),

    # Окружение
    "env": manager.dict({
        "actived": True,              # система работает?
        "personality": "professor_default",
        "start_lecture": False,       # сигнал начала лекции
    }),

    # Состояние агента
    "states": manager.dict({
        "plan": "",
        "thoughts": {},
        "personality": "professor_default",
    }),
}
```

### Формат сообщения (EventBase)
```python
{
    "processing_timestamp": 1775471460219945600,  # наносекунды
    "date": "2026-04-14 12:34:56",
    "env": "voice",                   # "voice", "system", "discord"
    "user": "Student",                # или "Professor"
    "type": "chat",                   # "chat", "system", "tool"
    "msg": "Расскажите про RAG",
    "filter_results": {"acceptable": True},
    "self": True/False,               # True = ответ профессора
}
```

## 8. Система прерываний (Interrupt)

Три уровня прерывания, от быстрого к медленному:

### Уровень 1: TTS Interrupt (мгновенный)
- **Когда:** STT распознал речь студента пока профессор говорит
- **Что:** Очистка tts_queue + interrupt-сигнал `{"text": "interrupt", "emotion": "interrupt"}`
- **Результат:** Звук обрывается мгновенно
- **Файл:** `src/data_collectors/stt/mic_stt_handler.py`

### Уровень 2: LLM Stream Break (~0-10с)
- **Когда:** В streaming loop обнаружено новое сообщение в ctx_chat
- **Что:** `break` из цикла генерации, `_interrupted = True`
- **Файл:** `src/agent/core_agent.py`

### Уровень 3: Stop Commands (мгновенный, без LLM)
- **Когда:** Сообщение содержит "стоп/подождите/помолчите/секунду"
- **Что:** `TTS("Хорошо, слушаю.")` → return, LLM не вызывается
- **Файл:** `src/agent/core_agent.py`

### Post-interrupt re-entry
После прерывания агент **сразу** обрабатывает новое сообщение без ожидания триггера:
```python
self._interrupted = True
# → step() вызывается снова
# → construct_prompt_messages(wait_for_trigger=False)
# → берёт последние сообщения из ctx_chat
```

### Tracking озвученного
В историю сохраняется только то, что студент реально услышал:
```python
spoken_sentences = []
for sentence in stream:
    if interrupted: break
    spoken_sentences.append(sentence)
    _send_to_tts(sentence)

# При прерывании:
_save_to_history(spoken_text + " [прервано студентом]")
```

---

# Часть III — Компоненты

## 9. STT — распознавание речи

**Файлы:**
- `src/data_collectors/stt/mic_stt_handler.py` — захват микрофона + VAD
- `src/data_collectors/stt/stt_fasterwhisper.py` — обёртка faster-whisper
- `src/data_collectors/stt/speech_processor.py` — обработчик речи

### VAD (Voice Activity Detection)
```
SAMPLE_RATE         = 16000 Hz
BLOCK_DURATION_MS   = 100мс (чанки по 1600 семплов)
SILENCE_THRESHOLD   = 200 RMS (настраивается)
SPEECH_MIN_BLOCKS   = 4 (~0.4с минимум речи)
SILENCE_AFTER_SPEECH = 10 блоков (~1.0с тишины для завершения)
MAX_USER_VOICE_TIME = 10с (максимум записи)
MAX_PARALLEL_USERS  = 3 (параллельные пользователи)
```

**Алгоритм:**
1. Аудио читается блоками по 100мс через sounddevice
2. RMS (энергия) каждого блока сравнивается с порогом
3. RMS > порог → речь → накапливаем в буфер
4. RMS < порог в течение 1.0с → речь закончена → отправка на транскрипцию

### Faster-Whisper
```python
model = WhisperModel("large-v3", device="cuda", compute_type="float16")
# VAD filter: min_silence_duration_ms=500, speech_pad_ms=200
# Beam size: 5 (GPU) / 1 (CPU)
# Язык: "ru" (hardcoded)
```

### STT коррекции
```python
"рак" → "RAG"    # частая ошибка
"РГ"  → "RAG"
```

### VRAM
- **Idle:** ~3328 MB
- **Peak (во время транскрипции):** ~4562 MB
- **Дельта:** ~3583 MB реального потребления

## 10. CoreAgent — мозг системы

**Файл:** `src/agent/core_agent.py`
**Класс:** `CoreAgent(BaseAgent)`
**~1075 строк**

### Инициализация
```python
self.llm = get_llm_chain()                    # Mistral через litellm
self._use_local_llm = USE_LOCAL_LLM == "true" # маршрутизация
self._lm_studio_client = LMStudioClient(...)  # если local
self._cached_prompt_constructor = CachedPromptConstructor(...)  # если local
self.rag_model = RagModel()                   # FAISS RAG
self._profile_mgr = StudentProfileManager()   # SQLite
self._interrupted = False
self._meta_running = False                    # guard для meta-agent
self._greeting_sent = False                   # не повторять приветствие
```

### Главный цикл: step()

```
step() — одна итерация обработки сообщения

1. Lecture mode check
   → Если _lecture_mode=True → _lecture_step()

2. Ожидание триггера
   → construct_prompt_messages(wait_for_trigger=not _interrupted)
   → Cloud: LangChain Messages
   → Local: CachedPromptConstructor → OpenAI dicts

3. Очистка TTS очереди (новый ответ затирает старый)

4. Проверка стоп-команд
   → "стоп/подождите" → TTS("Хорошо, слушаю.") → return

5. Проверка backchannels
   → "угу/ага/понимаю" → пропуск (не отвечать)

6. Инъекция профиля студента в промпт

7. Streaming LLM
   → stream_response_sentences(messages, temperature)
   → Мониторинг interrupt (новое сообщение в ctx_chat)
   → Каждое предложение → _send_to_tts()

8. Юмор (только Cloud mode)
   → try_humor() если ≥2 предложений

9. Сохранение в историю
   → Только озвученная часть + [прервано студентом]

10. Retry на пустой ответ (до 3 попыток с 3с задержкой)

11. Meta-agent (фоновый поток)
    → _run_meta_analysis() + _update_student_profile()
    → Guard: _meta_running (только один одновременно)

12. Context trimming
    → Если ctx_chat > 200 → pop oldest
```

### Обработка текста перед TTS
```python
def _send_to_tts(text):
    # 1. Убрать теги эмоций: (neutral), (happy), (thoughtful), etc.
    # 2. Убрать legacy теги: *emotion*
    # 3. Убрать markdown: *любой текст в звёздочках*
    # 4. "Хм..." → "Хмммм." (растянуть троеточие)
    # 5. tts_queue.append({"text": ..., "emotion": "neutral"})
```

## 11. Streaming Orchestrator — потоковая генерация

**Файл:** `src/agent/streaming_orchestrator.py`
**~300 строк**

### SentenceBuffer — накопитель предложений

Собирает токены от LLM в готовые предложения для TTS:
```
Вход:  "Это " "простой " "пример." " А " "вот " "второй."
Выход: → "Это простой пример."
       → "А вот второй."
```

**Правила:**
| Правило | Описание |
|---------|----------|
| Пунктуация | Разбивать на `.!?` + пробел (НЕ после цифр: `1.`, `2.`) |
| Вопросы | `?` сбрасывает немедленно (отдельная интонация для TTS) |
| Переполнение | >20 слов без пунктуации → принудительный сброс |
| Мелкие фрагменты | <3 слов → склеить со следующим предложением |

### Маршрутизация стриминга

```python
def _stream_to_queue(messages, temperature, max_tokens, q):
    if USE_LOCAL_LLM == "true":
        # LMStudioClient.stream_chat_to_queue()
        _stream_to_queue_lm_studio(messages, temperature, max_tokens, q)
    else:
        # litellm.completion(stream=True)
        _stream_to_queue_mistral(messages, temperature, max_tokens, q)
```

### stream_fast() — raw token streaming
```python
def stream_fast(messages, temperature=0.6, max_tokens=500):
    # LLM вызов в daemon-потоке → токены в queue
    # Основной поток читает с таймаутом:
    #   10с на один токен — если LLM повис
    #   30с max total — hard cap
    # Yields: individual tokens (str)
```

### stream_response_sentences() — высокоуровневый API
```python
def stream_response_sentences(messages, temperature=0.6, max_tokens=500):
    # Yields: complete sentences (str)
    # Uses SentenceBuffer
    # Filters TRIGGER_START (local LLM only)
    # Force-flush after 8s silence
    # Returns full response text via generator
```

### Background Smart Model (Claude Opus)
Опциональный запуск Claude Opus для улучшенного ответа:
- `launch_smart_background()` — неблокирующий запуск
- `get_smart_response()` — получить ответ если готов
- Используется для dual-brain архитектуры (fast+smart)

## 12. Prompt Constructor — сборка промпта

**Файлы:**
- `src/agent/prompt_generation/prompt_constructor.py` — для Cloud mode
- `src/agent/prompt_generation/cached_prompt_constructor.py` — для Local mode

### Cloud mode: construct_prompt_messages()

```
[System] personality_template
         + PROFESSOR_GOAL + PROFESSOR_VOICE_RULES
         + RAG context (с аннотацией уверенности)
         + Student profile
         + Meta-instruction (стиль ответа)
         + TRIGGER_START instruction (если local LLM)

[User/Assistant] ...история чата (до 50 сообщений)...
                 "======= Последние сообщения START ======="
                 ...
                 "======= Последние сообщения END ======="

[User] Текущий вопрос + инструкция
```

### RAG confidence scoring
| L2 Distance | Уровень | Инструкция для LLM |
|-------------|---------|---------------------|
| < 0.8 | Высокая | "Опирайся на контекст" |
| 0.8 — 1.2 | Средняя | "Дополни своими знаниями" |
| > 1.2 | Низкая | "Полагайся на свои знания" |

### Тривиальные сообщения (RAG пропускается)
- **Exact match:** "привет", "да", "нет", "ок", "спасибо", "здравствуйте"
- **Contains:** "добрый день", "как дела", "вы меня слышите"
- **Короткие:** < 15 символов

### SmartEventWaiter — ожидание триггера
Блокирует step() до нового сообщения от студента:
- Initial delay: 5с (можно 0 если _interrupted)
- Timeout: 15с на каждую проверку
- Пропускает self=True (ответы профессора)

## 13. RAG — поиск по материалам курса

**Файл:** `src/agent/rag.py`
**Класс:** `RagModel`

### Документы
- **Источник:** `resources/RAG/course_materials/` (10 лекций: week1-4 + w1-2_full до w9-10_full)
- **Разбиение:** `CustomTripleNewLineSplitter` — тройной перенос строки как граница
- **Минимальный чанк:** 50 символов (мелкие объединяются)
- **Эмбеддинги:** Mistral Embeddings API (cloud) / bge-m3 (local через LM Studio)
- **Хранилище:** FAISS → `data/rag_vector_store/knowledge.faiss`

### Поиск
```python
explain(query) → str:
    1. Векторизация запроса
    2. similarity_search_with_score() → top-2 документа
    3. Фильтр: distance > 1.5 → "NOT FOUND"
    4. Возврат: конкатенация content двух лучших чанков
```

### Warmup при старте
Запрос "Что такое вайб?" для прогрева FAISS + embeddings API (~1.5с).

### Vocabulary extraction
`get_vocabulary()` — извлекает технические термины (Latin/ASCII + Russian CAPS) для помощи STT corrections.

## 14. Meta-Agent — фоновый анализ контекста

**Файл:** `src/agent/meta_agent.py`

### Что делает
Анализирует контекст через Claude Haiku (~200 токенов, ~0.5-1с):
- **Вход:** профиль студента + последние 5 сообщений + текущее
- **Выход:** JSON с настроением, типом запроса, обновлениями профиля

### Выходной формат
```json
{
  "mood": "спокоен|раздражён|растерян|любопытен|торопится|шутит",
  "request_type": "техпомощь|теория|приветствие|знакомство|уточнение|юмор|offtopic",
  "is_off_topic": false,
  "humor_detected": false,
  "style_instruction": "Отвечай коротко и по существу",
  "topic": "docker|rag|tts|llm|python|embeddings|prompts|general",
  "needs_analogy": false,
  "profile_updates": {
    "tech_level_delta": 0,
    "add_topic": "RAG системы",
    "add_issue": null,
    "communication_note": "нуждается в пошаговых инструкциях",
    "background_info": "ML-инженер"
  }
}
```

### Когда запускается
- **Только** после полного (не прерванного) ответа
- **Только** если предыдущий meta-agent завершился (`_meta_running` guard)
- В **фоновом daemon-потоке** (не блокирует основной step())

### extract_student_info()
Regex-парсинг из первого сообщения:
```
"Привет, я Алексей, работаю ML-инженером"
→ {"name": "Алексей", "background": "работаю ML-инженером"}
```

## 15. TTS — синтез речи

**Файлы:**
- `src/tts/simple_tts_handler.py` — оркестратор TTS-очереди
- `src/tts/vosk/vosk_tts.py` — клиент Vosk TTS
- `src/tts/audio_device.py` — управление аудио-устройствами

### Архитектура очереди
```
tts_queue: [{"text": "Первое.", "emotion": "neutral"}, ...]
                    │
    _handle_vosk_queue_stream()
                    │
    split_sentences() → ["Первое предложение.", "Второе."]
                    │
    vosk_tts_sentence() → POST /tts → audio numpy (22050 Hz)
                    │
    audio_processor.play_sound() → VoiceMeeter → колонки
```

### Prefetch — ключевая оптимизация
```
Обычный режим:              С prefetch:
  Синтез1 → Проигрыш1        Синтез1 → Проигрыш1
  Синтез2 → Проигрыш2               └→ Синтез2 → Проигрыш2
  Синтез3 → Проигрыш3                       └→ Синтез3 → Проигрыш3

Экономия: ~300-700мс на каждом переходе
```
Реализация: `ThreadPoolExecutor(max_workers=1)` — один фоновый синтез.

### Бэкенды TTS
| Бэкенд | Скорость | Качество | GPU | Примечание |
|--------|----------|---------|-----|------------|
| **Vosk** (основной) | ~200-700мс | Хорошее | CPU | 5 русских голосов, VITS |
| Piper | ~300мс | Среднее | CPU | ONNX, denis-medium |
| Fish Speech | ~3-10с | Отличное | GPU | Клонирование голоса, legacy |

### Vosk TTS клиент
- **Сервер:** отдельный процесс на порту 22232
- **Модель:** vosk-model-tts-ru-0.9-multi (VITS, 22050 Hz)
- **Голос:** speaker_id=4 (male_1, voice33)
- **Speech rate:** 1.0
- **Кеш фраз:** ~40 частых фраз в `resources/Audio/tts_cache/`

### Разбиение на предложения (TTS-level)
```python
split_sentences(text):
    1. Разбить на .!? 
    2. ? — всегда отдельно (интонация)
    3. >10 слов → разбить на запятых/союзах
    4. <3 слов → склеить со следующим
```

### Пауза между предложениями
- Внутри одного tts_queue item: 0.18с
- Между разными items: 0.35с

## 16. Профили студентов

**Файл:** `src/lecture/student_profiles.py`
**Класс:** `StudentProfileManager`
**БД:** `data/student_profiles.db` (SQLite)

### Схема базы данных

**Таблица `students`:**
```sql
id INTEGER PRIMARY KEY,
name TEXT UNIQUE,
first_seen TIMESTAMP,
last_seen TIMESTAMP,
total_interactions INTEGER DEFAULT 0,
tech_level INTEGER DEFAULT 3,       -- 1 (новичок) — 5 (эксперт)
communication_style TEXT,
topics_of_interest TEXT,            -- JSON array
known_issues TEXT,                  -- JSON array
personality_notes TEXT,
background TEXT,
topic_levels TEXT                   -- JSON dict: {"RAG": 3, "Docker": 2}
```

**Таблица `interaction_log`:**
```sql
id, student_name, timestamp, student_message,
agent_response, meta_analysis (JSON), emotion_tag
```

### Жизненный цикл профиля
1. `extract_student_info()` парсит имя/бэкграунд из "Привет, я Алексей"
2. `get_or_create_student()` создаёт или находит профиль
3. Meta-agent генерирует `profile_updates` после каждого ответа
4. `update_profile()` применяет обновления (tech_level, topics, issues)
5. `get_profile_for_prompt()` форматирует для инъекции в промпт

### Пример профиля в промпте
```
Профиль студента: Алексей. Общений: 12. Уровень: 4/5.
Интересы: RAG системы, Docker.
Проблемы: fallback голоса в Fish TTS.
Фон: ML-инженер, опыт с Python.
```

## 17. Система лекций

**Файлы:** `src/lecture/`

### LectureManager (`integration.py`)
Фасад для конспектирования:
- Фоновый поток читает JSONL из STT
- Буфер транскрипции (`transcript_buffer.py`)
- Map-reduce суммаризация через LLM (`summarizer.py`)
- Обновление RAG индекса новыми конспектами

### Lecture Delivery (`lecture_delivery.py`)
Режим чтения лекции:
1. Claude Opus генерирует план лекции (10-20 блоков)
2. Блоки с разным стилем: `casual_start`, `explain_direct`, `explain_with_analogy`, `walkthrough`, `interactive`, `summary`
3. Доставка block-by-block → SentenceBuffer → TTS
4. Пауза между блоками для вопросов студента
5. Детекция backchannels (мм-хм, да, понимаю) → продолжение
6. Детекция вопросов → Q&A mode → "Продолжаем"

### Wake Words (`wake_word.py`)
- YAML конфигурация: `resources/Customization/wake_words.yml`
- Триггеры: "Professor", "Профессор", custom фразы
- Case-insensitive

### Суммаризация (`summarizer.py`)
Map-reduce через LLM:
1. Транскрипт делится на чанки
2. Каждый чанк → LLM summarize (map)
3. Все саммари → один конспект (reduce)
4. Хранение в `resources/RAG/lecture_summaries/`
5. Автоматическое обновление FAISS индекса

## 18. Модуль юмора

**Файл:** `src/agent/humor.py`

### Параметры
```python
HUMOR_PROBABILITY = 0.90   # 90% шанс юмора
HUMOR_COOLDOWN = 0         # без кулдауна
HUMOR_MAX_WORDS = 25       # макс длина шутки
HUMOR_TEMPERATURE = 0.9    # высокая креативность
```

### 9 типов юмора (с весами)
| Тип | Вес | Описание |
|-----|-----|----------|
| understatement | 0.18 | Преуменьшение |
| confession | 0.18 | Самоирония |
| wholesome_absurd | 0.12 | Добрый абсурд |
| pedantic | 0.12 | Педантичность |
| affectionate_tech | 0.10 | Тёплое техническое |
| non_sequitur | 0.08 | Неожиданный поворот |
| rhetorical_disappointment | 0.08 | Риторическое разочарование |
| philosophical | 0.08 | Философское |
| backhanded | 0.06 | Двусмысленный комплимент |

### Алгоритм
1. `should_inject_humor()` — двойной gate: random (90%) + appropriateness
2. `select_humor_type()` — weighted selection с ограничениями
3. `generate_humor(topic, type)` — отдельный LLM вызов с few-shot examples
4. `inject_humor_into_response()` — вставка между семантическими блоками

### Статус в версии с локальной LLM
**ОТКЛЮЧЁН.** Причина: `try_humor()` переформулирует весь ответ, `replace()` не может извлечь только шутку → студент слышит ответ дважды. Отключён через `if _use_local_llm: skip` в `core_agent.py:935`.

## 19. Инструменты (Tools)

**Файлы:** `src/agent/tools/`

| Инструмент | Назначение |
|------------|-----------|
| `speak(text, emotion)` | Озвучить текст с эмоцией |
| `interrupt_voice()` | Остановить текущую речь |
| `interrupt_chat()` | Очистить TTS очередь |
| `save_user_info(user, summary)` | Сохранить заметку о студенте |
| `wait(seconds)` | Пауза (до 10с) |
| `fx(sound_name)` | Воспроизвести звуковой эффект |
| `screenshot()` | Захват экрана для vision LLM |
| `change_personality()` | Сменить персону |

В текущей streaming-архитектуре профессор не использует tool-calling напрямую. CoreAgent.step() сам управляет TTS через `_send_to_tts()`.

## 20. Live2D аватар

**Файлы:** `src/live2d/`

- `vtube_studio.py` — WebSocket клиент VTube Studio
- `vtube_settings.py` — конфигурация параметров
- `eye_rotater.py` — анимация глаз

Подключается к VTube Studio через WebSocket:
- Lip sync (синхронизация губ с речью)
- Eye tracking (направление взгляда)
- Эмоциональные выражения
- Auto-reconnect при обрыве соединения

---

# Часть IV — Локальная LLM (LM Studio)

## 21. Обзор изменений для локальной LLM

### Мотивация
Замена Mistral Large API на локальную модель для:
1. Независимости от внешних API
2. Prompt caching через KV cache (ускорение TTFT)
3. Нулевой стоимости вызовов
4. Потенциально более быстрой генерации

### Созданные файлы
| Файл | Назначение |
|------|-----------|
| `src/agent/lm_studio_client.py` | **НОВЫЙ.** Клиент LM Studio с heartbeat + ThinkingFilter |
| `src/agent/prompt_generation/cached_prompt_constructor.py` | **НОВЫЙ.** KV-cache-оптимизированные промпты |
| `docs/LM_STUDIO_SETUP.md` | **НОВЫЙ.** Гайд по настройке |
| `tests/benchmark_llm.py` | **НОВЫЙ.** A/B бенчмарк |

### Изменённые файлы
| Файл | Изменения |
|------|-----------|
| `src/agent/core_agent.py` | USE_LOCAL_LLM flag, инициализация LMStudioClient, маршрутизация prompt builder |
| `src/agent/streaming_orchestrator.py` | Маршрутизация stream: LM Studio / litellm, TRIGGER_START фильтрация |
| `src/agent/prompt_generation/prompt_constructor.py` | TRIGGER_START инструкция в PROFESSOR_GOAL |
| `.env.example` | Новые переменные LM_STUDIO_* |

### Ключевые архитектурные решения
1. **ThinkingFilter** вместо true streaming — модель генерирует thinking, нужно буферизовать
2. **TRIGGER_START** в системном промпте — модель начинает ответ словом-триггером
3. **Heartbeat** каждые 2с — LM Studio сбрасывает KV cache через ~3-5с неактивности
4. **Cached prefix** — статическая часть промпта в начале для максимального cache hit

## 22. LMStudioClient — клиент локальной модели

**Файл:** `src/agent/lm_studio_client.py`
**Класс:** `LMStudioClient`
**~370 строк**

### Архитектура
Синхронный клиент на `requests` (не aiohttp) — соответствует threading-модели Professor.

```python
class LMStudioClient:
    base_url = "http://127.0.0.1:1234/v1"
    model = "loaded-model"
    heartbeat_interval = 2.0        # keepalive ping
    max_tokens = 512
    temperature = 0.7
    reasoning_effort = "none"       # отключить thinking
    filter_thinking = True          # использовать ThinkingFilter
```

### Жизненный цикл
```python
client = LMStudioClient(...)
client.start()          # создаёт session + запускает heartbeat
# ... использование ...
client.stop()           # останавливает heartbeat, закрывает session
```

### stream_chat() — основной метод
```python
def stream_chat(messages, max_tokens=None, temperature=None, on_token=Callable):
    # 1. pause_heartbeat() — избежать конфликта слотов
    # 2. POST /v1/chat/completions (stream=True)
    #    Payload: messages, model, max_tokens, temperature,
    #             reasoning_effort="none", stream=True
    # 3. Парсинг SSE: data: {"choices": [{"delta": {"content": "..."}}]}
    # 4. ThinkingFilter.process(token) — буферизация
    # 5. ThinkingFilter.flush() — извлечение после TRIGGER_START
    # 6. КРИТИЧНО: полностью дочитать стрим (для сохранения KV cache)
    # 7. resume_heartbeat()
```

### stream_chat_to_queue() — обёртка для threading
```python
def stream_chat_to_queue(messages, queue, max_tokens=None, temperature=None):
    # Токены → queue.put(token)
    # None → сигнал окончания
    # Для совместимости с streaming_orchestrator
```

### check_health() — проверка доступности
```python
def check_health() -> {"status": "ok"|"no_model"|"error", "models": [...]}
    # GET /v1/models
```

### Singleton
```python
_client = None

def get_lm_studio_client() -> LMStudioClient:
    # Создаёт единственный экземпляр при первом вызове
    # Настраивается из env: LM_STUDIO_API_BASE, LM_STUDIO_MODEL_NAME, etc.

def shutdown_lm_studio_client():
    # Останавливает и удаляет singleton
```

## 23. ThinkingFilter — фильтрация мыслей модели

**Файл:** `src/agent/lm_studio_client.py`
**Класс:** `ThinkingFilter`

### Проблема
Reasoning-модели (Gemma 4, Qwen 3.5) генерируют внутренние "мысли" перед ответом, даже с `reasoning_effort=none`. Эти мысли попадают в `content` стрим:

```
<thinking>Мне нужно объяснить RAG простыми словами...</thinking>
TRIGGER_START RAG — это система поиска по документам...
```

### Решение: TRIGGER_START
1. Системный промпт содержит инструкцию:
   > "ОБЯЗАТЕЛЬНО: Начинай КАЖДЫЙ ответ со слова TRIGGER_START"
2. ThinkingFilter буферизует ВСЕ токены
3. При flush() извлекает текст после **последнего** вхождения TRIGGER_START
4. Почему последнего: модель иногда копирует системный промпт в thinking

### Алгоритм
```python
class ThinkingFilter:
    def process(token) -> Optional[str]:
        if enabled:
            _buffer += token     # всё в буфер
            return None          # ничего не отдаём
        else:
            return token         # passthrough

    def flush() -> Optional[str]:
        text = "".join(_buffer)
        if TRIGGER in text:
            # Берём ВСЁ после последнего TRIGGER_START
            return text.rsplit(TRIGGER, 1)[1].strip()
        else:
            # Trigger не найден — отдаём всё
            return text.strip()
```

### Последствия
- **Нет true streaming:** студент ждёт пока модель сгенерирует весь ответ
- **TTFT увеличивается:** 2.2с (prompt processing) + 1-3с (генерация + фильтрация)
- **Но просто и надёжно:** не зависит от формата thinking, работает с любой моделью

### Почему не другие подходы?
| Подход | Проблема |
|--------|---------|
| Cyrillic/Latin ratio | Курс по AI — ответы содержат латинские термины (RAG, Docker, FAISS) |
| Regex для `<thinking>` | Модели не всегда оборачивают мысли в теги |
| Streaming + partial filter | Нет надёжного способа определить конец thinking на лету |

## 24. CachedPromptConstructor — оптимизация KV-кеша

**Файл:** `src/agent/prompt_generation/cached_prompt_constructor.py`
**Класс:** `CachedPromptConstructor`
**~212 строк**

### Принцип
KV cache в LM Studio работает по **совпадению токенового префикса**. Если запрос B начинается с тех же токенов, что и запрос A — они не перевычисляются.

**Стратегия:** Всё статическое → в начало промпта (cached prefix). Всё динамическое → в конец (dynamic suffix).

```
┌──────────────────────────────────────────────┐
│ [CACHED PREFIX]                               │  Rebuild only on
│   System: personality + goal + TRIGGER_START  │  personality or
│   System: student profile                     │  profile change
│                                               │  (~2200 tokens)
├──────────────────────────────────────────────┤
│ [DYNAMIC SUFFIX]                              │  Changes every
│   User: RAG context (с confidence)            │  request
│   System: meta-instruction                    │  (~1500 tokens)
│   User/Assistant: chat history (last 10)      │
│   User: current question                      │
└──────────────────────────────────────────────┘
```

### Методы

**`build_cached_prefix(ctx_swarm, student_profile="")`**
- Инвалидируется при смене personality или student_profile
- Формат: List[Dict] (OpenAI dicts)
- Версионирование: `_prefix_version` counter

**`build_dynamic_suffix(rag_context, rag_score, chat_messages, meta_instruction)`**
- Строится заново каждый запрос
- RAG контекст с аннотацией уверенности (то же что prompt_constructor)
- Последние 10 сообщений чата

**`build_full_prompt(...)`**
- Основная точка входа для core_agent
- `cached_prefix + dynamic_suffix`
- Возвращает: `List[Dict]` готовый для LMStudioClient

### Производительность
- Без кеша: ~2200 prefix tokens перевычисляются каждый запрос
- С кешем: только ~1500 dynamic tokens
- Ожидаемое ускорение TTFT: **~1.5-2x**
- Реальное: 2.2с (холодный) → ~1с (прогретый кеш)

## 25. Heartbeat — поддержание KV-кеша

### Проблема
LM Studio (llama.cpp) сбрасывает KV cache через ~3-5 секунд неактивности (eviction). Между вопросами студента может пройти 10-60 секунд → кеш всегда холодный.

### Решение
Фоновый daemon-поток отправляет keepalive-ping каждые 2 секунды:

```python
def _heartbeat_loop(self):
    while self._heartbeat_running:
        time.sleep(self.heartbeat_interval)  # 2с
        if idle > interval:
            # Ping с тем же prefix что и последний реальный запрос
            # max_tokens=1 (минимальный ответ)
            # ОБЯЗАТЕЛЬНО: полностью прочитать response (иначе кеш не сохранится)
            self._send_ping()
```

### Ключевые детали
- **Тот же prefix:** ping использует тот же набор сообщений, что и последний реальный запрос → максимальный cache hit
- **max_tokens=1:** минимальная генерация
- **Полное чтение response:** llama.cpp сохраняет KV cache только после полного завершения запроса
- **GPU overhead:** ~6% (0.18с на ping каждые 2-3с)
- **Пауза во время реальных запросов:** `pause_heartbeat()` / `resume_heartbeat()` избегают конфликта слотов

### Без heartbeat
- TTFT: ~3-5с (холодный старт каждый раз)
- С heartbeat: ~1с (кеш прогрет)

## 26. Маршрутизация Cloud/Local

### Точки маршрутизации

**1. core_agent.py — инициализация**
```python
if USE_LOCAL_LLM == "true":
    self._lm_studio_client = LMStudioClient(...)
    self._lm_studio_client.start()
    self._cached_prompt_constructor = CachedPromptConstructor(...)
```

**2. core_agent.py — step() — построение промпта**
```python
if self._use_local_llm:
    messages = self._cached_prompt_constructor.build_full_prompt(...)
    # → List[Dict] (OpenAI format)
else:
    messages = construct_prompt_messages(..., output_format="langchain")
    # → List[BaseMessage] (LangChain format)
```

**3. streaming_orchestrator.py — стриминг**
```python
def _stream_to_queue(messages, temperature, max_tokens, q):
    if USE_LOCAL_LLM == "true":
        client.stream_chat_to_queue(messages, q, ...)
    else:
        litellm.completion(stream=True, ...)
```

**4. streaming_orchestrator.py — TRIGGER_START фильтрация**
```python
for token in stream_fast(messages):
    sentences = buffer.add(token)
    for sentence in sentences:
        if _trigger and _trigger in sentence:
            sentence = sentence.split(_trigger, 1)[-1].strip()
        yield sentence
```

**5. core_agent.py — юмор**
```python
if not self._use_local_llm and len(spoken_sentences) >= 2:
    humor = try_humor(...)
```

## 27. Протестированные модели

| Модель | Результат | TTFT | tok/s | Примечание |
|--------|----------|------|-------|------------|
| **Gemma 4 E4B** | **РАБОТАЕТ** | ~2.2с base | 90-100 | reasoning_effort=none + TRIGGER_START |
| Qwen 3.5 9B (все варианты) | НЕ ПОДХОДИТ | 6-14с | — | Thinking overhead убивает latency |
| Mistral 7B Instruct | УДАЛЕНА | — | — | Очень плохое качество русского |

### Gemma 4 E4B — текущая модель
- **Runtime:** LM Studio 2.13.0 (CUDA 12)
- **Context:** 4096 токенов
- **VRAM:** ~5.9 GB
- **Ключевая настройка:** `reasoning_effort=none` отключает thinking (0 reasoning tokens)
- **С TRIGGER_START:** чистый вывод без leaked thinking

### Почему не Qwen 3.5 9B?
Все варианты (Q4_K_M, Q5_K_M, Q6_K) имеют thinking overhead 6-14 секунд, что неприемлемо для голосового ассистента. Даже с `reasoning_effort=none` модель генерирует thinking блоки.

## 28. VRAM бюджет

**Оборудование:** NVIDIA RTX 4070, 12 GB VRAM

Измерено 2026-04-13 под реальной нагрузкой (не просто загрузка модели):

| Компонент | Idle | Peak (под нагрузкой) |
|-----------|------|---------------------|
| System baseline | 979 MB | 979 MB |
| Whisper large-v3 float16 | 3328 MB | **4562 MB** |
| Gemma 4 E4B (ctx 4096) | 5270 MB | ~6000 MB |
| **Комбинированный peak** | | **~10.5 GB** |
| **Запас** | | **~1.7 GB** |

### Правила выбора модели
- LLM VRAM + 4.6 GB (Whisper peak) < 12 GB
- Всегда мерить peak под реальной нагрузкой, а не при загрузке
- Whisper delta: ~3583 MB (peak - baseline)

---

# Часть V — Vosk TTS и постобработка

## 29. Vosk TTS — синтез русской речи

**Сервер:** отдельный проект hVostic TTS на порту 22232
**Модель:** vosk-model-tts-ru-0.9-multi (VITS)
**Sample rate:** 22050 Hz
**Голос:** speaker_id=4 (male_1 / voice33)

### Параметры голоса
```python
noise_level = 0.667          # вариативность тона
duration_noise_level = 1.0   # вариативность длительности
speech_rate = 1.0            # скорость речи
```

### Stress marks (ударения)
Vosk TTS поддерживает ударения через `+` перед ударной гласной:
```
з+амок  → замок (крепость)
зам+ок  → замок (запорное устройство)
м+ука   → мука (страдание)
мук+а   → мука (для выпечки)
```

**Механизм:**
- `+` перед гласной → слово обходит встроенный словарь → идёт через `convert()` в `g2p.py`
- Без `+` → словарь выбирает ударение по умолчанию (часто неправильно для омографов)
- Unicode U+0301 (combining acute) **вызывает краш G2P** → только `+`

### Отвергнутые альтернативы
- **Silero TTS v4_ru:** плохое качество голоса, неправильные ударения даже с marks
- **Piper TTS:** среднее качество, нет ударений, ONNX CPU
- **Fish Speech:** отличное качество + клонирование, но в 20-40x медленнее

## 30. StressRNN — автоматические ударения

**Файл:** `N:/exam/hVostic TTS/text_utils.py` (функция `add_stress_marks()`)
**Библиотека:** StressRNN (ONNX, без TensorFlow)
**Установка:** `pip install git+https://github.com/dbklim/StressRNN.git`

### Зачем
Vosk TTS без ударений часто ставит неправильное ударение. StressRNN автоматически расставляет ударения перед синтезом.

### Pipeline
```
Текст
  → StressRNN: "замОк" → "замо+к" (V+ — после гласной)
  → _stress_after_to_before(): "замо+к" → "зам+ок" (+V — перед гласной)
  → Vosk G2P: правильное произношение
```

### Интеграция в TTS pipeline
```
finalize_punctuation()     → нормализация пунктуации
add_stress_marks()         → StressRNN + V+→+V конвертер
transliterate_latin()      → транслитерация латиницы
→ Vosk synth_audio()
```

### Параметры
- `accuracy_threshold = 0.55` — баланс покрытия vs ложных срабатываний
- Lazy-load модели при первом вызове (~0.5с), далее быстро
- **russtress (альтернатива)** — СЛОМАНА с TF 2.21, не использовать

## 31. De-esser — подавление высокочастотного шума

**Файл:** `N:/exam/hVostic TTS/server.py` (функция `_deess()`)

### Проблема
VITS-модель Vosk TTS генерирует высокочастотный "электронный" buzz. Low-pass фильтры (6-7.5kHz) мутят голос ("из подушки").

### Решение: Band-split de-esser
```python
def _deess(audio, sr=22050):
    # 1. Butterworth 4th-order band split at 4kHz
    # 2. Low band (< 4kHz) → проходит без изменений
    # 3. High band (> 4kHz):
    #    → если RMS > -20dB threshold → сжатие на 0.4x
    #    → если ниже → без изменений
    # 4. Результат = low_band + compressed_high_band
```

### Параметры
| Параметр | Значение | Описание |
|----------|---------|----------|
| Частота разделения | 4000 Hz | Граница low/high band |
| Порядок фильтра | 4 (Butterworth) | Крутизна среза |
| Threshold | -20 dB | Порог срабатывания компрессии |
| Ratio | 0.4x | Степень сжатия harsh peaks |

### Результат
- Убирает "электронный" buzz выше 4kHz
- Сохраняет чистоту голоса (low band не тронут)
- Применяется после `synth_audio()`, перед WAV encoding

---

# Часть VI — Эксплуатация

## 32. Структура проекта

```
N:/exam/LocalLLMExperement/AI-Professor/
│
├── src/
│   ├── main.py                          # Точка входа: Gradio UI + 3 процесса
│   │
│   ├── agent/                           # Ядро агента
│   │   ├── core_agent.py                # CoreAgent: step() loop, interrupt, streaming
│   │   ├── base_agent.py                # Абстрактный базовый класс
│   │   ├── streaming_orchestrator.py    # LLM streaming: SentenceBuffer, маршрутизация
│   │   ├── orchestrator.py              # Dual-brain: fast (Mistral) + smart (Claude)
│   │   ├── meta_agent.py               # Фоновый анализ контекста (Haiku)
│   │   ├── rag.py                       # FAISS RAG по материалам курса
│   │   ├── humor.py                     # Модуль юмора (9 типов, 90%)
│   │   ├── lm_studio_client.py          # [NEW] LM Studio клиент + heartbeat + ThinkingFilter
│   │   │
│   │   ├── prompt_generation/
│   │   │   ├── prompt_constructor.py    # Сборка промпта (Cloud mode)
│   │   │   ├── cached_prompt_constructor.py  # [NEW] KV-cache оптимизация (Local mode)
│   │   │   ├── idea_suggestor.py        # Генерация идей для разнообразия
│   │   │   └── base_parts.py            # Переиспользуемые части промптов
│   │   │
│   │   ├── llm_clients/
│   │   │   ├── lc_clients.py            # LangChain integration, get_llm_chain()
│   │   │   └── llm_wrappers.py          # Обёртки для моделей
│   │   │
│   │   └── tools/
│   │       ├── base_tools.py            # speak(), interrupt, save_user_info
│   │       ├── control_tools.py         # personality, directive
│   │       ├── dialogue_tools.py        # dialogue_step, like/dislike
│   │       ├── state_tools.py           # plan, focus, pattern
│   │       ├── status_tools.py          # get_*_status()
│   │       ├── vision_tools.py          # screenshot
│   │       ├── tool_executor.py         # Диспетчер вызовов
│   │       └── tools.py                 # Реестр инструментов
│   │
│   ├── lecture/
│   │   ├── integration.py               # LectureManager фасад
│   │   ├── lecture_delivery.py          # Доставка лекций по блокам
│   │   ├── student_profiles.py          # SQLite профили студентов
│   │   ├── transcript_buffer.py         # Буфер транскрипции
│   │   ├── summarizer.py               # Map-reduce суммаризация
│   │   ├── wake_word.py                 # Детекция обращений
│   │   └── process_recording.py         # Пост-обработка аудио
│   │
│   ├── data_collectors/stt/
│   │   ├── mic_stt_handler.py           # Захват микрофона + VAD
│   │   ├── stt_fasterwhisper.py         # faster-whisper обёртка
│   │   ├── speech_processor.py          # Обработчик речи (multiprocessing)
│   │   └── stt_utils.py                 # Аудио утилиты
│   │
│   ├── tts/
│   │   ├── simple_tts_handler.py        # Оркестратор TTS очереди + prefetch
│   │   ├── audio_device.py              # AudioProcessor: playback + interrupt
│   │   ├── vosk/
│   │   │   └── vosk_tts.py              # Vosk TTS клиент + split_sentences
│   │   ├── piper/
│   │   │   └── piper_tts.py             # Piper TTS (CPU ONNX)
│   │   └── fish/
│   │       └── fish_gr.py               # Fish Speech (GPU, legacy)
│   │
│   ├── data_flow/
│   │   ├── ctx_handler.py               # CtxHandler: ctx_chat management
│   │   ├── ctx_host.py                  # Multiprocessing locks
│   │   ├── database.py                  # SQLite helpers
│   │   └── filter_client.py             # Content safety filter
│   │
│   ├── data_schema/
│   │   ├── chat_structures.py           # EventBase, CtxEventType, CtxEnvType
│   │   ├── ctx_structures.py            # CtxSwarmType, Emotion, AudioFeedEntry
│   │   ├── tool_structures.py           # ToolRecord, ToolCommandFormats
│   │   ├── structure_templates.py       # CTX_SWARM_EMPTY, path constants
│   │   └── event_convert.py             # Type conversions
│   │
│   ├── live2d/
│   │   ├── vtube_studio.py              # VTube Studio WebSocket
│   │   ├── vtube_settings.py            # Параметры аватара
│   │   └── eye_rotater.py               # Анимация глаз
│   │
│   ├── metrics/
│   │   └── logger.py                    # SQLite метрики: latency, interactions
│   │
│   ├── config_schema/
│   │   ├── general.py                   # get_name(), get_secret(), is_dev_nick()
│   │   └── constants.py                 # Глобальные константы
│   │
│   └── utils/
│       ├── format_helper.py             # format_events_for_rag(), format_events_with_roles()
│       ├── prompt_helper.py             # YAML loading, template substitution
│       ├── audio_utils.py               # Аудио конвертация, VAD helpers
│       ├── patterns.py                  # BACKCHANNEL_PATTERNS
│       ├── string_helper.py             # Emoji detection, Cyrillic/Latin
│       ├── voicemeeter_control.py       # VoiceMeeter Banana integration
│       ├── vision_helper.py             # MSS screenshot
│       ├── time_helper.py               # Time utilities
│       └── debug.py                     # ANSI colors, timing
│
├── resources/
│   ├── Prompts/
│   │   └── personalities_professor.yml  # Персона преподавателя (5 вариантов)
│   ├── RAG/
│   │   ├── course_materials/            # 10 лекций курса
│   │   └── lecture_summaries/           # Автоконспекты лекций
│   ├── Audio/tts_cache/                 # ~40 pre-synthesized фраз
│   └── Customization/
│       └── wake_words.yml               # Trigger phrases
│
├── data/
│   ├── student_profiles.db              # SQLite профили студентов
│   ├── rag_vector_store/                # FAISS index (автосоздание)
│   ├── metrics.db                       # SQLite метрики
│   └── lecture_notes/                   # JSONL логи + конспекты
│
├── tests/
│   └── benchmark_llm.py                 # [NEW] A/B бенчмарк LLM
│
├── docs/
│   ├── PROJECT_DOCUMENTATION.md         # Эта документация
│   ├── architecture.md                  # Технический гайд (21 глава)
│   ├── LM_STUDIO_SETUP.md              # Настройка LM Studio
│   └── help/                            # Пользовательская документация
│
├── .env.example                         # Шаблон конфигурации
├── pyproject.toml                       # Зависимости и метаданные
├── CLAUDE.md                            # Правила разработки
├── README.md                            # Краткий README
└── PROJECT_STATE.md                     # Чекпоинт состояния (2026-04-02)
```

## 33. Конфигурация (.env)

### Идентичность агента
```env
SELF_NAME="Professor"
BOT_NICKNAMES="Professor,Профессор,профессор,Док,док"
```

### LLM — Cloud mode
```env
USE_LOCAL_LLM="false"
CORE_LLM_MODEL_NAME="mistral/mistral-large-latest"
MISTRAL_API_KEY="..."

# Smart brain (Claude Opus)
SMART_LLM_MODEL_NAME="openai/claude-opus-4.6"
SMART_LLM_API_BASE="https://api.awstore.cloud/v1"
OPENAI_API_KEY="sk-aw-..."
```

### LLM — Local mode (LM Studio)
```env
USE_LOCAL_LLM="true"
LM_STUDIO_API_BASE="http://localhost:22227/v1"
LM_STUDIO_MODEL_NAME="google/gemma-4-e4b"
LM_STUDIO_HEARTBEAT_INTERVAL="2.0"
LM_STUDIO_REASONING_EFFORT="none"
LM_STUDIO_FILTER_THINKING="true"
```

### STT (распознавание речи)
```env
FASTER_WHISPER_MODEL_NAME="large-v3"
STT_COMPUTE_DEVICE="cuda"
STT_COMPUTE_TYPE="float16"
AUDIO_MODE="local"                    # "local" или "meeting"
SOUND_DEVICE_IN="fifine"
```

### TTS (синтез речи)
```env
TTS_BACKEND="vosk"
VOSK_TTS_URL="http://localhost:22232"
VOSK_SPEAKER_ID="4"
VOSK_SPEECH_RATE="1.0"
SOUND_DEVICE_OUT="Voicemeeter Input (VB-Audio Voicemeeter VAIO)"
SOUND_DEVICE_SR=48000
```

### RAG / Embeddings
```env
EMBEDDINGS_MODEL="text-embedding-user-bge-m3"
EMBEDDINGS_API_BASE="http://localhost:22227/v1"
EMBEDDINGS_API_KEY="sk-1234"
```

### Лекции
```env
LECTURE_WEEK=1
TRANSCRIPTS_DIR="data/transcripts"
SUMMARIES_DIR="resources/RAG/lecture_summaries"
WAKE_WORDS_CONFIG="resources/Customization/wake_words.yml"
```

### Метрики и UI
```env
METRICS_DB_PATH="data/metrics.db"
GRADIO_SERVER_PORT=22228
GRADIO_SERVER_NAME="0.0.0.0"
```

## 34. Установка и запуск

### Предварительные требования
- Python 3.10+
- NVIDIA GPU с CUDA (для faster-whisper)
- Windows 11 (VoiceMeeter, sounddevice)
- VoiceMeeter Banana (для audio routing в Zoom)

### Установка
```bash
# 1. Клонировать/скопировать проект
cd N:/exam/LocalLLMExperement/AI-Professor

# 2. Создать .env
cp .env.example .env
# Заполнить API ключи и настройки аудио

# 3. Установить зависимости
pip install -e .
pip install -e ".[stt]"        # faster-whisper
pip install -e ".[simpletts]"  # Vosk TTS
pip install -e ".[gpu]"        # onnxruntime-gpu
```

### Запуск (Cloud mode)
```bash
# 1. Запустить Vosk TTS сервер (отдельный проект)
cd N:/exam/hVostic\ TTS && python server.py

# 2. Запустить Professor
cd N:/exam/LocalLLMExperement/AI-Professor
PYTHONPATH=src python src/main.py --offline --no-filter
```

### Запуск (Local LLM mode)
```bash
# 1. Запустить Vosk TTS сервер
cd N:/exam/hVostic\ TTS && python server.py

# 2. Запустить LM Studio
# → Загрузить google/gemma-4-e4b
# → GPU Offload: ВСЕ слои на GPU
# → Context Length: 4096
# → Запустить API сервер (порт 22227)

# 3. Проверить LM Studio
curl http://localhost:22227/v1/models

# 4. Запустить Professor
cd N:/exam/LocalLLMExperement/AI-Professor
USE_LOCAL_LLM=true PYTHONPATH=src python src/main.py --offline --no-filter

# 5. Бенчмарк (опционально)
PYTHONPATH=src python tests/benchmark_llm.py
```

### Остановка и cleanup
```bash
# 1. Остановить Professor (Ctrl+C в терминале)

# 2. Убить python-процессы
taskkill /f /im python.exe

# 3. Выгрузить модели LM Studio
"C:/Users/Whiter/.lmstudio/bin/lms.exe" unload --all

# 4. Остановить LM Studio сервер
"C:/Users/Whiter/.lmstudio/bin/lms.exe" server stop

# 5. Проверить VRAM
nvidia-smi
```

## 35. Тайминги и производительность

### Cloud mode (Mistral Large API)

| Операция | Задержка |
|----------|---------|
| VAD (детекция речи) | ~100мс |
| Тишина до обрезки | ~1.0с |
| STT (3с аудио) | ~1-2с |
| RAG поиск | ~0.5-1.0с |
| LLM первый токен | ~0.8-1.5с |
| LLM первое предложение | ~1.0-2.0с |
| TTS синтез (Vosk, 1 предл.) | ~0.2-0.7с |
| TTS prefetch gap | ~0мс |
| Meta-agent (Haiku) | ~0.5-1.0с (фон) |
| **E2E: речь → первый звук** | **~3-5с** |

### Local mode (Gemma 4 E4B, LM Studio)

| Операция | Задержка |
|----------|---------|
| VAD + STT | ~2-3с (не менялось) |
| RAG поиск (local embeddings) | ~0.3-0.5с |
| Prompt processing (холодный) | ~2.2с |
| Prompt processing (прогретый кеш) | ~0.5-1.0с |
| Генерация (90-100 tok/s) | ~1-3с |
| ThinkingFilter overhead | ~0с (буферизация в памяти) |
| TTS синтез (Vosk) | ~0.2-0.7с |
| **E2E: речь → первый звук (холодный)** | **~5-8с** |
| **E2E: речь → первый звук (прогретый)** | **~3-5с** |

### Сравнение
| Метрика | Cloud | Local (cold) | Local (warm) |
|---------|-------|-------------|-------------|
| TTFT | 0.8-1.5с | 2.2с | 0.5-1.0с |
| Генерация | ~40-60 tok/s | 90-100 tok/s | 90-100 tok/s |
| First sentence | 1.0-2.0с | 3-5с | 1.5-3с |
| Full E2E | 3-5с | 5-8с | 3-5с |
| Стоимость | ~$0.01-0.05 | $0 | $0 |
| True streaming | Да | Нет (batch) | Нет (batch) |

## 36. Отладка и логирование

### Ключевые логи
```
[MIC-STT] Speech started (RMS=...)       — VAD поймал звук
[MIC-STT] >>> текст                       — STT результат
[AGENT] Triggered by event: ...           — агент получил триггер
[AGENT] Skipping RAG for trivial          — RAG пропущен (приветствие)
[STREAM] Calling mistral/...              — Cloud LLM вызов
[LM-STUDIO] Streaming started             — Local LLM вызов
[LM-STUDIO] Heartbeat ping               — KV cache keepalive
[LM-STUDIO] ThinkingFilter: extracted     — Мысли отфильтрованы
[AGENT] sentence #N (Xms): 'текст'       — Предложение сгенерировано
[STREAM] Stream finished normally         — LLM стрим закончен
[STREAM] Timeout: no tokens for 10s       — LLM завис, восстановление
[AGENT] Student interrupted               — Студент перебил
[AGENT] Stop command detected             — Стоп-команда
[META-AGENT] {...}                        — Результат meta-анализа
[TTS] #N audio: Xs | 'текст'             — Предложение озвучено
[PROFILE] Updated: Алексей (tech=4)       — Профиль обновлён
```

### Полезные команды диагностики
```bash
# VRAM мониторинг
nvidia-smi -l 2

# Статус LM Studio
"C:/Users/Whiter/.lmstudio/bin/lms.exe" status
"C:/Users/Whiter/.lmstudio/bin/lms.exe" ps

# Тест LM Studio API
curl http://localhost:22227/v1/models
curl -X POST http://localhost:22227/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"loaded-model","messages":[{"role":"user","content":"Привет"}],"max_tokens":50}'

# Тест Vosk TTS
curl -X POST http://localhost:22232/tts -d '{"text":"Привет, мир"}'
```

## 37. Известные проблемы и решения

### Общие
| Проблема | Причина | Решение |
|----------|---------|---------|
| Нет ответа после триггера | LLM API завис | Подождать 10с (timeout), проверить API |
| STT не ловит речь | RMS порог высок | Проверить SILENCE_THRESHOLD, уровень микрофона |
| Профессор не замолкает | Стоп-слово не в списке | Добавить в `_stop_words` в core_agent.py |
| RAG возвращает мусор | Старый FAISS индекс | Удалить `data/rag_vector_store/`, перезапустить |
| Meta-agent ломает стрим | Параллельные litellm | `_meta_running` guard (уже есть) |
| Задержка между предложениями | Prefetch не работает | Проверить ThreadPoolExecutor в TTS |
| "рак" вместо "RAG" | STT ошибка | Добавить в `_STT_FIXES` в mic_stt_handler.py |

### Специфичные для Local LLM
| Проблема | Причина | Решение |
|----------|---------|---------|
| TTFT > 3с при тёплом кеше | GPU Offload не на максимуме | Все слои на GPU в LM Studio |
| 0 tokens received | Модель не загружена | `lms ps`, проверить сервер |
| Connection refused | Сервер не запущен | `lms server start` |
| Out of VRAM | Слишком большой контекст | Уменьшить context-length или модель |
| Leaked thinking в ответе | ThinkingFilter не сработал | Проверить TRIGGER_START в системном промпте |
| KV cache холодный | Heartbeat не работает | Проверить LM_STUDIO_HEARTBEAT_INTERVAL |
| Юмор дублирует ответ | humor.py несовместим с local LLM | Должен быть отключён (core_agent.py:935) |
| UTF-8 артефакты | Кодировка response | `resp.encoding = "utf-8"` перед iter_lines |

### Специфичные для Vosk TTS
| Проблема | Причина | Решение |
|----------|---------|---------|
| Высокочастотный buzz | VITS артефакт | De-esser в server.py (_deess) |
| Неправильные ударения | Нет stress marks | StressRNN в text_utils.py |
| Голос "из подушки" | Low-pass фильтр | Использовать de-esser вместо low-pass |
| Crash на Unicode ударениях | U+0301 ломает G2P | Только `+` перед гласной |

### Эксперименты, которые НЕ дали результатов
- **Punctuation hack** (. → , для не-последних предложений) — не улучшил просодию
- **noise_level tuning** — не решил скачки просодии между чанками
- **Корневая проблема:** каждый вызов `synth_audio()` независим → просодия скачет между предложениями

---

## Приложение A: Промпт профессора (ключевые правила)

**Файл:** `resources/Prompts/personalities_professor.yml`
**Персона:** `professor_default`

### Роль
ИИ-ассистент преподавателя курса по созданию цифровых персонажей (PersonaLab Workshop). Мужчина, мужской род.

### Голосовые правила
- Говорит как опытный старший коллега
- Варьирует длину: 1 предложение → 3-4 предложения
- Не повторяет структуру
- Не заканчивает вопросом (кроме знакомства)
- Не произносит "Понятно?", "Отличный вопрос"

### Знакомство
- Если студент неизвестен → попросить представиться (один раз)
- Если знаком → сразу к делу, без повторного приветствия

### Адаптация
- Программист → код, архитектура
- Дизайнер → визуальные аналогии
- Новичок → просто, пошагово
- Продвинутый → технично, детально

### Аналогии
Только когда концепция абстрактная И студент явно просит проще

### Юмор
Не шутит сам. Реагирует тепло на шутки студента. Стиль: британский deadpan.

### Остановка
"Стоп/подождите" → "Хорошо." и молчать. Без резюме, без вопросов.

### Источники знаний
1. RAG (primary) → собственные знания (с дисклеймером) → перенаправление к курсу

### Теги эмоций
В конце каждой реплики: `(neutral)` `(happy)` `(thoughtful)` `(encouraging)`. Не произносятся вслух — только для управления TTS.

### TRIGGER_START (только Local LLM mode)
```
ОБЯЗАТЕЛЬНО: Начинай КАЖДЫЙ ответ со слова TRIGGER_START.
Всё что перед этим словом будет отброшено.
```

---

## Приложение B: Зависимости (pyproject.toml)

### Core
```
gradio~=5.49.1
langchain-community~=0.3.31
langchain-litellm~=0.3.0
mistralai~=1.9.11
faiss-cpu~=1.12.0
python-dotenv~=1.1.1
soundcard~=0.4.5
pygame~=2.6.1
```

### Optional groups
```
[stt]     faster-whisper~=1.2.0
[simpletts] vosk-tts~=0.3.61, edge-tts~=6.1.9
[gpu]     onnxruntime-gpu~=1.23.2
```

---

## Приложение C: Диаграмма потоков данных

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              CoreAgent.step()                            │
└────────────────────────┬────────────────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
   LM Studio Path   Mistral Path    Lecture Mode
        │                │                │
        ▼                ▼                │
CachedPrompt      construct_prompt       │
Constructor        _messages()           │
    │                    │                │
    │         ┌──────────┤                │
    │         ▼          ▼                │
    │      RAG lookup  Chat history       │
    │                                     │
    ▼                                     ▼
[messages: List[Dict]]         [messages: List[BaseMessage]]
    │                                     │
    ├─────────────────────────────────────┤
    │                                     │
    ▼                                     ▼
 LMStudioClient                    litellm.completion()
   stream_chat()                     stream=True
       │                                  │
       ▼                                  │
 ThinkingFilter                           │
   (buffer all, flush after TRIGGER)      │
       │                                  │
       ├──────────────────────────────────┤
       │                                  │
       ▼                                  ▼
┌──────────────────────────────────────────────────┐
│         SentenceBuffer.add(token)                 │
│  Правила: .!? flush, 20-word overflow, <3 merge  │
└────────────┬─────────────────────────────────────┘
             │
             ▼
    _send_to_tts(sentence)
      → strip emotion tags
      → strip markdown
      → tts_queue.append()
             │
    ┌────────┴─────────────────────────┐
    │                                  │
    ▼                                  ▼
  Save to History              Interrupt Monitor
  (ctx_handler)                - student_speaking?
       │                       - new ctx_chat msg?
       │                       - → break stream
       ▼
 Background Meta-Agent
  → analyze_context()
  → update_student_profile()
  → log_interaction()
```

---

*Документация создана 2026-04-14. Версия: LocalLLMExperement.*
*Проект: AI Professor / PersonaLab Workshop / ИТМО AI Talent Hub.*
