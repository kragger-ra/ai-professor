```bash
cd docker
docker-compose up --build
```

docker build -t realtimetts-app .
docker run -it --name realtimetts --gpus all -p 7860:7860 realtimetts-app

docker run -it --name fish-speech --gpus all -p 7860:7860 fishaudio/fish-speech:latest-dev zsh
export GRADIO_SERVER_NAME="0.0.0.0"
python tools/run_webui.py --compile