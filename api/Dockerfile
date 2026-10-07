FROM python:3.11-slim

# ffmpeg decodes whatever the user drops in (mp3/m4a/ogg/mp4) to 16 kHz WAV.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

# Models are large (~1.7 GB) and are mounted at runtime, not baked into the image.
ENV MODELS_DIR=/app/models
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
