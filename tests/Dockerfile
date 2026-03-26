FROM nvidia/cuda:11.8.0-devel-ubuntu22.04

WORKDIR /app

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    build-essential \
    ninja-build \
    git \
    && rm -rf /var/lib/apt/lists/*


RUN pip3 install --upgrade pip setuptools wheel packaging

RUN pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

ENV CUDA_HOME="/usr/local/cuda"
ENV PATH="/usr/local/cuda/bin:${PATH}"

RUN pip3 install flash-attn --no-build-isolation
RUN pip3 install transformers pillow

COPY vlm_test.py .
COPY maxresdefault.jpg .

RUN chmod +x vlm_test.py

CMD ["python3", "vlm_test.py"]