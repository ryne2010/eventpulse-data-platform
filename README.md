# EventPulse Data Platform (Local‑First)

## Quickstart

Local-first dev (recommended):

```bash
make doctor
make up
```

Optional GCP demo deploy:

```bash
make init GCLOUD_CONFIG=personal-portfolio PROJECT_ID=YOUR_PROJECT_ID REGION=us-central1
make auth          # only needed once per machine/user
make doctor-gcp
make deploy-gcp
```

EventPulse is a **local‑first reference implementation** of an event-driven data platform you can run on your laptop with Docker.
It demonstrates production-grade patterns you can reuse in cloud environments (GCP, AWS, Azure) while keeping the local developer
experience simple.

This repo focuses on:

- **Replayable ingestion**: immutable raw landing zone + idempotent processing
- **Schema drift handling**: detect column changes and apply a drift policy (warn/fail/allow)
- **Data quality gates**: required fields, types, uniqueness, null thresholds, numeric ranges
- **Curated warehouse tables**: upsert into typed tables with lineage metadata
- **Operational visibility**: ingestion status + quality reports + drift reports via API
- **Optional GCP path**: design notes + Terraform skeleton for Cloud Run / Pub/Sub / BigQuery patterns

> ⚠️ This is a **reference implementation**, not a complete enterprise product. It is intentionally easy to read, fork, and adapt.

---

## Quickstart (Local)

### 1) Prereqs
- Docker + Docker Compose

Optional (for local scripting / linting):
- Python 3.11+
- **uv** (`pip install uv`)

### 2) Start the stack
```bash
make up
```

Services started:
- UI (React + TanStack): http://localhost:8081
- API (base): http://localhost:8081/api
- Swagger docs: http://localhost:8081/docs
- Postgres (metadata + curated tables): localhost:5432
- Redis (queue): localhost:6379
- Worker: background job processor
- (Optional) Watcher: directory polling → auto-ingest (see below)

Home page demo:
- The home page map + charts are powered by **curated parcels** (synthetic recorder-style sales) limited to 50 rows.
- If the table is empty, click **Seed 50 parcels** on `/` (or call `POST /api/demo/seed/parcels?limit=50`).
  - Seeding is split into multiple ingestions of **≤15 parcels each** so pipeline activity previews have rows per ingestion.

### Troubleshooting

If the API fails to start with:

```
psycopg2.OperationalError: could not translate host name "postgres" to address
```

it usually means the `postgres` container ended up in a stale/broken networking state. Fix by recreating the dependency containers:

```bash
docker compose up -d --force-recreate postgres redis
docker compose up --build
```

### 3) Generate sample files and ingest
Generate a baseline Excel file and a drifted Excel file into `./data/incoming/`:
```bash
uv sync --dev
uv run python scripts/generate_sample_data.py --out ./data/incoming --rows 500
```

Ingest one file (calls the API and queues processing):
```bash
curl -s -X POST "http://localhost:8081/api/ingest/from_path" \
  -H "Content-Type: application/json" \
  -d '{"dataset":"parcels","relative_path":"parcels_baseline.xlsx","source":"demo"}' | jq
```

List ingestions:
```bash
curl -s "http://localhost:8081/api/ingestions?limit=20" | jq
```

Fetch details + quality report:
```bash
INGESTION_ID="<copy-from-list>"
curl -s "http://localhost:8081/api/ingestions/${INGESTION_ID}" | jq
```

Preview curated data:
```bash
curl -s "http://localhost:8081/api/datasets/parcels/curated/sample?limit=10" | jq
```

### Optional: auto-ingest by watching `./data/incoming`
Start the watcher container (polls and ingests new files automatically):
```bash
docker compose --profile watch up --build  # (or wire a Make target)
```

Drop new files into `./data/incoming/` and they will be ingested automatically.

---

## UI development (React + TanStack)

The API container serves a built UI at `/` for convenience.

If you want a fast local dev loop:

```bash
# Terminal 1
docker compose up --build

# Terminal 2
cd web
corepack enable
pnpm install
pnpm dev
```

Open: http://localhost:5174

---

## Key Concepts

### Raw landing zone
All inbound files are copied into an immutable raw structure:

```
data/raw/<dataset>/<YYYY-MM-DD>/<sha256>.<ext>
```

The ingestion record stores the raw path and hash so you can:
- dedupe repeated deliveries
- replay/backfill safely
- audit exactly what was processed

### Data contracts
Dataset rules live in YAML (see `data/contracts/`), e.g. `parcels.yaml`:
- required columns
- column types
- primary key uniqueness
- null thresholds
- min/max constraints
- drift policy

### Drift policy
- `warn` (default): proceed but record a drift report
- `fail`: stop processing and mark ingestion as failed
- `allow`: accept drift silently (still records schema history)

---

## Environment configuration

Copy `.env.example` to `.env` and customize:

- `DATABASE_URL`
- `REDIS_URL`
- `RAW_DATA_DIR`
- `CONTRACTS_DIR`
- `INCOMING_DIR`
- `ARCHIVE_DIR`
- `DRIFT_POLICY_DEFAULT`
- `MAX_FILE_MB`

See `.env.example` for details.

---

## Optional: GCP deployment (Cloud Run demo)

This repo includes a **working, team-ready** Cloud Run demo deployment (Terraform + Cloud Build) under:
- `infra/gcp/cloud_run_api_demo/`

Quickstart:

```bash
# one-command deploy (remote state + Cloud Build)
make deploy-gcp

# add DATABASE_URL (reads from stdin)
make db-secret
```

See:
- `docs/DEPLOY_GCP.md`
- `docs/TEAM_WORKFLOW.md`


---

## License
Apache-2.0


## UI stack

- Vite + React
- TanStack Router/Query/Table + Virtual + Pacer + Ranger
- Tailwind + shadcn-style components (vendored in `web/src/portfolio-ui`)
