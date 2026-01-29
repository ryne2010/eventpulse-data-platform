# EventPulse Data Platform (Local‑First)

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
cp .env.example .env
docker compose up --build
```

Services started:
- UI (React + TanStack): http://localhost:8081
- API (base): http://localhost:8081/api
- Swagger docs: http://localhost:8081/docs
- Postgres (metadata + curated tables): localhost:5432
- Redis (queue): localhost:6379
- Worker: background job processor
- (Optional) Watcher: directory polling → auto-ingest (see below)

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
docker compose --profile watch up --build
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

## Optional: GCP deployment path

This repo includes design notes and a Terraform skeleton under `infra/gcp/`.
The recommended cloud mapping is:

- Raw landing: **Cloud Storage**
- Eventing: **Pub/Sub**
- Processing: **Cloud Run** (API + worker)
- Warehouse: **BigQuery**
- Secrets/IAM: **Secret Manager / IAM**
- Observability: **Cloud Logging/Monitoring**

See: `docs/gcp_deploy.md`

---

## License
Apache-2.0


## UI stack

- Vite + React
- TanStack Router/Query/Table + Virtual + Pacer + Ranger
- Tailwind + shadcn-style components (vendored in `web/src/portfolio-ui`)

