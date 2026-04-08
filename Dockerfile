# Backend container for cpu-analytics.
#
# Build context: cpu-analytics/ (the directory containing this file).
# The frontend, the .venv, and the data/processed/*.parquet files are excluded
# via .dockerignore. Parquet files are downloaded at runtime by data_loader.py
# from a GitHub Release asset (URLs set via Fly env vars).

FROM python:3.12-slim-bookworm

# System deps: only what's needed at runtime. duckdb wheels are self-contained.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first to maximize Docker layer cache hits.
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Application code.
COPY backend /app/backend

# data/processed/ is created at runtime by data_loader on first request.
RUN mkdir -p /app/data/processed

# Bind to PORT env var at runtime. Render assigns a random port per service
# and sets PORT in the environment. Fly.io maps internal_port via fly.toml.
# Local dev and the fly.toml path use 8000 as the fallback.
EXPOSE 8000

CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
