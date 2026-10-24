FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/cache/huggingface \
    TRANSFORMERS_CACHE=/cache/huggingface \
    HUGGINGFACE_HUB_CACHE=/cache/huggingface \
    TORCH_HOME=/cache/torch \
    TTS_DEVICE=cuda \
    PORT=8965

WORKDIR /app

# System deps: ffmpeg/ffprobe for pydub; libgomp for torch
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libgomp1 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# CUDA PyTorch wheels (requires NVIDIA Container Toolkit + compatible host driver)
RUN pip install --upgrade pip \
    && pip install --index-url https://download.pytorch.org/whl/cpu \
        torch==2.6.0 \
        torchaudio==2.6.0

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY . /app

RUN mkdir -p /cache/huggingface /cache/torch /app/voices/cache /app/voices/generated

EXPOSE 8965

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8965}"]
