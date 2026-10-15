# QR AI Lab backend / scheduler image (same image, different command).
# Build (context = repo root, because backend depends on libs/preprocess):
#   docker compose -f infra/docker-compose.yml --profile app build
#   docker build -t qr-ai-lab/backend:dev -f infra/backend/Dockerfile .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY libs/preprocess /libs/preprocess
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
