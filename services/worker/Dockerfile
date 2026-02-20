FROM python:3.11-slim

ARG UV_VERSION=0.9.21

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install uv (pinned)
RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}"

# Non-root user
RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 appuser

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY eventpulse ./eventpulse

USER appuser

# RQ worker listens on queue name "eventpulse"
CMD ["sh", "-c", "uv run rq worker eventpulse --url ${REDIS_URL}"]
