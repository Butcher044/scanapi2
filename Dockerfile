# ─── Stage 1: Build React frontend ───────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --prefer-offline 2>/dev/null || npm install

COPY frontend/ .
RUN npm run build


# ─── Stage 2: Python + Playwright runtime ─────────────────────────────────────
# Official Microsoft Playwright image — Chromium + all deps pre-installed
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source
COPY app/            ./app/
COPY bank_api_parser/ ./bank_api_parser/
COPY migrations/     ./migrations/
COPY config.yaml     ./config.yaml
COPY run.py          ./run.py

# React build output
COPY --from=frontend-builder /frontend/dist ./frontend/dist

# Snapshot storage (mount as Docker volume in production)
RUN mkdir -p /app/bank_api_parser/snapshots

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    DATABASE_HOST=postgres \
    DATABASE_PORT=5432 \
    DATABASE_USER=user \
    DATABASE_PASSWORD=1111 \
    DATABASE_DB=system_monitoring \
    TELEGRAM_BOT_TOKEN="" \
    SCHEDULER_TIME="10:00" \
    DASHBOARD_HOST="0.0.0.0" \
    DASHBOARD_PORT=8080 \
    MIGRATIONS_DIR=/app/migrations

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8080/api/summary || exit 1

CMD ["python", "run.py"]
