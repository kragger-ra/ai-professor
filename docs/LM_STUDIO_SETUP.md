# Настройка LM Studio для AI Professor

## Обзор

LM Studio позволяет запускать LLM локально на GPU, обеспечивая:
- Независимость от внешних API (Mistral, OpenAI)
- Prompt Caching через KV cache (TTFT ~1с при прогретом кеше)
- Скорость генерации 90-100 tok/s на RTX 4070
- Нулевую стоимость API-вызовов

## Текущая конфигурация

| Параметр | Значение |
|----------|---------|
| **Модель** | google/gemma-4-e4b |
| **Runtime** | 2.13.0 (CUDA 12) |
| **Порт** | 22227 |
| **Context length** | 4096 |
| **VRAM** | ~5.9 GB (модель) |
| **Генерация** | 90-100 tok/s |
| **TTFT (прогретый кеш)** | ~1с |
| **TTFT (холодный старт)** | ~2.2с |

## Ограничения VRAM

RTX 4070 = 12 GB VRAM. faster-whisper large-v3 (STT) занимает **до 4.6 GB peak**.
Доступно для LLM = ~7.4 GB.

Замеры под реальной нагрузкой (2026-04-13):

| Компонент | Idle | Peak (под нагрузкой) |
|-----------|------|---------------------|
| System baseline | 979 MB | 979 MB |
| Whisper large-v3 float16 | 3328 MB | **4562 MB** |
| Gemma 4 E4B (ctx 4096) | 5270 MB | ~6000 MB |
| **Комбинированный peak** | | **~10.5 GB** |
| **Запас** | | **~1.7 GB** |

### Протестированные модели

| Модель | VRAM | Результат | Примечание |
|--------|------|----------|------------|
| **Gemma 4 E4B** | ~5.9 GB | **РАБОТАЕТ** | reasoning_effort=none + TRIGGER_START |
| Qwen 3.5 9B (все Q-варианты) | ~6 GB | НЕ ПОДХОДИТ | thinking 6-14с overhead, убивает latency |
| Mistral 7B Instruct | ~5 GB | УДАЛЕНА | Очень плохое качество русского |

**Правило:** LLM VRAM + 4.6 GB (Whisper peak) < 12 GB. Всегда мерить peak под реальной нагрузкой, не при загрузке.

## Установка

1. Скачать LM Studio: https://lmstudio.ai
2. Обновить runtime до 2.13.0+ (нужен для Gemma 4):
   ```bash
   "C:/Users/Whiter/.lmstudio/bin/lms.exe" runtime update --yes
   ```
3. Скачать модель `google/gemma-4-e4b` через UI или CLI:
   ```bash
   "C:/Users/Whiter/.lmstudio/bin/lms.exe" ls  # проверить что скачана
   ```

## Критические настройки модели

### GPU Offload (ОБЯЗАТЕЛЬНО)
- **GPU Offload:** ВСЕ слои на GPU (ползунок "Layers to GPU" на максимум)
- Если не сделать — скорость упадёт с 90 tok/s до 3 tok/s
- В логах должно быть: `[LM] All layers offloaded to GPU`
- Если видите `0 layers offloaded` — двигайте ползунок

### Context Length
- Рекомендуется: **4096** токенов (текущая рабочая настройка)
- Можно увеличить до 8192, но проверить что Gemma + Whisper влезают в VRAM

### Prompt Caching
- Включён по умолчанию — **НЕ ВЫКЛЮЧАТЬ**
- LM Studio автоматически кеширует совпадающий префикс промпта
- Heartbeat Professor поддерживает кеш тёплым между запросами

### Unified Cache
- **НЕ ТРОГАТЬ** (оставить выключенным)
- С Unified Cache производительность хуже

### Reasoning Effort
- Gemma 4 поддерживает `reasoning_effort` в API
- Professor использует `reasoning_effort=none` — отключает thinking (0 reasoning tokens)
- Без этого модель генерирует thinking-блоки, увеличивая latency

## Запуск API сервера

### Через UI
1. В LM Studio: вкладка **"Local Server"** (или Developer)
2. Загрузить `google/gemma-4-e4b`
3. Нажать **"Start Server"**
4. Порт: **22227** (изменить если по умолчанию 1234)

### Через CLI
```bash
# Запустить сервер
"C:/Users/Whiter/.lmstudio/bin/lms.exe" server start --port 22227

# Загрузить модель
"C:/Users/Whiter/.lmstudio/bin/lms.exe" load google/gemma-4-e4b --gpu max --context-length 4096

# Проверить
"C:/Users/Whiter/.lmstudio/bin/lms.exe" ps
"C:/Users/Whiter/.lmstudio/bin/lms.exe" status
```

### Проверка
```bash
curl http://localhost:22227/v1/models

curl http://localhost:22227/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "loaded-model", "messages": [{"role": "user", "content": "Привет"}], "max_tokens": 50}'
```

## Настройка Professor

В `.env`:
```env
# Включить локальную LLM
USE_LOCAL_LLM="true"

# Адрес LM Studio API
LM_STUDIO_API_BASE="http://localhost:22227/v1"

# Имя модели (используется loaded-model по умолчанию)
LM_STUDIO_MODEL_NAME="google/gemma-4-e4b"

# Интервал keepalive для прогрева кеша (секунды)
LM_STUDIO_HEARTBEAT_INTERVAL="2.0"

# Отключить thinking
LM_STUDIO_REASONING_EFFORT="none"

# Фильтрация leaked thinking через TRIGGER_START
LM_STUDIO_FILTER_THINKING="true"
```

## Как работает Prompt Caching

LM Studio (llama.cpp) кеширует вычисленные key-value пары по совпадению токенов.
Если запрос B начинается с тех же токенов, что и запрос A — они не перевычисляются.

```
Запрос 1: [system prompt][profile][RAG][вопрос 1]  → ~2.2с (холодный старт)
Запрос 2: [system prompt][profile][RAG][вопрос 2]  → ~1с   (кеш на prefix)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ кешировано
```

Professor использует `CachedPromptConstructor` — вся статика (personality, student profile) идёт в начало промпта, динамика (RAG, chat history, вопрос) — в конец. Это максимизирует cache hit.

### Heartbeat (keepalive)

LM Studio сбрасывает KV cache через ~3-5 секунд неактивности.
Professor отправляет keepalive-ping каждые 2 секунды через `LMStudioClient._heartbeat_loop()`.

- Ping использует тот же prefix, что и последний реальный запрос
- `max_tokens=1` — минимальная генерация
- **Обязательно полностью читать response** — иначе кеш не сохранится
- GPU overhead: ~6% (0.18с на ping каждые 2-3с)
- Без heartbeat: TTFT вырастает с ~1с до 2.2-5с

### Правила для кеширования

1. **Стрим нужно полностью прочитать** — если прервать на середине, кеш не сохранится
2. **Динамические данные — в конец** — всё что меняется между запросами идёт в конец промпта
3. **Не менять системный промпт** — любое изменение в начале сбрасывает весь кеш

## ThinkingFilter и TRIGGER_START

### Проблема
Gemma 4 (и другие reasoning-модели) иногда генерируют внутренние "мысли" в content, даже с `reasoning_effort=none`. Студент услышит мусор вместо ответа.

### Решение
1. Системный промпт содержит инструкцию: "Начинай КАЖДЫЙ ответ со слова TRIGGER_START"
2. `ThinkingFilter` буферизует ВСЕ токены (нет true streaming)
3. При завершении — извлекает текст после **последнего** TRIGGER_START
4. Последнего — потому что модель иногда копирует системный промпт в thinking

### Последствия
- Нет true streaming: студент ждёт полную генерацию, потом слышит ответ по предложениям
- TTFT = prompt processing + полная генерация + фильтрация
- Но просто и надёжно: работает с любой моделью

### Почему не другие подходы?
| Подход | Почему не работает |
|--------|-------------------|
| Cyrillic/Latin ratio | Курс по AI — ответы содержат RAG, Docker, FAISS |
| Regex для `<thinking>` | Модели не всегда оборачивают мысли в теги |
| Streaming + partial filter | Нет надёжного способа определить конец thinking на лету |

## Ожидаемая производительность (RTX 4070, 12 GB)

| Метрика | Gemma 4 E4B |
|---------|------------|
| Генерация | 90-100 tok/s |
| VRAM (модель) | ~5.9 GB |
| VRAM (с Whisper, peak) | ~10.5 GB |
| TTFT (прогретый кеш) | ~1 секунда |
| TTFT (холодный старт) | ~2.2 секунды |
| E2E (речь → первый звук, warm) | ~3-5 секунд |
| E2E (речь → первый звук, cold) | ~5-8 секунд |

## Запуск

```bash
# 1. Запустить Vosk TTS сервер (отдельный терминал)
cd "N:/exam/hVostic TTS" && python server.py

# 2. Запустить LM Studio (через CLI или UI)
"C:/Users/Whiter/.lmstudio/bin/lms.exe" server start --port 22227
"C:/Users/Whiter/.lmstudio/bin/lms.exe" load google/gemma-4-e4b --gpu max --context-length 4096

# 3. Проверить что модель загружена
curl http://localhost:22227/v1/models

# 4. Запустить Professor
cd "N:/exam/LocalLLMExperement/AI-Professor"
USE_LOCAL_LLM=true PYTHONPATH=src python src/main.py --offline --no-filter

# 5. Бенчмарк (опционально)
PYTHONPATH=src python tests/benchmark_llm.py
```

## Остановка

```bash
# Убить python-процессы
taskkill /f /im python.exe

# Выгрузить модели
"C:/Users/Whiter/.lmstudio/bin/lms.exe" unload --all

# Остановить сервер
"C:/Users/Whiter/.lmstudio/bin/lms.exe" server stop

# Проверить что VRAM свободна
nvidia-smi
```

## Troubleshooting

| Проблема | Решение |
|----------|---------|
| TTFT > 3с при прогретом кеше | Проверить GPU Offload — все слои на GPU |
| 0 tokens received | `lms ps` — модель загружена? Сервер запущен? |
| Connection refused | `lms server start --port 22227` |
| Out of VRAM | Уменьшить context-length до 4096 или ниже |
| Leaked thinking в ответе | Проверить TRIGGER_START в системном промпте и `LM_STUDIO_FILTER_THINKING=true` |
| KV cache всегда холодный | Проверить `LM_STUDIO_HEARTBEAT_INTERVAL=2.0`, heartbeat thread в логах |
| Юмор дублирует ответ | Юмор должен быть отключён для local LLM (core_agent.py:935) |
| UTF-8 артефакты в ответе | В lm_studio_client.py: `resp.encoding = "utf-8"` перед iter_lines |
| Runtime не поддерживает Gemma 4 | `lms runtime update --yes` — нужен runtime 2.13.0+ |
| Генерация 3 tok/s вместо 90 | GPU Offload не на максимуме — все слои на GPU |

## Ключевые файлы

| Файл | Что делает |
|------|-----------|
| `src/agent/lm_studio_client.py` | Клиент LM Studio: streaming, heartbeat, ThinkingFilter |
| `src/agent/prompt_generation/cached_prompt_constructor.py` | KV-cache-оптимизированные промпты |
| `src/agent/streaming_orchestrator.py` | Маршрутизация Cloud/Local, TRIGGER_START фильтрация |
| `src/agent/core_agent.py` | USE_LOCAL_LLM flag, инициализация, маршрутизация |
| `src/agent/prompt_generation/prompt_constructor.py` | TRIGGER_START инструкция в PROFESSOR_GOAL |
| `.env` | Переменные LM_STUDIO_* |
