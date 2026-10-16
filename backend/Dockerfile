# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.11.2 AS uv
FROM python:3.13-slim AS build
COPY --from=uv /uv /uvx /bin/
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app/backend
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

FROM python:3.13-slim AS runtime
ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    APP_DATA_DIR=/app/data/runtime \
    APP_DATABASE_PATH=/app/data/runtime/mianshiagent.sqlite3
RUN useradd --create-home --uid 10001 app
WORKDIR /app/backend
COPY --from=build /app/backend/.venv ./.venv
COPY --from=build /app/backend/src ./src
RUN mkdir -p /app/data/runtime && chown -R app:app /app/data
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["uvicorn", "mianshi_agent.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
