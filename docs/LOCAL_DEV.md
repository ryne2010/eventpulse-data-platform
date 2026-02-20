# Local development (macOS, M2 Max)

This repo supports two common workflows.

---

## Option A: Docker Compose (recommended)

Copy the example env file:

```bash
cp .env.example .env
```

> Note: `.env.example` is configured for Docker Compose service DNS names
> (`postgres`, `redis`). If you want to run the API on your host (hybrid lane),
> use `.env.host.example` (or export env vars as shown below).

### Internal endpoints (optional but recommended)

Some capabilities are intentionally gated behind internal auth (task token or Cloud Run IAM):

- GCS signed uploads (`/api/uploads/gcs_signed_url`)
- Register existing GCS objects (`/api/ingest/from_gcs`)
- Incoming file listing (`/api/incoming/list`)
- Ingest from INCOMING_DIR path (`/api/ingest/from_path`)
- Contract editing (`PUT /api/datasets/<dataset>/contract`)
- Ops actions (`/internal/admin/*`)

For local dev, `.env.example` sets a **local-only** default:

```bash
TASK_TOKEN=devtoken
```

You can change it to any value (it’s just a shared-secret for internal endpoints).

…and (optionally) enable features:

```bash
ENABLE_SIGNED_URLS=true
ENABLE_INCOMING_LIST=true
ENABLE_CONTRACT_WRITE=true
```

Then in the UI **Ops** page, set the same task token so the browser can call internal endpoints.

Start the stack:

```bash
make up
```

### Data directory permissions (Compose lane)

For better security parity with Cloud Run, the API/worker containers run as a **non-root** user by default.

`make up` automatically runs:

```bash
make init-data
```

That target:

- creates the required bind-mounted directories under `./data/`
- makes `data/raw`, `data/archive`, `data/incoming`, and `data/contracts` writable
- **does not touch** `data/pg` (Postgres is strict about its data directory permissions)

If you hit a permissions error during local dev, re-run:

```bash
make init-data
```

Optional watcher:

```bash
make watch
```

Optional edge-agent (simulated RPi telemetry):

```bash
make edge-up
```

UI: `http://localhost:8081`

---

## Option B: Hybrid (containers for DB/Redis, run API locally)

This is often faster for Python iteration.

1) Start Postgres + Redis:

```bash
docker compose up -d postgres redis
```

2) Install deps:

```bash
uv sync --dev
```

3) Configure env vars (choose one):

**Option B1 (quick): export env vars**

```bash
export DATABASE_URL='postgresql://postgres:eventpulse@localhost:5432/eventpulse'
export REDIS_URL='redis://localhost:6379/0'
export STORAGE_BACKEND=local
export RAW_DATA_DIR='./data/raw'
export CONTRACTS_DIR='./data/contracts'
export INCOMING_DIR='./data/incoming'
export ARCHIVE_DIR='./data/archive'
```

**Option B2 (repeatable): use the host template**

```bash
cp .env.host.example .env
set -a; source .env; set +a
```

4) Run the API:

```bash
uv run uvicorn eventpulse.api_server:app --reload --port 8081
```

5) Run the worker:

```bash
uv run rq worker eventpulse --url $REDIS_URL
```

---

## Frontend dev loop

```bash
corepack enable
pnpm install
pnpm -C web dev
```

Vite will proxy API calls to the backend (see `web/vite.config.ts`).

---

## Debugging & recovery

### Clean local artifacts

If you switch branches a lot (or change Node/Python versions) and run into weird tooling errors:

```bash
make clean
```

### Reclaim stuck ingestions

If an ingestion is stuck in `PROCESSING` (e.g., worker crash after claiming), reclaim and re-enqueue it:

```bash
make reclaim-stuck
```
