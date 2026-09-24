# ─── Stage 1: Build React frontend ───────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ .
RUN npm run build


# ─── Stage 2: Python runtime ─────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/             ./app/
COPY bank_api_parser/ ./bank_api_parser/
COPY certs/           ./certs/
COPY migrations/      ./migrations/
COPY config.yaml      ./config.yaml
COPY run.py           ./run.py
COPY --from=frontend-builder /frontend/dist ./frontend/dist

RUN useradd --system --no-create-home bankmon
USER bankmon

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    MIGRATIONS_DIR=/app/migrations

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4)" || exit 1

CMD ["python", "run.py"]
