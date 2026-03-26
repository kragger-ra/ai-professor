# NeuroDeva - TTS Branch

- [NeuroDeva - TTS Branch](#neurodeva---tts-branch)
  - [Warning 11.01.2025](#warning-11012025)
  - [Launch algorithm](#launch-algorithm)
  - [Configuration](#configuration)
  - [TTS System Overview](#tts-system-overview)
  - [Updates](#updates)
    - [Latest](#latest)
      - [Main app parameters description](#main-app-parameters-description)
      - [New About installation](#new-about-installation)
  - [AutoFormat](#autoformat)
    - [21.11.2024](#21112024)
    - [13.11.2024](#13112024)
    - [23.10.2024](#23102024)
  - [System Requirements](#system-requirements)
  - [Quick Start](#quick-start)
- [Original Project](#original-project)
- [About env prepare](#about-env-prepare)

## Warning 11.01.2025

> [!CAUTION]
> <details><summary>ON AGENT RAG ERROR 11.01.2025 ⚠️</summary>
>
> Код может вылетать после каждого запуска агента (без видимых ошибок) из-за кривой реализации библиотеки FAISS
>
> Если вы обновили репозиторий после 10.01.2025 и он не запускается при активации агента, значит проблема здесь
>
> Для решения проблемы нужно удалить папку `this_repo/data/rag_vector_store`
>
> Это сбросит кэш раг-системы (при первом запуске она туда кэшируется и потом берёт оттуда кэш, а если документы в раге меняются, то этот кэш невалидный, потом случается ошибка внутри FAISS, которая никак не документируется и не отслеживается)
>
> В случае появления проблемы снова после обновлений репозитория повторите процедуру.
> </details>

## Launch algorithm

1. LM studio launch
2. Minecraft launch
3. OBS launch
4. VTube Studio Launch
5. SheepChat launch
6. cd this_repo/src
7. python main.py
8. Enable agent checkbox & start agent button

## Configuration

data/HyperAI_DATABASE.db
.env (example)

```env
MistralApiKey=""
DONATIONALERTS_TOKEN=""
# EXTRA-PRIVATE!!!
YOUTUBE_STREAM_API_KEY="w"  # NetTyan googleapi app
# YOUTUBE_CHANNEL_ID="UChs0pSaEoNLV4mevBFGaoKA"  # TEST (music audio)
YOUTUBE_CHANNEL_ID="UCy6HXAVZo3X9W3q9SrCPInQ"  # NetTyan 
YOUTUBE_VIDEO_ID="36YnV9STBqc"
VIDEO_ID="36YnV9STBqc"

TWITCH_APP_SECRET=""
TWITCH_TARGET_CHANNEL="nettyan_ai"
TWITCH_APP_ID=""

DiscordToken = '.GjK-'
TrovoClientID = ""
TrovoAccessToken= "-"

MODEL_NAME=saiga_nemo_12b_gguf
RAZRABS=Razrab0,Razrab1
BOT_NICKNAMES=NicksOfStreamer1,NicksOfStreamer2
BOT_RELATIVES_L1=ботиха,тянка,тян,нитан,нтян,бот,ии,bot,gpt,chatgpt,ai,chatbot
BOT_RELATIVES_L2=интеллект,разум,помощник
lm_studio_api_ext = "http://localhost:22227/v1"
lm_studio_api = "http://localhost:22227/v1"
model_name_ext = saiga_nemo_12b_gguf
embeddings_model=text-embedding-user-bge-m3
model_name_full=IlyaGusev/saiga_nemo_12b_gguf/saiga_nemo_12b_gguf.gguf
```

## TTS System Overview

The TTS system is responsible for converting generated text responses from LLM into natural-sounding speech output. It integrates with:

- Silero TTS Model Integration
- Real-time lip sync with Live2D model
- Audio processing and routing
- WebSocket-based VTube Studio integration

<!-- UPDATES -->
## Updates

### Latest

15.03.2025 UPD: run `python main.py -rof` to disable filter and STT.

To use code agent use --code, to use standart coreagent don't use anything.

Always add -o (because you are not streamer) to disable social APIs.

Main run:

```bash
cd this_repo/src
python main.py
```

Run docker fishspeech & filters:

```bash
cd this_repo/docker/filter
docker-compose up --build
```

Interface controller located at `http://localhost:22228`

#### Main app parameters description

```python
parser.add_argument(
    "-l", "--old", action="store_true", help="Run old autogpt agent"
)
parser.add_argument(
    "-c", "--code", action="store_true", help="Run smolagents codeagent"
)
parser.add_argument(
    "-r",
    "--no-stt",
    action="store_true",
    help="Speech to text start",
)
parser.add_argument(
    "-f",
    "--no-filter",
    action="store_true",
    help="Disable filtering",
)
parser.add_argument(
    "-s",
    "--stop-auto",
    action="store_true",
    help="Do not start agent automatically",
)
parser.add_argument(
    "-o",
    "--offline",
    action="store_true",
    # default=False,
    help="Dont start social services",
)
parser.add_argument(
    "-w",
    "--warmup",
    action="store_true",
    default=False,
    help="Do TTS warmup after start",
)
```

#### New About installation

We are now working in **LM Studio** as main openai-like LLM inference provider.

- Download latest beta for your system from [here](https://lmstudio.ai/beta-releases)
- Start LM studio
- Download our using saiga-nemo [model](https://model.lmstudio.ai/download/IlyaGusev/saiga_nemo_12b_gguf) in LM studio
- Start server on port 22227 in developer page LM Studio GUI
- Now you can run our python code!

## AutoFormat

```bash
cd repo
black src
isort --profile=black src
```

### 21.11.2024

Added Docker-based VLLM API server for local LLM hosting, added instructions for launch.
Vllm Setup:
Ensure cuda availability:

```bash
docker run --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

In separate terminal run:

```bash
cd vllm_docker
docker-compose up --build
```

### 13.11.2024

New tts pipeline configured, instead of silero it is decided upon edge_tts -> moe_tts conversion.

GRADIO add. You can auto-reload code and use gradio to see changes in-time.
Use `gradio main.py`
and if you change the code, gradio app will reload.

But also you can do older `python main.py`, it will work too.

To enter gradio interface (if app is started), open this adress in any your browser:

`http://localhost:22228`

### 23.10.2024

Major code refactoring. Improved project structure, edited some parts (specifically fredt5 class), better separation of concerns, proper async/await implementation, enhanced error handling.

## System Requirements

| Component | Requirement                                  |
| --------- | -------------------------------------------- |
| Python    | 3.10.9                                       |
| RAM       | 10+ GB                                       |
| Audio     | Virtual Cable support                        |
| OS        | Windows 10/11 (Linux untested, but may work) |
| Memory    | 30+ GB                                       |

<!-- Quick Start -->
## Quick Start

1. Clone the repo

   ```bash
   git clone -b tts_tests https://github.com/3ndetz/NeuroDeva.git
   ```

2. Install the required packages:

   ```bash
   cd NeuroDeva
   ```

   ```bash
   pip install -r requirements.txt
   ```

3. VTube Studio Setup (optional, to see the avatar):

   - Install Vtube studio app through Steam

   - Enable Plugin API (port 8001)
   - Configure lip sync parameters

4. Vllm Setup:
  Ensure cuda availability:

  ```bash
  docker run --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
  ```

  In separate terminal run:

  ```bash
  cd vllm_docker
  docker-compose up --build
  ```

# Original Project

For full project context, see main branch and Habr article.

# About env prepare

TODO перейти на poetry, conda или куда-то, где не будет проблем...

0. Создать и активировать venv для проекта. В VS Code или в консоли, как удобно.

1. `cd path/to/repo`

2. `pip3 install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu118`

3. `pip install -r requirements.txt`

В случае проблем с лангчейном:

(UPD 15.04.2025 - новое)

`pip install langchain==0.3.23 langchain-core==0.3.52 langchain-community==0.3.8 langchain-openai==0.3.13 -U`
