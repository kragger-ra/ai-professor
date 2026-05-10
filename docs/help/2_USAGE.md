
# 2_Usage

## 1. Run workers

ШАГ НУЖЕН только если хотите Fish TTS и/или СИСТЕМУ ФИЛЬТРАЦИИ

### 1.1 Docker Fish TTS + Filters

See in [installation](0_INSTALLATION.md) how to setup docker. Same command for run. Ensure containers are running BEFORE running main script.

### 1.2 Simple TTS server (NO Docker)

Вариант для ПРОСТОЙ более "слабой" версии TTS без интонаций и т.д.
Откройте отдельный терминал, выполните пункты этого файла 4.1, 4.2, 4.3.

## 2. Run game

Start Minecraft with the mod autoclef with latest [release](https://github.com/3ndetz/autoclef/releases) installed. Ensure `altoclef` mod is in `mods` folder.

## 3. Configure .env

Удостоверьтесь, что вы правильно настроили `.env` файл.
После любых изменений в нём нужно:

- открыть НОВЫЙ терминал
- закрыть старый и старую программу, если была запущена.

В некоторых случаях требуется ПОЛНОСТЬЮ перезапустить VS Code или даже систему, если `.env` не обновился или изменена системная переменная пути.

## 4. Running script

### 4.0. Зайдите в папку репозитория из терминала

`cd этот_репозиторий` или где у вас папка с этим проектом.

### 4.1. Activate venv if not yet activated

For example, activating venv for windows

```bash
.venv\Scripts\activate
```

For linux / macOS

```bash
source .venv/bin/activate
```

### 4.2. Optional: Start simpletts server

If you DON'T using Fish TTS from Docker, RUN this simple version of TTS.

```bash
python simple_tts_server.py
```

And wait for starting, downloading and installing models.
You may need a proxy if not downloading.

Do NOT **stop** the terminal console where it is running! This server should run in a background.

### 4.3. Run main script

Option 1:

```bash
cd src
python main.py [params]
```

Option 2:

```bash
uv run nettyan [params]
```

Available params:

- `r` - disable STT (Speech to text)
- `o` - disable twitch chat listener
- `f` - disable filter
- `s` - do not start agent automatically
- `l` - use simple chat agent

Dry test run only with simple game chat agent:

```bash
python main.py -rofl
```

Example run with many params, disabled twitch and filter:

```bash
python main.py -of
```

Full params, 100% actual latest params can be found in `src/main.py`.
(прямо в коде прописаны параметры и описания)

## Финал

Вы попробовали использовать скрипт и он у вас запустился, теперь можете вернуться в [содержание](index.md) и оттуда перейти к КАСТОМИЗАЦИИ.
