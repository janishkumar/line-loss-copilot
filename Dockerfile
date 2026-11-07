# API image: read-only FastAPI service over the Postgres marts.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.14 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first so code changes reuse this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY config ./config

EXPOSE 8000
CMD ["uvicorn", "linecopilot.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
