# История разработки AI Professor

> Хронология создания ИИ-агента-преподавателя для курса PersonaLab Workshop.
> Акцент на проблемах, ошибках, альтернативных решениях и ключевых решениях на каждом этапе.

---

## Обзор

- **Период:** 26 марта — 4 апреля 2026 (10 дней, 6 рабочих сессий)
- **Коммитов:** 25
- **Итог:** −16 853 строк удалено, +4 582 добавлено (171 файл изменён)
- **База:** форк NetTyan (автономная ИИ-стримерша для Minecraft)
- **Цель:** образовательный голосовой ИИ-ассистент для Zoom-лекций

---

## День 1 — 26 марта: Форк и архитектура

### Что сделано
- Форк репозитория NetTyan, начальная загрузка кода
- Создан `CLAUDE.md` — описание проекта для работы с Claude Code
- Написаны новые модули: `wake_word.py` (детектор обращений), `transcript_buffer.py` (буфер транскрипта), `summarizer.py` (конспектирование лекций), `logger.py` (метрики в SQLite)
- Создана персона профессора (`personalities_professor.yml`): три варианта — default, concise, summarizer
- `LectureManager` — фасад, объединяющий wake word + буфер + суммаризатор + метрики
- Интеграция в `main.py`: вкладки Lecture и Metrics в Gradio UI

### Проблемы и решения
| Проблема | Что случилось | Решение |
|---|---|---|
| **Pickle-ошибка LectureManager** | `LectureManager` содержит SQLite-соединения и `threading.Lock`, которые нельзя сериализовать через `multiprocessing.Manager` | Вынесли LectureManager в главный процесс. CoreAgent пишет данные как plain dict в `ctx_swarm["env"]["last_interaction"]`, polling-тред в main.py дренит их в LectureManager каждые 2 секунды |

### Архитектурное решение
Система на `multiprocessing.Manager` (shared state) — унаследована от NetTyan. Это фундаментальное ограничение: любой объект в shared state должен быть pickle-совместимым. SQLite, Lock, файловые хэндлеры — нельзя.

---

## День 2 — 27 марта: TTS, эмбеддинги, первые баги

### Что сделано
- Переключение на персону профессора (`professor_default`)
- Замена OpenAI Embeddings → Mistral AI Embeddings в RAG
- Подключение FishTTS на порту 22231 (Docker)
- Добавлен post-processing TTS: noise gate, low-pass фильтр, peak normalization
- Голосовые референсы профессора (`professor_neutral.wav`)

### Проблемы и решения
| Проблема | Что случилось | Решение |
|---|---|---|
| **Python version** | `pyproject.toml` требовал строгую версию Python, не совместимую с установленной | Ослабили ограничение версии |
| **Emoji encoding Windows** | Эмодзи в промптах ломали вывод на Windows cp1251 | Обернули вывод в safe encode/decode |
| **Donations dependency** | Код импортировал модуль донатов, которого нет в образовательном контексте | Удалили зависимость |
| **Mistral assistant prefill** | Mistral API не поддерживает `assistant` prefill в начале — выдавал ошибку | Убрали prefill из prompt_constructor |

### Альтернативы: TTS
- **FishTTS** (GPU, Docker, клонирование голоса) — выбран как основной
- Попытка LoRA fine-tune на 6 минутах аудиокниги → **полный провал** (смешение голосов, языков, интонаций). Причины: слишком мало данных (нужно 30+ мин), приблизительное выравнивание текста (Whisper word count вместо точных timestamps), переобучение уже на шаге 200
- **Решение:** остаться на zero-shot voice cloning через reference audio

### Альтернативы: Embeddings
- OpenAI Embeddings → не работали (проблемы с API ключом / совместимостью)
- Mistral AI Embeddings → работают, `mistral-embed` модель

---

## День 3 — 29 марта: Чистка NetTyan, RAG-материалы

### Что сделано
- **BREAKING:** полная замена персоны NetTyan на профессора
  - Словарь: мат → вежливые термины
  - Инструкции: nickname_analyzer → professor assistant
  - Few-shot примеры: насилие → образовательные Q&A
  - Удалены: yandere-режим, стримерские персоны, Minecraft-специфичные эмоции
- Добавлены RAG-материалы курса (5 .md файлов из docs/help/)
- Создан `process_recording.py` — офлайн-обработка записей лекций

### Проблемы и решения
| Проблема | Что случилось | Решение |
|---|---|---|
| **Остатки NetTyan повсюду** | yandere-режим в control_tools, emotion-типах, eye_rotater, hud_layer, warmup-сообщениях | Системная чистка: 15+ файлов, удаление enter_yandere_mode, streamer_abstract, все NSFW-контент |
| **Minecraft bossbar crash** | Код отправлял Minecraft-команды даже без сервера | Обернули в `ENABLE_MINECRAFT_HUD` env guard |

### Архитектурное решение
Двухэтапная чистка (два BREAKING-коммита) вместо одного большого: сначала персона, потом модули. Это позволило тестировать после каждого этапа.

---

## День 4 — 1 апреля: STT/TTS pipeline для Zoom

### Что сделано
- `mic_stt_handler.py` — новый STT-обработчик для микрофона (faster-whisper + VAD)
- Аудио-маршрутизация через VoiceMeeter Banana + VB-Cable
- **BREAKING:** удаление ВСЕХ стриминговых модулей NetTyan (Twitch, YouTube, Discord, DonationAlerts, Minecraft gameplay, browser automation)

### Проблемы и решения
| Проблема | Что случилось | Решение |
|---|---|---|
| **Два VB-Cable нужны** | Zoom одновременно и источник (speaker → STT) и приёмник (TTS → mic) — один кабель не справится | VB-Cable A для Zoom→STT, VoiceMeeter Banana для TTS→Zoom |
| **sounddevice vs soundcard** | sounddevice (STT) обрезает имена устройств на ~32 символа (MME), soundcard (TTS) использует полные Windows Core Audio имена | Короткие имена в .env для sounddevice, полные для soundcard |
| **find_mic_device min vs max** | `max()` по device index выбирал WDM-устройство (device 29), которое молчит | Заменили на `min()` — device 1 (MME) работает |
| **VoiceMeeter A1 exclusive lock** | Sound Blaster Play! 3 захватывается VoiceMeeter A1 эксклюзивно | TTS-вывод через VoiceMeeter Input (VAIO), не напрямую в Sound Blaster |
| **FX_SOUND_DEVICE_OUT crash** | pygame (звуковые эффекты) падал при попытке играть в Sound Blaster | FX тоже через VoiceMeeter Input |

### Масштаб удаления
Удалено: Twitch/Trovo/YouTube/Discord/DonationAlerts collectors, Minecraft gameplay agent (minebridge, minecraft_tools, game_agent), browser automation, vote/fun tools, NetTyan slang/docs/audio, streaming configs. Оставлено: RAG, lecture processing, STT/TTS, Live2D, core agent.

---

## День 5 — 2 апреля: Piper TTS, промпт-инженерия, стриминг

### Что сделано
- **Piper TTS** как CPU-альтернатива FishTTS (голос Denis-medium, ~0.3s генерация)
- Переключение TTS_BACKEND через .env: `"piper"` или `"fish"`
- LLM stream с таймаутом (5s без токена = конец ответа)
- Полный ответ собирается, потом целиком отправляется в TTS (без sentence splitting)
- Сохранение ответов профессора в ctx_chat с `self=True`
- Промпт: когнитивная нагрузка, режим А (конкретный) / режим Б (уточняющий)
- Emotion-теги: `(neutral)/(happy)/(thoughtful)/(encouraging)`

### Проблемы и решения
| Проблема | Что случилось | Решение |
|---|---|---|
| **STT tiny vs large-v3** | Сначала downgrade до tiny (освободить VRAM для FishTTS) → качество распознавания упало | Вернули large-v3, а TTS перевели на Piper (CPU) — освободило GPU полностью |
| **audio_device.py IN/OUT перепутаны** | TTS молчал — использовал SOUND_DEVICE_IN вместо OUT для колонок | Исправили на SOUND_DEVICE_OUT |
| **filter_client None crash** | `get_secret("RAZRABS")` возвращал None → crash | Добавили проверку на None |
| **Supervisor not None** | main.py проверял `ctx` вместо `Supervisor` → agent не стартовал | Исправили условие |
| **prompt_constructor no trigger** | Функция не возвращала None при отсутствии триггера → crash | Добавили `return None, ""` |
| **FishTTS reference_id** | `reference_id="professor"` давал неправильный голос из Docker-кеша | Использовать `reference_id=""` + загрузка WAV напрямую |
| **TTS post-processing шум** | Lowpass 8kHz + pitch shift 1.05x добавляли шум и искажения | Удалили post-processing полностью |
| **Mistral API stream hang** | LLM stream никогда не закрывался — Mistral API не слал StopIteration | `_next_with_timeout` с 5s таймаутом в отдельном треде |
| **Self-trigger loop** | Ответ профессора попадал в ctx_chat → агент обрабатывал его как новое сообщение → бесконечный цикл | Добавлен флаг `self=True` на ответы профессора |
| **Piper choppy audio** | Итерация по чанкам аудио давала прерывистый звук | Переход на SynthesisConfig + crossfade между сегментами |
| **Piper length_scale** | `_voice.config.length_scale` ломал просодию | Использовать SynthesisConfig для параметров |

### Альтернативы: TTS
| Вариант | Плюсы | Минусы | Статус |
|---|---|---|---|
| FishTTS (GPU Docker) | Клонирование голоса, эмоции | 1.75 GB VRAM, блокирует GPU для STT | Запасной |
| Piper TTS (CPU) | Быстрый (~0.3s), не трогает GPU | Нет клонирования, фиксированный голос | **Основной** |
| FishTTS LoRA | Свой голос | Провалился с 6 мин данных | Отброшен |

### Альтернативы: STT модели
| Вариант | Плюсы | Минусы | Статус |
|---|---|---|---|
| Whisper large-v3 (CUDA) | Лучшее качество | 3 GB VRAM | **Основной** |
| Whisper tiny (CUDA) | Мало VRAM | Плохое качество русского | Отброшен |

---

## День 6 — 4 апреля: RAG, лекции, финальные фиксы

### Что сделано
- Исправлен парсинг emotion-тегов: safety-net regex strip ВСЕХ тегов перед TTS
- LLM таймаут: 5s → 10s → 15s, graceful "..." при обрыве
- Chat history: `event.get("self", False)` → `role="assistant"` в промпте
- RAG загрузчик: поддержка .md файлов (было только .txt)
- RAG-материалы: 19 .md файлов из GitHub-репо NetTyan + 4 конспекта лекций
- Транскрибация 4 лекций: Whisper large-v3 CUDA, ~13 000 сегментов, ~60 мин обработки
- Суммаризация лекций через Mistral Large API → конспекты в RAG
- Промпт v3: 3 правила (КРАТКОСТЬ / КОНКРЕТНОСТЬ / ДИАЛОГ) вместо A/B-режимов
- VoiceMeeter Zoom/Direct toggle в Gradio UI
- Chunking fix: fallback \n\n для markdown, merge мелких чанков (min 50 chars)

### Проблемы и решения
| Проблема | Что случилось | Решение |
|---|---|---|
| **Студент слышит "нейтрал"** | `_parse_emotion` парсил тег корректно, но только в конце строки (`$`). Если LLM ставил тег в середине или в нестандартном формате — тег оставался | Safety-net: два compiled regex `_EMOTION_PAREN_RE` и `_EMOTION_STAR_RE` зачищают ВСЕ вхождения тегов перед TTS, плюс при сохранении в историю |
| **RAG грузил 0 course material chunks** | `glob="*.txt"` — не грузил .md файлы | Цикл по `("*.txt", "*.md")` |
| **Professor responses как "user"** | `format_events_with_roles` давал `role="assistant"` только для `type="tool_call"`. У профессора `type="chat"` | Добавлен `or event.get("self", False)` в условие |
| **PROFESSOR_VOICE_RULES конфликт** | Старые правила говорили "задай уточняющий вопрос", новый промпт — "отвечай сразу" | Синхронизировали VOICE_RULES с новым промптом |
| **RAG stubs вместо реальных docs** | Заглушки `architecture_overview.txt` и `faq.txt` содержали общую информацию | Заменены на 19 .md файлов из GitHub-репо NetTyan (git clone → copy) |
| **RAG tiny chunks → Mistral 400** | CustomTripleNewLineSplitter резал по `\n\n\n`, markdown файлы не содержат тройных переносов → файл = 1 чанк (15-19 KB). При fallback на `\n\n` — 234 чанка < 50 символов (заголовки) | Fallback split на `\n\n` + merge мелких чанков в соседей (min 50 chars). Результат: 362 чанка, min 50, avg 234 символов |
| **Documents/knowledge/ не существует** | `dataloader` падал с FileNotFoundError → RagModel = None → RAG не использовался ВООБЩЕ. **Это была главная причина "галлюцинаций"** | Создана пустая директория + `os.path.isdir()` guard в загрузчике |
| **Промпт A/B → 3 правила** | Режим Б ("уточняющий") заставлял модель переспрашивать вместо ответа на "расскажи про RAG" | Правило 2 (КОНКРЕТНОСТЬ): "отвечай сразу на самую вероятную интерпретацию" |
| **cp1251 Unicode arrows** | Символ `→` в print-строках ломал Windows console | Заменили на `->` |

### Критический баг сессии
**RAG не работал вообще** (обнаружен в конце дня). Цепочка:
1. `resources/Documents/knowledge/` не существовала
2. `dataloader.load()` → `FileNotFoundError`
3. `CoreAgent.__init__` → `except` → `self.rag_model = None`
4. `construct_prompt_messages` → `if rag_model is not None` → `False`
5. Промпт отправлялся БЕЗ RAG-контекста
6. Модель отвечала из своих знаний → "галлюцинации"

Баг существовал с первого запуска. Все предыдущие тесты RAG через `python -c "from agent.rag import RagModel"` работали, потому что `dataloader` находил директорию. Но при запуске через `main.py` → `CoreAgent` → путь разрешался иначе. Исправление: создать директорию + guard.

---

## Хронология ключевых решений

| Дата | Решение | Альтернатива | Почему выбрали |
|---|---|---|---|
| 26.03 | Форк NetTyan | Писать с нуля | NetTyan уже имеет multiprocessing pipeline, Live2D, TTS/STT |
| 27.03 | Mistral Embeddings | OpenAI Embeddings | OpenAI не работал, Mistral стабильнее |
| 27.03 | Zero-shot voice cloning | LoRA fine-tune | 6 мин данных → мусор. Нужно 30+ мин |
| 01.04 | VoiceMeeter Banana | Два VB-Cable | VoiceMeeter даёт матрицу маршрутизации, мониторинг, gain control |
| 02.04 | Piper TTS (CPU) | FishTTS (GPU) | Освобождает GPU для STT, быстрее (0.3s vs 1-2s), не нужен Docker |
| 02.04 | Whisper large-v3 | Whisper tiny | Качество русского языка критично для образования |
| 02.04 | Полный ответ → TTS | Sentence splitting → TTS | Piper быстрый, просодия лучше на полном тексте |
| 04.04 | 3 правила промпта | Режимы A/B | Режим Б (уточняющий) раздражал — модель переспрашивала вместо ответа |
| 04.04 | 15s stream timeout | 5s / 10s | Mistral Large думает 6-7s перед первым токеном |

---

## Итоговая архитектура

```
Микрофон (fifine)
    → STT (Whisper large-v3, CUDA, faster-whisper)
    → RAG (FAISS + Mistral Embeddings, 362 чанка из 23 файлов)
    → LLM (Mistral Large API, 15s stream timeout)
    → Emotion parser (regex strip перед TTS)
    → TTS (Piper denis-medium, CPU, crossfade)
    → VoiceMeeter Banana
    → Наушники (A1) + Zoom mic (B1)
```

**RAG knowledge base:** 19 файлов документации NetTyan + 4 конспекта лекций (транскрибация Whisper + суммаризация Mistral)

**Gradio UI** (порт 22228): управление агентом, TTS очередь, ctx_chat, VoiceMeeter toggle

---

## Статистика ошибок по категориям

| Категория | Количество | Примеры |
|---|---|---|
| Аудио/маршрутизация | 7 | IN/OUT перепутаны, MME truncation, exclusive lock, pygame crash |
| TTS | 5 | LoRA fail, reference_id cache, post-processing noise, choppy audio, length_scale |
| LLM/промпт | 5 | Stream hang, self-trigger loop, prefill error, A/B vs 3-правила, timeout |
| RAG | 5 | 0 chunks, .txt only, tiny chunks, missing directory, stale index |
| Совместимость | 3 | Python version, emoji encoding, cp1251 Unicode |
| Архитектура | 2 | Pickle error, None checks |
