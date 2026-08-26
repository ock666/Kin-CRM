FROM python:3.11-slim

# System deps: libmagic/jpeg libs help Pillow (a transitive dep of instagrapi) build/run smoothly.
# Build deps are purged after pip install to keep the final image lean and reduce attack surface.
WORKDIR /app

COPY requirements.txt .

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    curl \
    gosu \
    tzdata \
    ffmpeg \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y build-essential libjpeg62-turbo-dev zlib1g-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY app ./app

# Persistent data lives here - mount a volume at /data in production.
ENV DATA_DIR=/data
RUN mkdir -p /data

COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
