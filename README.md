# EventPulse Data Platform (Local-first → Cloud Run)

EventPulse is a small, production-minded reference implementation of an event-driven data platform:

- **Immutable raw landing zone** (filesystem or GCS)
- **Schema drift detection** + configurable drift policies
- **Contract-driven quality gates**
- **Audit log + quality trends** (observability/governance)
- **Curated outputs** (Postgres tables) with **lineage metadata columns**
- **Per-ingestion lineage artifact** persisted to Postgres
- **Async processing**
  - Local dev: Redis/RQ (or inline)
  - Cloud Run: Cloud Tasks → internal processing endpoint

It’s designed to be easy to understand, easy to run locally on an **M2 Max MacBook Pro**, and easy to deploy to **Cloud Run**.

---

## Quickstart (local, Docker Compose)

### Prereqs

- Docker Desktop
- `make`

Optional (for running tooling outside Docker): `uv`, `node`, `pnpm`.

### Run

```bash
cp .env.example .env
make up
```

If you prefer a hybrid loop (DB/Redis in Docker, API on your host), use:

```bash
cp .env.host.example .env
```

See `docs/LOCAL_DEV.md` for both workflows.

Optional: set `TASK_TOKEN` in `.env` to enable internal endpoints (signed uploads, from_gcs backfills, incoming listing, and contract editing).

Open:

- UI: `http://localhost:8081`
- API health: `http://localhost:8081/health`

In the UI, use the top nav:

- **Dashboard** — status totals, backlog, and quick actions
- **Ingestions** — browse events; click through to quality/drift/lineage/audit
- **Datasets** — contract explorer/editor, schema history, curated sample, and marts
- **Products** — catalog of published marts (consumption layer)
- **Devices** — edge telemetry device health + **map** + **alerts** + provisioning (edge_telemetry demo)
  - click a device id for per-device telemetry + day-2 ops commands
- **Media** — optional edge device photo/video artifacts (webcam snapshots), requires internal auth
- **Trends** — quality pass/fail trends across recent ingestions
- **Audit** — operational audit log
- **Ingest** — direct upload (dev), signed URL upload (prod), and backfills
- **Ops** — runtime config + API docs link

### Seed a demo dataset

```bash
curl -X POST 'http://localhost:8081/api/demo/seed/parcels?limit=50&per_ingestion_max=10'

# Edge telemetry demo (RPi-style)
curl -X POST 'http://localhost:8081/api/demo/seed/edge_telemetry?limit=200&per_ingestion_max=200'
```

Then visit the UI and watch ingestions progress (or use **Dashboard → Seed demo data**).

---

## Ingestion paths

### 1) Drop files into the incoming folder (watcher → /api/ingest/from_path)

The watcher container polls `/data/incoming` and calls the API. Start it with: `make watch`.

> This path uses a privileged endpoint (`/api/ingest/from_path`) and requires internal auth.
> For local dev, set `TASK_TOKEN` in `.env` (the watcher automatically sends `X-Task-Token`).
> For Cloud Run, rely on IAM (and optionally a token for defense-in-depth).

- Incoming volume (host): `./data/incoming`
- Files are copied into the raw landing zone and then **archived** to avoid reprocessing.

### 2) Upload directly to the API (no multipart)

This endpoint accepts `application/octet-stream` and streams the body to disk before registering it.

```bash
curl -X POST \
  'http://localhost:8081/api/ingest/upload?dataset=parcels&filename=parcels.xlsx&source=curl' \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @./data/samples/parcels_baseline.xlsx

> **Security note:** In production, consider setting `INGEST_AUTH_MODE=token` and a strong
> `INGEST_TOKEN` for human/admin uploads. Field devices should use the **per-device token**
> model (`EDGE_AUTH_MODE=token`) and the `/api/edge/*` endpoints.
```

> **Cloud Run note:** request bodies have size limits. For larger files, use one of the GCS-backed paths:
>
> - **Recommended**: mint a **signed URL** (`POST /api/uploads/gcs_signed_url`), `PUT` the file to GCS, then (optionally) let **GCS finalize events** auto-register the ingestion.
> - **Manual**: upload to GCS yourself (e.g., `gsutil cp`) and call `POST /api/ingest/from_gcs`.
>
> Example (manual register after `make deploy-gcp`):
>
> ```bash
> URL=$(terraform -chdir=infra/gcp/cloud_run_api_demo output -raw service_url)
> RAW_BUCKET=$(terraform -chdir=infra/gcp/cloud_run_api_demo output -raw raw_bucket)
> TASK_TOKEN_SECRET=$(terraform -chdir=infra/gcp/cloud_run_api_demo output -raw task_token_secret_name)
> TASK_TOKEN=$(gcloud secrets versions access latest --secret "$TASK_TOKEN_SECRET")
>
> gsutil cp ./data/samples/parcels_baseline.xlsx "gs://${RAW_BUCKET}/uploads/parcels_baseline.xlsx"
>
> curl -sS -X POST "${URL}/api/ingest/from_gcs" \
>   -H "X-Task-Token: ${TASK_TOKEN}" \
>   -H 'Content-Type: application/json' \
>   -d '{"dataset":"parcels","gcs_uri":"gs://'"${RAW_BUCKET}"'/uploads/parcels_baseline.xlsx","source":"gsutil"}' | jq .
> ```
>
> For signed URLs + event-driven ingestion wiring, see `docs/DEPLOY_GCP.md`.
### 3) Edge devices (RPi / field sensors)

Field devices (Raspberry Pi sensors over 5G/LTE) should use the **edge ingestion**
endpoints and the per-device token auth model:

- `POST /api/edge/uploads/gcs_signed_url` → device uploads directly to GCS via signed URL
- `POST /api/edge/ingest/from_gcs` → finalize ingestion (register + enqueue)
- `POST /api/edge/ingest/upload` → direct API upload (local dev / small payloads)

Fast provisioning option (recommended for deployment speed): configure `EDGE_ENROLL_TOKEN`
on the API and let devices self-enroll via `POST /api/edge/enroll`.

See `docs/EDGE_RPI.md` for a practical Raspberry Pi deployment walkthrough.


---

## Cloud Run (production demo)

The Cloud Run lane is optimized for serverless:

- **Raw landing zone**: GCS bucket
- **Async processing**: Cloud Tasks
- **Metadata + curated tables**: Postgres (bring your own DB URL)

### Deploy

1) Authenticate and configure gcloud defaults (one-time):

```bash
make auth
make init PROJECT_ID=YOUR_PROJECT_ID REGION=us-central1
```

Or, equivalently (manual):

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
gcloud config set run/region us-central1
```

2) Provision prerequisite infra (APIs, Artifact Registry, service accounts, **secret containers**):

```bash
make infra-gcp ENV=dev
```

3) Add required secret versions (paste values, then Ctrl-D):

```bash
make db-secret
make task-token-secret

# Optional (protect public ingest endpoint)
# make ingest-token-secret

# Optional (fast edge provisioning)
# TF_VAR_enable_edge_enroll=true make edge-enroll-token-secret
```

4) Build + deploy:

```bash
make deploy-gcp ENV=dev
```

Tip: `make deploy-gcp` runs a secrets preflight (`make check-secrets-gcp`) and fails early if versions are missing.

5) Verify:

```bash
make verify-gcp ENV=dev
```

---

## Docs

- `docs/QUICK_TOUR.md` — hands-on walkthrough
- `docs/LOCAL_DEV.md` — local dev workflows (Docker and hybrid)
- `docs/DEPLOY_GCP.md` — Cloud Run deployment notes + troubleshooting
- `docs/EDGE_RPI.md` — edge telemetry (Raspberry Pi agent)
- `docs/FIELD_OPS.md` — field deployment runbook (RPi + LTE/5G)
- `docs/HARDWARE.md` — cheap + available field hardware options
- `docs/MAINTENANCE.md` — DB size widgets + pruning retention data
- `docs/OBSERVABILITY.md` — logs, request IDs, and trace correlation
- `docs/SCHEMA_DRIFT.md` — dataset schema drift logic and policies
- `docs/DRIFT_DETECTION.md` — Terraform drift detection notes (infra)
- `RUNBOOK.md` — common operational tasks
- `docs/RUNBOOKS/` — incident/debug/release runbooks

## Development notes

- Dataset names are normalized to lowercase and validated (safe for paths + SQL identifiers).
- Ingestion processing is **idempotent**: only `RECEIVED` and `FAILED_EXCEPTION` ingestions are auto-claimed for processing.
  - Replays create a **new** ingestion record referencing the same raw artifact.
- If an ingestion is stuck in `PROCESSING` (e.g., worker crash after claiming), you can reclaim it:
  - Local/dev: `make reclaim-stuck`
  - Cloud Run: `POST /internal/admin/reclaim_stuck` (protected via TASK_AUTH_MODE)
