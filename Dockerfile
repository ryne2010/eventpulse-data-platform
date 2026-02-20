# syntax=docker/dockerfile:1

############################
# Frontend build
############################
# Node LTS (keep current-ish; build stage only)
FROM node:22-alpine AS webbuilder
WORKDIR /app

# Workspace-aware install for reproducible builds.
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
RUN mkdir -p web
COPY web/package.json ./web/package.json

RUN corepack enable && pnpm install --frozen-lockfile

COPY web/ ./web/
RUN pnpm -C web build

############################
# Python runtime
############################
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install uv (pinned for reproducibility)
ARG UV_VERSION=0.9.21
RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}"

# Create non-root user
RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 appuser

WORKDIR /app

# Install dependencies from lockfile
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy backend source
COPY eventpulse ./eventpulse

# Contracts + demo data (read-only at runtime)
COPY data ./data

# Copy built frontend assets
COPY --from=webbuilder /app/web/dist ./web/dist

USER appuser

ENV PORT=8080
EXPOSE 8080

# Uvicorn: proxy headers are important on Cloud Run.
CMD ["sh", "-c", "uvicorn eventpulse.api_server:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips '*'"]
