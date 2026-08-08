# Structure Gate API (FastAPI) for Cloud Run / container hosts.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PYTHONIOENCODING=utf-8 \
    PORT=8080 \
    QRESEARCH_UI_HOST=0.0.0.0 \
    QRESEARCH_UI_PORT=8080 \
    QRESEARCH_CORS_ORIGINS=* \
    QRESEARCH_SG_PAPER_ONLY=1 \
    QRESEARCH_FUTU_ALLOW_LIVE=0

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml README.md ./
COPY src ./src
COPY examples ./examples

RUN pip install --no-cache-dir -U pip \
 && pip install --no-cache-dir -e ".[futu,web]"

EXPOSE 8080

# Cloud Run injects PORT.
CMD exec python -m uvicorn qresearch.web.paper_app:app --host 0.0.0.0 --port ${PORT}
