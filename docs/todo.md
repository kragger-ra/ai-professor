
# TODO TEST & INTEGRATE NEW S1 TTS


TTS Docker

Исходя из их доки https://speech.fish.audio/inference/#docker-inference 

запускать так

22231


cd docker\filter\

docker compose up --build

НЕ ЗАПУСТИЛСЯ С ОШИБКЙО

Error response from daemon: failed to create task for container: failed to create shim task: OCI runtime create failed: runc create failed: unable to start container process: error during container init: error running prestart hook #0: exit status 1, stdout: , stderr: Auto-detected mode as 'legacy'
nvidia-container-cli: initialization error: WSL environment detected but no adapters were found: unknown

надо ENSURE DOCKER CUDA SUPPORT

https://docs.nvidia.com/cuda/wsl-user-guide/index.html -> https://docs.nvidia.com/ai-enterprise/deployment/vmware/latest/docker.html -> https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html#installing-the-nvidia-container-toolkit


порты inner outer

TODO посмотреть новая конфига для S1-mini

docker run -d \
    --name fish-speech-webui \
    --gpus all \
    -p 7860:7860 \
    -v ./checkpoints:/app/checkpoints \
    -v ./references:/app/references \
    -e COMPILE=1 \
    fishaudio/fish-speech:latest-webui-cuda