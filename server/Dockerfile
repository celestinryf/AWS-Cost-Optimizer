# ---- Build stage: install dependencies ----
FROM python:3.13-slim AS builder
WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Runtime stage ----
FROM python:3.13-slim AS runtime

# Non-root user for security
RUN addgroup --system app && adduser --system --ingroup app app

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY app/ ./app/

# Data directory for SQLite — mount a volume here in production
RUN mkdir -p /data && chown app:app /data

USER app

# Environment defaults — override at runtime via env vars or docker-compose
ENV RUNS_DB_PATH=/data/runs.db \
    API_PREFIX=/api/v1 \
    ENVIRONMENT=production \
    APP_NAME=aws-cost-optimizer-api \
    CORS_ORIGINS=http://localhost:3000

EXPOSE 8000

# --workers 1: SQLite Lock is process-local. Multiple workers would each have
# their own lock and can corrupt the database. Increase workers only after
# migrating to a server database (Postgres, RDS, etc.).
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--no-access-log"]
