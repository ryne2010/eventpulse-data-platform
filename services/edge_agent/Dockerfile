# syntax=docker/dockerfile:1

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Non-root user (good practice on RPi)
RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 appuser

WORKDIR /app

# Install minimal runtime dependencies.
COPY services/edge_agent/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt

# Copy only what we need for the agent runtime.
COPY services/edge_agent ./services/edge_agent

USER appuser

CMD ["python", "services/edge_agent/agent.py"]
