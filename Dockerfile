### Build frontend (React + TanStack)
FROM node:20-alpine AS frontend

WORKDIR /app/web
RUN corepack enable
COPY web/package.json ./
RUN pnpm install --no-frozen-lockfile
COPY web/ ./
RUN pnpm build


### Backend (FastAPI)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir --upgrade pip uv

COPY pyproject.toml ./

RUN uv sync --no-dev --no-install-project

COPY eventpulse ./eventpulse

# Copy built UI into /app/web/dist so the API can serve it
COPY --from=frontend /app/web/dist ./web/dist

EXPOSE 8080

CMD ["uvicorn", "eventpulse.api_server:app", "--host", "0.0.0.0", "--port", "8080"]
