# Konzei Clips web starter: single-instance FastAPI + FFmpeg.
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 KONZEI_PUBLIC_MODE=1 KONZEI_DATA_DIR=/app/data KONZEI_MAX_UPLOAD_GB=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libgomp1 libgl1 fonts-dejavu-core ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r /app/requirements.txt
COPY . /app
RUN test -f /app/static/index.html \
 && test -f /app/static/app.js \
 && test -f /app/static/style.css
RUN mkdir -p /app/data
EXPOSE 8765
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8765} --workers 1"]
