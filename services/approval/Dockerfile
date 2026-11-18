# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS builder
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends curl libpq-dev gcc python3-dev && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv

COPY services/approval/pyproject.toml ./
RUN uv pip install --system --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    "sqlalchemy[asyncio]" \
    greenlet \
    asyncpg \
    pydantic \
    pydantic-settings \
    alembic \
    "pyjwt[crypto]" \
    cryptography \
    httpx \
    structlog \
    pyyaml

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl libpq5 && rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY libs/platform_contracts /app/libs/platform_contracts
COPY services/approval/app /app/app
COPY services/approval/migrations /app/migrations
COPY services/approval/alembic.ini /app/alembic.ini

RUN useradd -u 10001 -m appuser && chown -R appuser:appuser /app
USER 10001

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s CMD curl -f http://localhost:8000/health/ready || exit 1
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
