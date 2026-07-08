FROM python:3.11-slim
WORKDIR /app

# Install system dependencies for Moonshine (ONNX Runtime) and Opus
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopus0 \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download Moonshine STT model (English Base)
RUN python -m moonshine_voice.download --stt --language en 2>/dev/null || true

COPY . .

# Ensure data directories exist
RUN mkdir -p /app/data/moonshine_cache

CMD ["python", "-m", "bot.main"]