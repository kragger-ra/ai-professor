# AI Professor — ИИ-агент-преподаватель PersonaLab Workshop

## Что это

ИИ-агент-преподаватель для 8-недельного воркшопа по созданию цифровых персонажей.
Форк NetTyan, адаптированный под образовательный контекст (Zoom-лекции, RAG по курсу, конспектирование).

- **Платформа:** ИТМО AI Talent Hub / PersonaLab
- **Трек ВКР:** Образовательный

## Быстрый старт

```bash
cp .env.example .env
# Заполнить API ключи и настройки аудио в .env
pip install -e .
python src/main.py
```

## Структура проекта

```
src/
  main.py                  # точка входа (Gradio UI + multiprocessing)
  agent/                   # CoreAgent, RAG, промпты, инструменты
  lecture/                 # НОВЫЕ модули: wake_word, transcript_buffer, summarizer
  metrics/                 # НОВЫЙ: SQLite логирование взаимодействий
  data_flow/               # ctx_handler, ctx_host (из NetTyan)
  data_collectors/stt/     # STT через faster-whisper
  live2d/                  # VTube Studio интеграция
  tts/                     # FishTTS
resources/
  Prompts/                 # personalities, instructions, abilities
  Customization/           # wake_words.yml, tool_bank_config и др.
  Audio/refs/              # голосовые сэмплы для клонирования
  RAG/                     # course_materials/, lecture_summaries/
data/
  metrics.db               # SQLite (автосоздаётся)
  transcripts/             # сырые транскрипты лекций
  faiss_index/             # персистентный RAG-индекс
```

## Архитектура

Система на `multiprocessing.Manager` (shared state между процессами):

- **STT Process** — faster-whisper, слушает Zoom через VB-Cable #1
- **Wake Word Detector** — keyword spotting на STT-транскрипте (русские фразы)
- **CoreAgent** — LLM + RAG по материалам курса
- **TTS Process** — FishTTS, выход через VB-Cable #2 в Zoom
- **Live2D** — VTube Studio, эмоции + lipsync → Virtual Camera → Zoom
- **Transcript Buffer** — копит STT для постфактум-суммаризации
- **Metrics Logger** — SQLite, все взаимодействия для ВКР

### Потоки данных

**Фоновый:** Zoom audio → STT → Transcript Buffer → [после лекции] → LLM суммаризация → RAG
**Интерактивный:** Wake word → CtxHandler → CoreAgent (RAG) → TTS + Live2D → Zoom

## Конфигурация

- `.env` — модели, API ключи, аудио-устройства (LiteLLM синтаксис)
- `resources/Customization/wake_words.yml` — триггер-фразы для обращения к агенту
- `resources/Prompts/personalities_professor.yml` — персонаж преподавателя

## LLM

- **Основной:** локальная модель через LM Studio/Ollama (`localhost:22227`) или Claude/Mistral API
- **Embeddings:** `bge-m3` через LM Studio
- Переключение модели: `CORE_LLM_MODEL_NAME` в `.env`

## Аудио маршрутизация (Zoom)

Требуется два VB-Cable:
- VB-Cable #1: Zoom speaker → STT (вход)
- VB-Cable #2: FishTTS → Zoom mic (выход)

## Правила разработки

- Язык кода: Python 3.11+
- Код и комментарии: на английском
- Промпты и персонаж: на русском
- Конфиги: YAML
- Метрики: SQLite
- Не трогать модули NetTyan без необходимости (data_flow, data_schema, live2d, tts)
- Новый функционал — в `src/lecture/` и `src/metrics/`
