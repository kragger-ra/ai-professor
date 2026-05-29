# Troubleshooting

Известные проблемы и обходы. Если симптом не из списка — лог тьютора
лежит в `tutor_v2.log`, борд пишет в `data/board_events.jsonl` и cmd-
окно «AI Professor Board».

## Установка

### `setup.bat`: «Python 3.10 not found»

Установи Python **строго 3.10** с
https://www.python.org/downloads/release/python-31011/
с галочкой «Add to PATH» и «Install py launcher». 3.11+ не работает
(зафиксированы зависимости).

### `pip install` падает на `stressrnn` / `git`

`stressrnn` устанавливается из GitHub. Если в Windows нет `git` в
PATH, поставь его: https://git-scm.com/download/win — после этого
перезапусти `setup.bat`.

### `pip install` падает на `PySide6`

PySide6 ~370 МБ. Возможные причины:
- Кончилось место на диске.
- Сетевая блокировка (PyPI или Qt-сервера). Попробуй с VPN.
- Старая версия pip. Скрипт уже апгрейдит, но если запускал вручную:
  `.venv\Scripts\python.exe -m pip install --upgrade pip`.

## Запуск

### `start_tutor_v2.bat`: «TTS did not start within 3 minutes»

Vosk-TTS сервер не поднялся. Проверь:
- Файлы Vosk-моделей по пути из `vosk_tts_server/`.
- Свободен ли порт 22232 (`netstat -an | findstr 22232`).
- Лог: `vosk_tts.log` в корне репо.

Если сервер не нужен (хочешь только текстовый чат) — закомментируй
блок Vosk в `start_tutor_v2.bat` или скажи `set TTS_BACKEND=` перед
запуском.

### «LM Studio (:22227) not responding»

Это warning, не fatal. По умолчанию эмбеддинги RAG идут через облако
(`text-embedding-3-small` на том же `OPENAI_API_KEY`), поэтому поиск по
курсу работает и без LM Studio. LM Studio нужен только для полностью
локального стека (`USE_LOCAL_LLM=true` + `EMBEDDINGS_MODEL=...bge-m3` на
`:22227`).

### Тьютор стартует, но молчит

- Микрофон выбран правильно? Проверь имя устройства в `.env`
  (`SOUND_DEVICE_IN`) или через UI: **Звук → Аудио-режим**.
- В meeting-режиме Zoom Speaker должен быть `CABLE Input`, иначе
  звук собеседника не попадает в STT тьютора.
- Whisper модель ещё качается на первой загрузке (~600 МБ).

### Whisper не использует GPU

Если в логе `[STT] Loaded ... on cpu`, GPU не используется. Причины:
- Драйвер NVIDIA не установлен.
- В `.env`: `STT_COMPUTE_DEVICE="cuda"` (по умолчанию).
- Не установлен `onnxruntime-gpu` (опциональный extras).

Поправить:
```bat
.venv\Scripts\python.exe -m pip install -e ".[gpu]"
```

CPU-режим работает, просто транскрипция длиннее в 3-5 раз.

## API / LLM

### «Incorrect API key provided»

Проверь:
- Активный провайдер в **Файл → Настройки подключений** соответствует
  тому, ключ к которому ты вписал.
- Ключ актуальный (не отозванный, с остатком на балансе).
- Для Yandex GPT — впиши и `YANDEX_API_KEY`, и `YANDEX_FOLDER_ID`.

### «Rate limit exceeded»

Либо провайдер задросселил, либо у тебя slow tier. Снизь нагрузку:
- В UI **Звук → Заглушить TTS** (Ctrl+M) — модель всё ещё дёргается,
  но реже.
- В `.env` переключись на дешёвую модель: `gpt-4o-mini`,
  `claude-3-5-haiku-20241022`, `deepseek-chat`.

### Yandex GPT — «Folder ID required»

Yandex API требует помимо ключа ID каталога (folder). Возьми из
консоли облака → AI Studio → API. Впиши в **Файл → Настройки
подключений → Yandex Folder ID** или в `.env`:
```
YANDEX_FOLDER_ID="b1g..."
```

## Аудио

### Тьютор слышит сам себя

- В UI **Звук → Аудио-режим** должно быть «Локальный (микрофон /
  динамики)», а не «Режим созвона». В созвоне иначе настроена
  маршрутизация.
- В обычном режиме VAD-гейт повышается во время TTS, но если динамики
  играют ОЧЕНЬ громко — может прорваться. Снизь VOSK громкость или
  переходи на наушники.

### Микрофон не определяется

`python -c "import sounddevice as sd; print(sd.query_devices())"`
покажет все устройства. Скопируй точное имя в `.env`:
```
SOUND_DEVICE_IN="(3- fifine Microphone)"
```
Достаточно substring — `fifine` обычно тоже сработает.

## Видео

### Транскрипция падает на «ffmpeg not found»

Faster-Whisper для извлечения аудио использует `ffmpeg` через
`pydub`. Поставь ffmpeg:
- Windows: https://www.gyan.dev/ffmpeg/builds/ — добавь `bin/` в PATH.
- Linux: `sudo apt install ffmpeg`.
- Mac: `brew install ffmpeg`.

### Транскрипция «висит»

Прогресс-бар нулевой, но Whisper работает в фоне. Долгое видео + CPU
+ короткий ход — типичная ситуация. Подожди или переключи на GPU.

## Доска (board)

### Меркает блок Mermaid вместо схемы

- Перезапусти борд (CSS / JS могут быть закешированы).
- Открой Alt+D в борде — увидишь диагностический оверлей с
  сообщением от Mermaid, если рендер упал.
- Сложный синтаксис Mermaid (вложенные узлы, кастомные стили) может
  не поддерживаться нашей версией 10.9.1.

### Иконки слишком маленькие

В **Файл → Настройки подключений…** нет — это про API. Размер шрифта
ставится в `board/app.py` (`QFont("Segoe UI", 11)`). Можно поднять до
12-13 для большей читаемости, потребуется пересборка venv через
`pip install -e .` (или просто перезапуск, если правил по месту).

## Тесты и волонтёры

### Профессор помнит чужие данные

Если на чистой машине профессор ссылается на кого-то постороннего —
память не очищена. Запусти `reset_memory.bat` (чистит
`data/session_memory.json` и `data/student_profile.json`).
