FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN python -m pip install --no-cache-dir --upgrade pip uv

COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

COPY services/watcher ./services/watcher
COPY eventpulse ./eventpulse

CMD ["python", "/app/services/watcher/watcher_main.py"]
