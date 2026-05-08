# AI Professor — Полный технический гайд

## Оглавление

1. [Обзор системы](#1-обзор-системы)
2. [Архитектура: 3 процесса](#2-архитектура-3-процесса)
3. [Путь сообщения: от микрофона до ответа](#3-путь-сообщения-от-микрофона-до-ответа)
4. [Процесс STT (распознавание речи)](#4-процесс-stt)
5. [CoreAgent — мозг системы](#5-coreagent--мозг-системы)
6. [Streaming Orchestrator — потоковая генерация](#6-streaming-orchestrator)
7. [Prompt Constructor — сборка промпта](#7-prompt-constructor)
8. [RAG — поиск по материалам курса](#8-rag)
9. [Meta-Agent — анализ контекста](#9-meta-agent)
10. [Процесс TTS (синтез речи)](#10-процесс-tts)
11. [Система прерываний (Interrupt)](#11-система-прерываний)
12. [Профили студентов](#12-профили-студентов)
13. [Система инструментов (Tools)](#13-система-инструментов)
14. [Shared State — ctx_swarm](#14-shared-state--ctx_swarm)
15. [CtxHandler — управление сообщениями](#15-ctxhandler)
16. [Конфигурация (.env)](#16-конфигурация)
17. [Промпт профессора](#17-промпт-профессора)
18. [Форматирование истории для LLM](#18-форматирование-истории)
19. [Запуск системы (main.py)](#19-запуск-системы)
20. [Тайминги и производительность](#20-тайминги)
21. [Известные проблемы и отладка](#21-отладка)

---

## 1. Обзор системы

AI Professor — голосовой ИИ-преподаватель для курса PersonaLab Workshop (ИТМО).
Студент говорит в микрофон -> система распознает речь -> генерирует ответ -> озвучивает.

**Технологии:**
- **STT**: faster-whisper (large-v3, CUDA)
- **LLM**: Mistral Large (streaming через litellm)
- **TTS**: Vosk-TTS (CPU, русский, 5 голосов)
- **RAG**: FAISS + Mistral Embeddings
- **Meta-анализ**: Claude Haiku (через awstore.cloud)
- **UI**: Gradio (порт 22228)

**Принципиальная схема:**
```
Микрофон -> [STT Process] -> ctx_chat -> [CoreAgent] -> tts_queue -> [TTS Process] -> Колонки
                                            |                            |
                                       RAG + промпт                Vosk синтез
                                       Meta-анализ                Prefetch озвучки
```

---

## 2. Архитектура: 3 процесса

Система работает на `multiprocessing.Manager` — общее состояние между процессами.

### Процесс 1: Main (Gradio + CoreAgent)
- Gradio UI на порту 22228
- CoreAgent.run() — бесконечный цикл step()
- Фоновые потоки: meta-agent, CtxHandler monitor

### Процесс 2: STT (mic_stt_handler)
- Слушает микрофон через sounddevice
- VAD (Voice Activity Detection) на основе RMS энергии
- faster-whisper транскрибирует -> добавляет в ctx_chat

### Процесс 3: TTS (simple_tts_handler)
- Читает tts_queue
- Синтезирует через Vosk-TTS сервер
- Проигрывает через soundcard/VoiceMeeter
- Prefetch: следующее предложение синтезируется пока текущее играет

### Связь между процессами
```python
ctx_swarm = {
    "ctx_chat": manager.list(),     # история сообщений
    "tts_queue": manager.list(),    # очередь на озвучку
    "fx_queue": manager.Queue(),    # звуковые эффекты
    "voice": manager.dict(),        # состояние голоса (is_speaking, etc.)
    "env": manager.dict(),          # глобальные настройки
    "states": manager.dict(),       # состояние мышления
    ...
}
```

---

## 3. Путь сообщения: от микрофона до ответа

### Полный цикл (E2E ~3-8 секунд):

```
 1. Студент говорит в микрофон
         | (sounddevice, 16kHz, mono)
 2. VAD детектирует речь (RMS > 200)
         | (буфер накапливает аудио)
 3. 1.0с тишины -> речь закончена
         | (pydub -> WAV bytes)
 4. faster-whisper транскрибирует (~1-2с)
         | "Профессор, расскажите про RAG"
 5. STT коррекции (рак->RAG, РГ->RAG)
         |
 6. Если профессор говорит -> INTERRUPT TTS
         |
 7. EventBase создается, добавляется в ctx_chat
         | (_check_changes поток замечает)
 8. CoreAgent.step() получает триггер
         |
 9. Проверка стоп-команд ("стоп"->"Хорошо, слушаю.")
         |
10. construct_prompt_messages():
    a. Проверка тривиальности (приветствие -> без RAG)
    b. RAG поиск по материалам курса (~0.5-3с)
    c. Сборка промпта: personality + RAG + history + goal
         |
11. stream_response_sentences() через Mistral:
    a. litellm.completion(stream=True) в отдельном потоке
    b. Токены -> SentenceBuffer -> предложения
    c. Каждое предложение -> tts_queue
         |
12. TTS Process обрабатывает очередь:
    a. vosk_tts_sentence() -> POST к Vosk серверу (~300мс)
    b. audio_processor.play_sound() -> VoiceMeeter -> колонки
    c. Параллельно: prefetch следующего предложения
         |
13. _save_to_history() -> сохраняет ответ в ctx_chat
         |
14. Фоновый meta-agent анализирует диалог
    -> обновляет профиль студента
```

---

## 4. Процесс STT

**Файл:** `src/data_collectors/stt/mic_stt_handler.py`

### VAD (Voice Activity Detection)
```
Параметры:
  SAMPLE_RATE = 16000 Hz
  BLOCK_DURATION_MS = 100мс (чанки по 1600 семплов)
  SILENCE_THRESHOLD = 200 RMS
  SPEECH_MIN_BLOCKS = 4 (~0.4с минимум речи)
  SILENCE_AFTER_SPEECH_BLOCKS = 10 (~1.0с тишины для завершения)
```

**Алгоритм:**
1. Читаем аудио блоками по 100мс
2. Считаем RMS (энергию) каждого блока
3. RMS > 200 -> речь (копим в буфер)
4. RMS < 200 в течение 1.0с -> речь закончена -> транскрибируем

### Транскрипция
- faster-whisper (модель large-v3, CUDA, float16)
- Результат: строка текста на русском
- Пустой результат (<2 символов) -> пропускаем

### STT коррекции
```python
"рак" -> "RAG"    # частая ошибка распознавания
"РГ"  -> "RAG"
```

### Interrupt при распознавании
Если профессор говорит (`is_speaking=True`) и STT распознал реальный текст:
- Очистить tts_queue
- Вставить interrupt-сигнал
- Профессор замолкает

---

## 5. CoreAgent — мозг системы

**Файл:** `src/agent/core_agent.py`
**Класс:** `CoreAgent(BaseAgent)`

### Инициализация
```python
self.llm = get_llm_chain()              # Mistral через litellm
self.rag_model = RagModel()             # FAISS RAG
self._profile_mgr = StudentProfileManager()  # SQLite профили
self.tool_bank = tools_config.init_tools_module()
self._current_student = None            # имя текущего студента
self._interrupted = False               # флаг прерывания
self._meta_running = False              # guard для meta-agent
```

### Главный цикл: step()

```python
def step(self):
    # 1. Ждем триггер (или берем последнее сообщение после interrupt)
    messages = construct_prompt_messages(wait_for_trigger=not self._interrupted)

    # 2. Очищаем TTS очередь (старые ответы)
    tts_queue.clear() + interrupt

    # 3. Достаем последнее сообщение студента
    last_student_msg = ...

    # 4. Проверка стоп-команд
    if "стоп" in msg -> TTS("Хорошо, слушаю.") -> return

    # 5. Инжектим профиль студента в промпт

    # 6. Стримим ответ от LLM
    for sentence in stream_response_sentences(...):
        # Проверка interrupt (новое сообщение студента)
        if len(ctx_chat) > before -> break

        spoken_sentences.append(sentence)
        _send_to_tts(sentence)

    # 7. Сохраняем в историю (только озвученное)
    # 8. Фоновый meta-анализ (если не прервано)
    # 9. Если прервано -> _interrupted = True -> повтор без ожидания
```

### Обработка текста перед TTS
```python
_send_to_tts(text):
    1. Убрать (neutral), (happy), etc.      # теги эмоций
    2. Убрать *emotion*                      # legacy теги
    3. Убрать *любой текст в звездочках*     # markdown разметка
    4. "Хм..." -> "Хмммм."                  # растянуть троеточие
    5. -> tts_queue.append({"text": ..., "emotion": "neutral"})
```

### run() — бесконечный цикл
```python
def run(self):
    self.running = True
    ctx_swarm["fx_queue"].put("starting")  # звук запуска
    while ctx_swarm["env"]["actived"] and self.running:
        self.step()
```

---

## 6. Streaming Orchestrator

**Файл:** `src/agent/streaming_orchestrator.py`

### SentenceBuffer — накопитель предложений

Собирает токены от LLM в готовые предложения:
```
Токены:  "Это " "простой " "пример." " А " "вот " "второй."
Выход:   -> "Это простой пример."
         -> "А вот второй."
```

**Правила:**
- Разбивать на `.!?` + пробел (но НЕ после цифр: `1.`, `2.`)
- Предложения >10 слов -> разбить на запятых/союзах
- Фрагменты <3 слов -> склеить со следующим
- Накопилось >20 слов без пунктуации -> принудительный сброс

### stream_fast() — стриминг с hard timeout

```python
def stream_fast(messages, temperature, max_tokens):
    # LLM вызов в отдельном потоке
    thread -> litellm.completion(stream=True) -> queue.put(token)

    # Основной поток читает с таймаутом
    while True:
        token = queue.get(timeout=10)  # 10с — если Mistral повис
        yield token
```

Если Mistral не отвечает 10 секунд -> поток обрывается, агент восстанавливается.

### stream_response_sentences() — высокоуровневый API

```python
for token in stream_fast(messages):
    sentences = buffer.add(token)
    for sentence in sentences:
        yield sentence  # готовое предложение -> TTS
remaining = buffer.flush()
if remaining:
    yield remaining
```

---

## 7. Prompt Constructor

**Файл:** `src/agent/prompt_generation/prompt_constructor.py`

### construct_prompt_messages() — сборка промпта

**Вход:** tools, ctx_handler, rag_model, output_format
**Выход:** List[Message] + response_starting

**Шаги:**
1. **Ожидание триггера** — `wait_for_sync(timeout=15с)`
   - Пропускает self-сообщения (ответы профессора)
   - Пропускает если TTS/chat очереди заняты

2. **Тривиальность** — пропуск RAG для приветствий
   - Exact: "привет", "да", "нет", "ок", "спасибо"
   - Contains: "добрый день", "как дела", "слышите"
   - Короткие: < 15 символов

3. **RAG запрос** — поиск по материалам курса
   - Top-2 документа с distance < 1.5

4. **Сборка промпта:**
   ```
   [System] personality + RAG context + student profile
   [User/Assistant] ... история чата (до 50 сообщений) ...
   [User] "=== Последние сообщения END === Инструкция: ..."
   ```

### construct_prompt() — системный промпт
```python
personality_template     # из personalities_professor.yml
+ RAG context            # "## Контекст из материалов курса: ..."
+ student_profile        # "## Профиль студента: ..."
+ meta_instruction       # "## Стиль текущего ответа: ..."
```

---

## 8. RAG

**Файл:** `src/agent/rag.py`
**Класс:** `RagModel`

### Документы
- **Источник:** `resources/RAG/course_materials/` (4 лекции: week1-4)
- **Разбиение:** `CustomTripleNewLineSplitter` (50-1000 символов на чанк)
- **Эмбеддинги:** Mistral Embeddings API
- **Хранилище:** FAISS (`data/rag_vector_store/`)

### Поиск
```python
explain(query) -> str:
    1. Векторизация запроса
    2. similarity_search_with_score() -> top-2 документа
    3. Фильтр: distance > 1.5 -> "NOT FOUND"
    4. Возврат: конкатенация content двух лучших чанков
```

### Warmup
При старте: запрос "Что такое вайб?" для прогрева FAISS + embeddings API.

---

## 9. Meta-Agent

**Файл:** `src/agent/meta_agent.py`

### Что делает
Анализирует контекст диалога через Claude Haiku (быстрый, 200 токенов):

**Вход:** профиль студента + последние 5 сообщений (с ролями) + текущее

**Выход (JSON):**
```json
{
  "mood": "спокоен|раздражен|растерян|любопытен|торопится|шутит",
  "request_type": "техпомощь|теория|приветствие|юмор|offtopic",
  "is_off_topic": false,
  "humor_detected": false,
  "style_instruction": "как именно отвечать",
  "profile_updates": {
    "tech_level_delta": 0,
    "add_topic": "RAG системы",
    "communication_note": "нуждается в пошаговых инструкциях"
  }
}
```

### Когда запускается
- **Только** после полного (не прерванного) ответа
- **Только** если предыдущий meta-agent завершился (`_meta_running` guard)
- В **фоновом потоке** (не блокирует основной)

### extract_student_info()
Regex-парсинг имени и бэкграунда из сообщения:
```
"Привет, я Алексей, работаю ML-инженером"
-> {"name": "Алексей", "background": "работаю ML-инженером"}
```

---

## 10. Процесс TTS

**Файл:** `src/tts/simple_tts_handler.py`

### Архитектура очереди

```
tts_queue: [{"text": "...", "emotion": "neutral"}, ...]
                    |
    _handle_vosk_queue_stream()
                    |
    split_sentences() -> ["Первое.", "Второе."]
                    |
    vosk_tts_sentence() -> POST /tts/sentence -> audio numpy
                    |
    audio_processor.play_sound(audio, sr, blocking=True)
```

### Prefetch — ключевая оптимизация

```
Обычный режим:             С prefetch:
  Синтез1 -> Проигрыш1      Синтез1 -> Проигрыш1
  Синтез2 -> Проигрыш2             \-> Синтез2 -> Проигрыш2
  Синтез3 -> Проигрыш3                     \-> Синтез3 -> Проигрыш3

Экономия: ~300-700мс на каждом переходе между предложениями
```

**Реализация:** `ThreadPoolExecutor(max_workers=1)` — один фоновый синтез.

### Vosk-TTS клиент (`src/tts/vosk/vosk_tts.py`)

- **Сервер:** отдельный процесс на порту 22232
- **Модель:** vosk-model-tts-ru-0.9-multi (VITS, 22050 Hz)
- **Голос:** speaker_id=4 (male_1)
- **Кеш фраз:** ~40 частых фраз в `resources/Audio/tts_cache/`
- **Split:** предложения до 10 слов для быстрого синтеза

### Interrupt в TTS
```python
{"text": "interrupt", "emotion": "interrupt"}
```
Когда этот элемент попадает в очередь -> `audio_processor.interrupt_main_device()` -> звук обрывается.

---

## 11. Система прерываний

Три уровня прерывания, от быстрого к медленному:

### Уровень 1: TTS Interrupt (мгновенный)
**Когда:** STT распознал текст студента пока профессор говорит
**Что:** Очистка tts_queue + interrupt сигнал -> звук обрывается
**Файл:** `mic_stt_handler.py`

### Уровень 2: LLM Stream Break (~0-10с)
**Когда:** В streaming loop обнаружено новое сообщение в ctx_chat
**Что:** `break` из цикла генерации, `_interrupted = True`
**Файл:** `core_agent.py`, streaming loop

### Уровень 3: Stop Commands (мгновенный, без LLM)
**Когда:** Сообщение содержит "стоп/подождите/помолчите/секунду"
**Что:** TTS("Хорошо, слушаю.") -> return (LLM не вызывается)
**Файл:** `core_agent.py`

### Post-interrupt re-entry
После прерывания агент **сразу** обрабатывает новое сообщение:
```python
self._interrupted = True
-> step() вызывается снова
-> construct_prompt_messages(wait_for_trigger=False)
-> берет последние сообщения из ctx_chat
```

### Tracking озвученного
```python
spoken_sentences = []       # что реально ушло в TTS
for sentence in stream:
    if interrupted: break
    spoken_sentences.append(sentence)
    _send_to_tts(sentence)

# При прерывании сохраняется только озвученное:
_save_to_history(spoken_text + " [прервано студентом]")
```

---

## 12. Профили студентов

**Файл:** `src/lecture/student_profiles.py`
**Класс:** `StudentProfileManager`

### Схема SQLite (`data/student_profiles.db`)

```sql
students:
  id, name (UNIQUE), first_seen, last_seen,
  total_interactions, tech_level (1-5),
  communication_style, topics_of_interest (JSON),
  known_issues (JSON), personality_notes, background

interaction_log:
  id, student_name, timestamp, student_message,
  agent_response, meta_analysis (JSON), emotion_tag
```

### Как работает
1. **extract_student_info()** — парсит имя из "Привет, я Алексей"
2. **get_or_create_student()** — создает или обновляет профиль
3. **Meta-agent** -> profile_updates -> `update_profile()`
4. **get_profile_for_prompt()** -> строка для инъекции в промпт

### Пример профиля в промпте
```
Профиль студента: Алексей. Общений: 12. Уровень: 4/5.
Интересы: RAG системы, Docker.
Проблемы: fallback голоса в Fish TTS.
Фон: ML-инженер, опыт с Python.
```

---

## 13. Система инструментов

**Файлы:** `src/agent/tools/`

### Активные инструменты
| Инструмент | Назначение |
|------------|-----------|
| `speak` | Озвучить текст с эмоцией |
| `interrupt_voice` | Остановить текущую речь |
| `interrupt_chat` | Очистить TTS очередь |
| `save_user_info` | Сохранить заметку о студенте |
| `wait` | Пауза (до 10с) |
| `clear_queue` | Очистить любую очередь |
| `fx` | Воспроизвести звуковой эффект |

### Формат вызова (legacy, из NetTyan)
LLM может вызвать инструмент в формате:
```
>Привет, как дела? *happy*     <- speak
!wait 3                        <- wait
!save_user_info Алексей "ML"   <- save
```

В текущей streaming архитектуре профессор не использует tool-calling напрямую.
CoreAgent.step() сам управляет TTS через _send_to_tts().

---

## 14. Shared State — ctx_swarm

Общее состояние между процессами через `multiprocessing.Manager`:

```python
ctx_swarm = {
    # Главное
    "ctx_chat": [],          # история всех сообщений (EventBase dicts)
    "ctx_chat_lock": Lock(), # для потокобезопасного доступа
    "tts_queue": [],         # очередь на озвучку
    "fx_queue": Queue(),     # звуковые эффекты

    # Голос
    "voice": {
        "is_speaking": False,    # профессор сейчас говорит?
        "text_chunk": "",        # текущий текст
        "speak_entry": {},       # текущий элемент очереди
    },

    # Настройки
    "env": {
        "actived": True,         # система работает?
        "personality": "professor_default",
    },

    # Состояние мышления
    "states": {
        "plan": "",
        "thoughts": {},
        "personality": "professor_default",
    },
}
```

---

## 15. CtxHandler

**Файл:** `src/data_flow/ctx_handler.py`

### Что делает
Управляет `ctx_chat` — историей сообщений. Все процессы пишут через него.

### Ключевые методы
| Метод | Назначение |
|-------|-----------|
| `add_message(event)` | Добавить сообщение (с дедупликацией) |
| `get_ctx_chat(limit=50)` | Получить последние N сообщений |
| `wait_for_sync(check, timeout)` | Ждать новое сообщение |
| `modify_message(id, updates)` | Обновить сообщение |

### Дедупликация
Окно 8 сообщений. Если совпадает `(type, user, msg)` -> не добавлять, увеличить `repeat`.

### Фоновый мониторинг
Поток `_check_changes()` каждые 50мс проверяет ctx_chat на новые сообщения и уведомляет ожидающих (waiters).

### EventBase — формат сообщения
```python
{
    "processing_timestamp": 1775471460219945600,  # наносекунды
    "date": "2026-04-06 13:31:00",
    "env": "voice",
    "user": "Student",          # или "Professor"
    "type": "chat",
    "msg": "Расскажите про RAG",
    "filter_results": {"acceptable": True},
    "self": True/False,         # True = ответ профессора
}
```

---

## 16. Конфигурация (.env)

### Ключевые переменные

| Переменная | Значение | Описание |
|-----------|---------|----------|
| `SELF_NAME` | Professor | Имя агента |
| `CORE_LLM_MODEL_NAME` | mistral/mistral-large-latest | Основная LLM |
| `SMART_LLM_MODEL_NAME` | openai/claude-opus-4.6 | Умная LLM (meta) |
| `TTS_BACKEND` | vosk | Бэкенд TTS |
| `VOSK_SPEAKER_ID` | 4 | Голос (male_1) |
| `VOSK_TTS_URL` | http://localhost:22232 | Vosk сервер |
| `SOUND_DEVICE_OUT` | Voicemeeter Input | Выход звука |
| `SOUND_DEVICE_IN` | fifine | Микрофон |
| `FASTER_WHISPER_MODEL_NAME` | large-v3 | Модель STT |
| `STT_COMPUTE_DEVICE` | cuda | GPU для STT |
| `MISTRAL_API_KEY` | ... | API ключ Mistral |
| `OPENAI_API_KEY` | sk-aw-... | API ключ awstore (для Claude) |
| `SMART_LLM_API_BASE` | https://api.awstore.cloud/v1 | Base URL для Claude |

---

## 17. Промпт профессора

**Файл:** `resources/Prompts/personalities_professor.yml`

### Ключевые правила

**Роль:** ИИ-ассистент преподавателя курса по созданию цифровых персонажей.
NetTyan — пример персонажа для обучения, не цель клонирования.

**Голос:** Говорит как опытный старший коллега. Варьирует длину.
Не повторяет структуру. Не заканчивает вопросом.

**Знакомство:** Если студент неизвестен -> попросить представиться (один раз).
Если знаком -> сразу к делу.

**Адаптация:** Программист -> код. Дизайнер -> визуальные аналогии.
Новичок -> просто. Продвинутый -> технично.

**Юмор:** Не шутит сам. Реагирует тепло на шутки студента.

**Остановка:** "Стоп/подождите" -> "Хорошо." и молчать.

**Запреты:** Нет "Понятно?". Нет "Отличный вопрос". Не объявлять технические действия вслух.

**Эмоции:** В конце реплики тег: (neutral) (happy) (thoughtful) (encouraging).
Не произносится вслух — только для управления TTS.

---

## 18. Форматирование истории

**Файл:** `src/utils/format_helper.py`

### Формат для LLM
```
[30с назад] Студент: Расскажите про RAG.
[15с назад] Professor (ты): RAG - это как библиотекарь. [прервано студентом]
[5с назад] Студент: А подробнее?
```

### Роли
- `event.get("self", False) == True` -> `role: "assistant"` (профессор)
- Все остальное -> `role: "user"` (студент)

### Категории сообщений
- **Old** (>1 мин) — "Ранее в диалоге:"
- **Relevant** (<1 мин) — "Недавний контекст:"
- **Recent** (последние) — "Текущий диалог:"

---

## 19. Запуск системы (main.py)

### Последовательность запуска
```
 1. [0-5с]   Импорт модулей (gradio, pandas, pygame, tts)
 2. [5-10с]  Manager + ctx_swarm + Database
 3. [10с]    TTS Process запущен
 4. [10с]    STT Process запущен
 5. [10-15с] CoreAgent создан (RAG warmup ~1.5с)
 6. [15-20с] Gradio UI запущен (порт 22228)
 7. [20с+]   Agent control loop -> CoreAgent.run()
```

### Gradio UI
- **Вкладка Control:** ввод текста, отображение контекста
- **Вкладка Audio:** кнопки Созвон/Локально/Отпустить для VoiceMeeter
- **Вкладка TTS Queue:** мониторинг очереди, ручная отправка
- **Вкладка Stats:** тайминги LLM/TTS/playback

---

## 20. Тайминги

| Операция | Задержка |
|----------|---------|
| VAD (детекция речи) | ~100мс (1 блок) |
| Тишина до обрезки | ~1.0с |
| STT транскрипция (3с аудио) | ~1-2с |
| RAG поиск | ~0.5-1.0с |
| LLM первый токен (Mistral) | ~0.8-1.5с |
| LLM первое предложение | ~1.0-2.0с |
| TTS синтез (Vosk, 1 предложение) | ~0.2-0.7с |
| TTS prefetch gap | ~0мс (параллельный синтез) |
| Meta-agent (Haiku) | ~0.5-1.0с (фон) |
| **E2E: речь -> первый звук** | **~3-5с** |

---

## 21. Отладка

### Ключевые логи
```
[MIC-STT] Speech started (RMS=...)     - VAD поймал звук
[MIC-STT] >>> текст                     - STT результат
[AGENT] Triggered by event: ...         - агент получил триггер
[AGENT] Skipping RAG for trivial        - RAG пропущен
[STREAM] Calling mistral/...            - LLM вызов
[AGENT] sentence #N (Xms): 'текст'     - предложение сгенерировано
[STREAM] Stream finished normally       - LLM стрим закончен
[STREAM] Timeout: no tokens for 10s     - LLM завис, восстановление
[AGENT] Student interrupted             - студент перебил
[AGENT] Stop command detected           - стоп-команда
[META-AGENT] {...}                      - результат meta-анализа
[TTS] #N audio: Xs | 'текст'           - предложение озвучено
```

### Частые проблемы

| Симптом | Причина | Решение |
|---------|---------|---------|
| Нет ответа после триггера | Mistral API завис | Подождать 10с (timeout), проверить API |
| STT не ловит речь | RMS порог слишком высок | Проверить SILENCE_THRESHOLD, уровень микрофона |
| Профессор не замолкает | Стоп-слово не в списке | Добавить в `_stop_words` в core_agent.py |
| RAG возвращает мусор | Старый FAISS индекс | Удалить `data/rag_vector_store/`, перезапустить |
| Meta-agent ломает стрим | Параллельные litellm вызовы | `_meta_running` guard (уже есть) |
| Задержка между предложениями | Prefetch не работает | Проверить ThreadPoolExecutor в TTS |
| "рак" вместо "RAG" | STT коррекция пропущена | Добавить в `_STT_FIXES` в mic_stt_handler.py |
