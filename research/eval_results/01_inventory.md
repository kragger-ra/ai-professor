# 01 — Инвентаризация системы (Tutor build)

**Дата замеров:** 2026-05-19
**Рабочий каталог:** `N:\exam\LocalLLMExperement\AI-Professor-Tutor`
**Ветка:** `student-release` (репо `kragger-ra/ai-professor`)
**GPU:** NVIDIA GeForce RTX 4070, 12 282 MiB

> Все цифры в этом отчёте получены прогоном `_inventory_probe.py`, `_inventory_measure.py`, `_inventory_retrieval.py`, чтением `.env`/конфигов и SQL-запросами к `data/metrics.db`. Никаких чисел из памяти.

---

## 1. Активная конфигурация LLM-стека

| Компонент | Реализация | Модель | Где задано |
|---|---|---|---|
| Core LLM (streaming Q&A) | `litellm` → OpenAI API | `openai/gpt-5.4` | `.env::CORE_LLM_MODEL_NAME` |
| LM Studio-совместимый эндпоинт | прямые `requests` на `api.openai.com/v1` | `gpt-5.4` | `.env::LM_STUDIO_*` |
| Meta-agent (фоновый анализ) | прямой POST на тот же эндпоинт | `gpt-5.4-mini` | `.env::META_LOCAL_MODEL` |
| Embeddings (RAG) | LM Studio локально на :22227 | `text-embedding-user-bge-m3` (358M, 261 MB) | `.env::EMBEDDINGS_MODEL` |
| STT | `faster-whisper` CUDA, float16 | `dvislobokov/faster-whisper-large-v3-turbo-russian` | `.env::FASTER_WHISPER_MODEL_NAME` |
| TTS | Vosk-TTS HTTP-сервер на :22232 | speaker_id=4, rate=0.95 | `.env::TTS_BACKEND` |
| Audio routing | VoiceMeeter Banana, AUDIO_MODE=meeting | I/O = `Voicemeeter Out B2` / `Voicemeeter Input` | `.env::AUDIO_MODE` |

**Управление reasoning:** `LM_STUDIO_REASONING_EFFORT=none` — без скрытых reasoning-токенов (критично для бюджета апробации $5).

**Stream-конфигурация:** `MAX_STREAM_TIME_S=30` wall-clock kill switch, `STREAM_TOKEN_TIMEOUT_S=7` per-chunk idle, `RESPONSE_MAX_TOKENS_LONG=1000` (был 5000 до инцидента 2026-05-17).

**ThinkingFilter:** код `lm_studio_client.ThinkingFilter` сохранён, но при `USE_LOCAL_LLM=false` фактически не используется в streaming-пути (`streaming_orchestrator._stream_to_queue_mistral`).

⚠ **Security:** OpenAI API key в `.env` хранится в plaintext. Тот же ключ был отдан мне в этой сессии. Если репо публичный или ключ ротировался — проверить и при необходимости перевыпустить.

---

## 2. Local / Cloud split после миграции

**Локально (на машине пользователя):**
- Faster-Whisper STT (CUDA, float16, ~2.1 GB VRAM)
- LM Studio + bge-m3 embeddings (~250 MB VRAM, runtime 2.13.0)
- Vosk-TTS HTTP сервер (CPU, ~120 MB RAM)
- Gradio UI + Manager IPC (3 процесса: main / STT / agent)
- SQLite: `data/metrics.db`, `data/student_profiles.db`
- FAISS index: `data/rag_vector_store/knowledge.faiss` (1024-d, 140 chunks)

**Облачно:**
- OpenAI API — `gpt-5.4` (Core LLM) + `gpt-5.4-mini` (Meta-agent), оба через `https://api.openai.com/v1`

**Версии:**
- Python 3.10.9 (uv-managed)
- `faster-whisper` (через WhisperModel, float16, CUDA 12)
- `langchain-litellm`, `langchain-openai`, `langchain-core` 0.3.x
- LM Studio runtime 2.13.0 (CUDA 12)
- FAISS: `IndexFlatL2`, dim=1024, ntotal=140

---

## 3. Что изменилось vs. предзащиты (12.05.2026)

> Источник: код-снимки + memory snapshots `project_session_2026_05_12 → project_session_2026_05_19`.

### Добавлено
- **OpenAI-streaming через litellm** (`streaming_orchestrator._stream_to_queue_mistral` — name historical, dispatches gpt-5.x с `max_completion_tokens` + `reasoning_effort`).
- **Wall-clock abort timer** в `stream_fast` (защита от litellm HTTP recv hang, инцидент 2026-05-17).
- **Meta-agent v2** — 7 полей вместо 10 (`mood, level, needs_analogy, stt_garbled, ref, stuck_on, style_hint`), на gpt-5.4-mini, см. `src/agent/meta_agent.py`.
- **Async save_to_history**, watchdog с heartbeat и queue-awareness (только тикает при пустой `tts_queue`).
- **Manner switching** в Q&A: 3 промпта в `personalities_professor.yml` — `professor_simpler / _neutral / _detailed`. Студент переключает голосом.
- **Lecture cache (semantic-replay)** — задумывался, реализован 16.05, но **частично откатан** в pivot 18.05.

### Удалено / откатано
- **Локальная Gemma 4 E4B (IQ4_XS)** в качестве Core LLM. Файл `bench_lmstudio.py` остался в AI-Professor (lecture сборка). LM Studio оставлен ради bge-m3.
- **Blocked-lecture педагогика**: `lecture_planner + comprehension_judge + блочная доставка с nudge/finale-remediation`. Откат 2026-05-18. Silence-hint таймер (`_silence_hint_sent`, `SILENCE_HINT_SHORT/LONG_S` константы и фразы «Подумай не спеша / пойдём дальше») вычищен из `core_agent.py` 2026-05-19.
- **Skeleton mechanism (two-pass outline→delivery)** — задокументирован, в Tutor pivot-сборке не задействован (нет вызовов).
- **Quiz session с remediation-циклом** — `src/lecture/quiz_session.py` ещё существует, но в `core_agent.py` единственное упоминание — комментарий. Голосовой quiz после лекции **не идёт**.
- **Auto-resume лекции, filler-фразы** — выпилены 16.05.
- **RMS-interrupt** — заменён на STT-based.

### Переписано
- **Core agent**: ~3607 LOC → ~1500 LOC (pivot 18.05, см. project_pivot_freetutor_shipped_2026_05_18).
- **Personalities**: `personalities_professor.yml` полностью переписан под voice-формат с правилом «факт сначала, аналогия потом» (3 манеры + summarizer).
- **Course config**: RAG-bound через `data/current_course.json` mtime-cache. Сейчас — PersonaLab Workshop.

### Архитектура — 3 процесса (без изменений vs. 12.05)
```
STT (faster-whisper, CUDA)      CoreAgent (main)             TTS (Vosk HTTP :22232)
     ↓                              ↑    ↓                       ↑
     ctx_chat ←─── multiprocessing.Manager ─────── tts_queue (prefetch)
                                    ↓
                       [LLM stream + RAG + meta-agent + profile]
```

---

## 4. VRAM (live, RTX 4070 12 GB)

| Состояние | VRAM used | Δ |
|---|---|---|
| Baseline (драйверы/ОС, ничего не запущено) | 749 MiB | — |
| После загрузки Faster-Whisper large-v3-turbo (float16) | 2 885 MiB | **+2 136 MiB** |
| Во время STT-инференса (sample WAV → текст) | 3 031 MiB | +146 MiB transient |
| После загрузки bge-m3 в LM Studio | ~1 316 MiB (отдельный процесс) | +20 MiB сверху на GPU |
| **Расчётный peak с поднятым стеком (Whisper + bge-m3 + буферы)** | **≈3 500 MiB** | — |

**Сравнение с предзащитой:** старый стек = Whisper (3.6 GB) + Gemma 4 E4B IQ4_XS (4.76 GB) ≈ 8.4 GB. Текущий = ~3.5 GB. **Освободилось ~5 GB**, влезает даже на 8 GB карту.

---

## 5. Тайминги (live, 10 прогонов)

### TTFT и end-to-end LLM (gpt-5.4 streaming через requests, с реалистичным system_prompt ≈ 7k chars + RAG snippet 1800 chars + user q)

| Метрика | TTFT | End-to-end |
|---|---|---|
| p50 | **1 398 ms** | **3 243 ms** |
| p95 | **1 686 ms** | **4 440 ms** |
| min / max | 640 / 1 686 | 2 258 / 4 440 |

Tokens на ответ: 81…186 (среднее 124). Все 10 запросов прошли успешно.

### Retrieval (FAISS `similarity_search_with_score` через bge-m3)

| Метрика | ms |
|---|---|
| p50 | **15 ms** |
| p95 | **63 ms** |
| mean | 21 ms |
| min / max | 11 / 63 |

Init-стоимость RAG (загрузка эмбеддингов + warmup): **7.14 s** — одноразовая при старте.

### End-to-end студент-в-студенте (расчётно)
STT (≈1 s VAD + 0.5-1.5 s транскрипция на CUDA) + Retrieval (~20 ms) + TTFT LLM (~1.4 s) + TTS-prefetch (≈0.5 s до первого слова) → **первое слово ответа ≈ 3-4 s** после конца речи студента.

### Сырые цифры
- `_inventory_llm_results.json` — все 10 LLM-замеров с превью ответов
- `_inventory_retrieval_results.json` — все 10 retrieval с top-1 L2

---

## 6. RAG-индекс (сейчас)

- **Курс:** PersonaLab Workshop (`data/current_course.json`)
  - topic: «создание цифрового персонажа (LLM + STT + TTS)»
  - audience: «студент магистратуры AI Talent Hub»
- **FAISS:** `IndexFlatL2`, dim=1024 (bge-m3), `ntotal=140`
- **Источники чанков:** все 140 имеют `kind="course_materials"`, `subject=None`
  - ⚠ subject не проставлен (курс грузился не через `reload_from_path`, а из стартового сканирования папки)
- **Размеры чанков:** min=50, median=240, mean=250, max=936 chars (`chunk_size=1000`, `chunk_overlap=0`, split по `\n\n\n` с fallback на `\n\n`)
- **Файлы курса** (`resources/RAG/course_materials/`):
  - `00_personalab_canonical.md` (13 200 B)
  - `supplemental_aprobacia.md` (9 894 B)
  - `week2_lecture.md` (18 652 B)
  - `week3_lecture.md` (17 608 B)
  - ⚠ `week1` отсутствует в course_materials — есть только в `lecture_summaries/`
- **Cutoff:** в `rag.py:explain()` — `best_score > 1.5 → пусто`. Top-2 docs из retrieve кладутся в prompt. Retriever настроен на `k=3` с фильтром по `kind=knowledge` (отдельный путь).
- **Распределение top-1 L2 на 10 тестовых вопросах:** min 0.587, median 0.975, max 1.248 — все ниже 1.5, релевантные.

---

## 7. metrics.db за 16-19 мая

```
interactions_total            = 58
interactions 2026-05-16..19   = 58 (всё в этом окне)
  2026-05-16                  = 11
  2026-05-17                  = 0    ⚠ день, когда тестировали, но логи в metrics.db не писались
  2026-05-18                  = 47
  2026-05-19                  = 0    ⚠ pivot-день, тестирование не пошло до записей
interactions_with_rag_sources = 53 / 58   (91 %)
system_metrics                = 0    ⚠ таблица пустая — STT/LLM/TTS latency не логировались
response_time_ms              = avg 4 251 / min 297 / max 18 607
```

**Схема `interactions`:** `id, timestamp, lecture_week, student_query, agent_response, response_time_ms, rag_sources (JSON), emotion, was_helpful`.

**Студенты:** в `student_profiles.db::students` — **26 записей** (накопилось за все запуски — реальная апробация ≈ 9 добровольцев, остальное — собственное тестирование).

**Дыры для эвалов:**
- `system_metrics` пустая → нельзя из БД достать исторические STT/LLM/TTS latency. Только агрегированный `response_time_ms` интеракции.
- `rag_sources` хранится как JSON-превью топ-2 (поле `preview` обрезано до 120 chars), а не как chunk_id или полный текст → faithfulness-eval (Промпт 3) **не сможет** на 100 % восстановить связку answer↔retrieved без повторного прогона запроса через систему.

---

## 8. Активные промпты

### 8.1 Системный промпт основного агента — `professor_simpler` (базовая манера, по умолчанию)

```
Ты — ИИ-репетитор курса {COURSE_NAME}. Тема курса: {COURSE_TOPIC}.
Мужской род. Русский язык. Ты говоришь ГОЛОСОМ.

## КОНТЕКСТ
Студент заранее прочитал учебный материал курса. Материал намеренно написан тяжёлым
академическим канцеляритом — словами вида «дислоцированной», «инкапсулирована»,
«инициализационной инъекции», «контекстуальной дескрипции». Студент пришёл к тебе,
чтобы разобрать непонятные места.

Твоя задача — переводить эти формулировки на простой человеческий русский с короткими
бытовыми аналогиями и конкретными примерами. Опирайся на материалы курса из RAG-базы
как на основной источник фактов.

## МАНЕРА (это базовая манера тьютора — «расскажи проще»)
- Бытовые аналогии: то, что человек уже знает из обычной жизни.
- Короткие фразы. Максимум 18 слов в предложении.
- Разговорный регистр, обращение на «ты». Никакого канцелярита в своих ответах
  («осуществляется», «реализуется», «дислоцирована» — НЕТ; «работает», «лежит», «делает» — ДА).
- Перед ключевой мыслью один лексический маркер выделения: «главное здесь — …»,
  «запомни — …», «если запомнишь только одно, то это — …». Один маркер на ответ, не больше.

## КАК СТРОИТЬ ОТВЕТ
ПЕРВОЕ предложение — короткий ФАКТ или ОПРЕДЕЛЕНИЕ простым языком. Не начинай с примера,
не начинай с «Представь», не начинай со сценки. Студент слушает тебя голосом — пример
без определения он не сможет привязать. Сначала факт — потом пример.

ВТОРОЕ-ТРЕТЬЕ предложение — короткий конкретный пример или бытовая аналогия. Можно
начать с «Например», «Допустим», «Смотри как это работает».

Длина ответа — на твоё усмотрение, под сложность вопроса. Простой фактический вопрос —
2-4 предложения. Сложный с несколькими связями — больше, но без воды. Если темa лезет
на 8+ предложений, останови себя и спроси: «Закрепить пример, или копнуть глубже?».

## ИСТОЧНИКИ
Материалы курса (RAG) — основной источник. Если узнаёшь фрагмент — можно кратко
процитировать или сослаться. НЕ пересказывай весь материал, отвечай конкретно
на то, что спросили.

Если в RAG ничего релевантного нет — отвечай из общих знаний и предупреди:
«В материалах курса этого нет, но из общих знаний…».

Не выдумывай конкретные факты (цифры, имена сущностей, версии), если их нет в контексте.

## ЗАПРЕТЫ
- НИКОГДА не начинай предложение со слова «Представь» или «Представьте».
- Никаких «отличный вопрос», «понятно?», «продолжить?» после каждой реплики.
- Не повторяй вопрос студента целиком перед ответом — сразу к сути.
- Не говори вслух про технические внутренности («я распознал твой голос», «сохранил профиль»).
- Не объявляй смену манеры словами «теперь объясню проще» — просто объясняй проще.
- Не зацикливай ту же мысль другими словами в одной реплике.
- Не используй markdown, backticks, скобки с настроением (например, "(neutral)").

## ОСТАНОВКА И ПАУЗА
Если студент говорит «стоп», «подожди», «помолчи», «секунду», «погодите», «хватит»,
«тихо», «давай паузу» — это просьба замолчать. ЗАМОЛЧИ. Один короткий ответ:
«Хорошо.» или «Слушаю.» и жди следующую реплику.

## OFF-TOPIC
Курс «{COURSE_NAME}» — про {COURSE_TOPIC}. Off-topic — мягко вернуть к теме одним-двумя
предложениями: «Это не про курс. Если по курсу — спрашивай.». Не извиняйся, не объясняй
почему. Один раз — и стоп.
```

Подстановки в рантайме: `{COURSE_NAME} → "PersonaLab Workshop"`, `{COURSE_TOPIC} → "создание цифрового персонажа (LLM + STT + TTS)"`. Источник — `data/current_course.json` через mtime-cache.

Есть ещё 2 манеры (`professor_neutral`, `professor_detailed`) — выбираются голосом, та же структура с разной планкой формализма. Полный текст: `resources/Prompts/personalities_professor.yml`.

### 8.2 Промпт мета-агента (gpt-5.4-mini, non-streaming, 7 полей)

```
Ты — аналитик учебного диалога. Смотришь на последние реплики и определяешь по
студенту семь параметров. Отвечай ТОЛЬКО валидным JSON без markdown.

Профиль студента: {profile}

Последние реплики (старые → новые):
{history}

Текущая реплика студента: {current}

Поля:
- "mood" — "спокоен" | "растерян" | "любопытен" | "раздражён"
- "level" — 1..5, насколько студент въезжает в ТЕКУЩУЮ тему (по последним 3-5 репликам)
- "needs_analogy" — true ТОЛЬКО если: студент явно не понял ("не понимаю/сложно/проще/
  что это значит") ИЛИ level<=2. Иначе false.
- "stt_garbled" — true если в реплике явно несвязные/несуществующие слова, ломаный
  русский, обрывки.
- "ref" — если в текущей реплике есть местоимение/указатель ("это / он / она / тот /
  та / такой") и непонятно к чему — короткое словосочетание из истории. Null если ясно.
- "stuck_on" — если студент уже 2+ раза за последние 5 реплик возвращается к одной
  концепции и явно её не схватывает — название концепции. Иначе null.
- "style_hint" — если студент в текущей реплике ЯВНО даёт инструкцию о ФОРМАТЕ ответа,
  извлеки её одним коротким повелительным предложением. Если просто комментарий — null.

Формат ответа (ровно эти ключи):
{"mood":"...","level":3,"needs_analogy":false,"stt_garbled":false,"ref":null,"stuck_on":null,"style_hint":null}
```

Вывод мета-агента рендерится в `build_meta_instruction()` и инжектится в системный промпт как **дополнительная инструкция** перед каждым ответом основной LLM (`src/agent/meta_agent.py:204-264`).

### 8.3 Персонажный конфиг — курс
```
{
  "name": "PersonaLab Workshop",
  "topic": "создание цифрового персонажа (LLM + STT + TTS)",
  "short_name": "PersonaLab",
  "teaching_style": "практично, без воды, технические аналогии для программистов",
  "audience": "студент магистратуры AI Talent Hub",
  "example_keywords": ["LLM", "STT", "TTS", "RAG", "FAISS", "Vosk", "Whisper", "цифровой персонаж"]
}
```

---

## 9. Точки риска / TODO до Промпта 2

1. **`system_metrics` таблица пустая** — историческая телеметрия latency восстановима только повторным прогоном. Для слайдов TTFT/E2E цифры из этого отчёта (live 19.05) — единственные.
2. **`rag_sources` хранит только превью** — для faithfulness-eval (Промпт 3) придётся повторно прогнать каждый исторический query через текущий стек, чтобы получить полный текст retrieved chunks. Это окей по cost ($0.005/call), но **факт fidelity faithfulness не будет 1:1 с тем, что слышал волонтёр** (модель та же, retrieval индекс тот же, но non-determinism temperature=0.6 даст другой ответ).
3. **Subject=None у всех чанков RAG** — для multi-course позиционирования (Промпт 5) надо переключиться на `reload_from_path` или вручную проставить `subject="PersonaLab"` в metadata. Сейчас выглядит так, будто курс «один и всегда».
4. **Week1 не в course_materials** — есть только в `lecture_summaries/`. Если на защите будет вопрос «откуда RAG берёт неделю 1» — ответ «из summary-ветки», что нормально, но надо знать.
5. **OpenAI ключ в plaintext** — ротация перед публикацией репо.

---

## Готовность к Промпту 2 (RAG retrieval eval)

Всё на месте:
- ✅ LM Studio + bge-m3 поднят, FAISS-индекс грузится за 7s, retrieve_full работает ~15 ms
- ✅ Курс PersonaLab активен, 140 чанков, материалы в `resources/RAG/course_materials/`
- ✅ Можно собирать ground truth и считать precision@k / MRR
- ✅ L2-распределение для distractor-анализа собрать тривиально (10 тестовых query уже дали разброс 0.59…1.25)

**Следующий шаг:** Промпт 2 — собрать 15-30 ground-truth вопросов и прогнать retrieval-метрики.
