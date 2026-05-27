# Локальные эмбеддинги (опционально)

Папка для модели эмбеддингов, если хочешь работать **полностью локально**
без облачного провайдера. По умолчанию RAG идёт через OpenAI
text-embedding-3-small (через `OPENAI_API_KEY`) и этот файл не нужен.

## bge-m3 GGUF

`setup.bat` качает сюда `bge-m3/user-bge-m3-q4_k_m.gguf` (261 МБ) с
HuggingFace (`cm4ker/USER-bge-m3-Q4_K_M-GGUF`). Это бекап-вариант для
LM Studio: установи LM Studio (https://lmstudio.ai/), укажи в его
настройках **Models directory** = эту папку (или скопируй файл в
обычную LM Studio директорию моделей), запусти сервер на :22227,
впиши в `.env`:

```
EMBEDDINGS_MODEL="text-embedding-user-bge-m3"
EMBEDDINGS_API_BASE="http://localhost:22227/v1"
EMBEDDINGS_API_KEY="sk-1234"
```

Имя `text-embedding-user-bge-m3` — то, что LM Studio автоматически
присваивает модели из `cm4ker/USER-*` репо.

## Зачем именно эта версия

Q4_K_M квант от `cm4ker` — компактный (261 МБ против 635 МБ Q8_0) и
даёт приемлемое качество для русского с минимальным VRAM.

## Если не нужно

Можно вызвать `setup.bat --no-bge-m3`, либо удалить файл вручную после
установки — приложение без него работает на облачных эмбеддингах.
