FROM python:3.13-slim

# libgomp1 is required at runtime by scikit-learn's OpenMP-based routines.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# uv for fast, reproducible dependency installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY . .

# Snapshot cache dir — mount this as a volume to persist/reuse cached
# Snowflake query results across runs (see data/ in CLAUDE.md).
RUN mkdir -p data

CMD ["python", "inference.py"]
