FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN python -m pip install --no-cache-dir --upgrade pip uv

COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

COPY eventpulse ./eventpulse

# RQ worker listens on queue name "eventpulse"
CMD ["sh", "-c", "rq worker eventpulse --url ${REDIS_URL}"]
