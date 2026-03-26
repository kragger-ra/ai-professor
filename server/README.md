# Server part installation

Server contains inner API for TTS, STT, filters and little LLM models (probably, maybe all later).

Open your linux / WSL terminal and STRICT follow the instructions. 

0. If on Windows: run WSL and then work there 
1. Install [conda / miniconda](https://docs.anaconda.com/miniconda/install/#quick-command-line-install) if you haven't already

Fast miniconda installation works for WSL

```bash
cd ~
mkdir -p ~/miniconda3
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O ~/miniconda3/miniconda.sh
bash ~/miniconda3/miniconda.sh -b -u -p ~/miniconda3
rm ~/miniconda3/miniconda.sh
source ~/miniconda3/bin/activate
conda init --all
```

2. Run commands

Prepare linux env

```bash
#
# Prepare linux env
#

sudo apt update
sudo apt upgrade

# (Ubuntu / Debian User) Install sox + ffmpeg
sudo apt install libsox-dev ffmpeg 

# (Ubuntu / Debian User) Install pyaudio 
sudo apt install build-essential \
    cmake \
    libasound-dev \
    portaudio19-dev \
    libportaudio2 \
    libportaudiocpp0
```

Create conda environment

```bash
# follow this guide (from [FishSpeech](https://speech.fish.audio/#requirements) installation linux guide)

# Conda env creating
conda create -n fish-speech python=3.10
```

Activate conda environment (maybe need later, remember the command)

```bash
conda activate fish-speech
```

Install torch + cuda & UV

```bash
# Activating fast packager uv (VERY FAST INSTALL)
pip install uv
uv pip install torch==2.4.1 torchvision==0.19.1 torchaudio==2.4.1 --index-url https://download.pytorch.org/whl/cu121
```

Install fish-speech

```bash
# Install fish-speech 
git clone this_repo_branch

cd this_repo_folder/server
mkdir data
cd data
git clone https://github.com/fishaudio/fish-speech.git



cd fish-speech
# your terminal needs to be in folder 'repo/server/data/fish-speech'
uv pip install -e .
# (if this not work try without 'uv')
```

Downloading TTS AI models (~1.5G).

```bash
# [optional 1: you can use another drive here for storaging big files. See below]

# Download models
# your terminal needs to be in folder 'repo/server/data/fish-speech'
# 1.5G models download
# huggingface-cli download fishaudio/fish-speech-1.5 --local-dir storage
# your terminal needs to be in folder 'repo/server/data/fish-speech'
huggingface-cli download fishaudio/fish-speech-1.5 --local-dir checkpoints/fish-speech-1.5
```

[optional] Run FishSpeech webui test

(run this to ensure all works fine)

```bash
#
# Running FishSpeech webui
# your terminal needs to be in folder 'repo/server/data/fish-speech'
#
python -m tools.run_webui \
    --llama-checkpoint-path "checkpoints/fish-speech-1.5" \
    --decoder-checkpoint-path "checkpoints/fish-speech-1.5/firefly-gan-vq-fsq-8x1024-21hz-generator.pth" \
    --decoder-config-name firefly_gan_vq \
    --compile

python -m tools.run_webui --compile
```

After start and loading go to http://localhost:7860 in browser and test all working.

## [OPTIONAL 1] Add yor another any windows drive path to storage big files.

Disk naming is like for D is mnt/d/

```bash
mkdir storage
sudo mount --bind /mnt/d/Pets/NetTyan/Python/NetTyanRepo/NetTyan/server/data/storage checkpoints
# https://stackoverflow.com/questions/45244306/mounting-a-windows-share-in-windows-subsystem-for-linux
```

## Uninstalling

If you have some errors you can uninstall this conda and install again, sometimes this may help.

```bash
# If you are in env fish-speech
conda deactivate

conda remove -n fish-speech --all 
```