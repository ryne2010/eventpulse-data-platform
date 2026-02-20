# Architecture

EventPulse is a **contract-driven, event-based ingestion platform** designed to resemble a scaled-down modern enterprise data stack.

Core patterns:

- data contracts + schema drift handling
- idempotent ingestion + replay/backfill
- curated modeling + marts/views + lineage metadata
- per-ingestion lineage artifacts
- observable operations (request IDs, structured logs)

---

## Logical flow

```
Source feeds (files, e.g., CSV/XLSX)
        |
        v
Raw landing (immutable copy: filesystem or GCS)
        |
        v
Contract validation + schema inference + drift detection
        |
        v
Curated tables (warehouse-ready)
        |
        v
Marts / views (read-optimized aggregates)
        |
        +--> Quality report (JSON)
        |
        +--> Lineage artifact (JSON)
```

---

## Edge telemetry lane (Raspberry Pi → Cloud Run)

EventPulse also includes a **field ops + edge telemetry** path designed for low-cost hardware deployments.

```
Sensors / device signals
  (real or simulated)
        |
        v
RPi (Edge Agent container)
  - local spool (offline buffering)
  - idempotent upload
        |
        v
Cloud Run (single service)
  - /api/edge/* device-authenticated helpers
  - optional signed URLs to GCS
        |
        v
GCS raw landing (edge_telemetry)
        |
        v
GCS event → ingestion job
  - contract validation
  - drift + quality checks
  - curated table + marts
        |
        v
UI
  - Devices (status + provisioning)
  - Device detail (telemetry + audit + commands)
```

---

## Local stack (Docker Compose)

- **Postgres** — system of record for ingestions, quality reports, schemas, lineage artifacts, and curated outputs
- **API (FastAPI)** — ingestion endpoints + read APIs + UI static hosting
- **Worker** — performs parsing/validation/drift detection/loading jobs
- **Watcher** — optional: polls `data/incoming/` and enqueues new drops
- **Web UI** — React/TanStack dashboards for ingestions and datasets

---

## Cloud Run lane (GCP)

The included Terraform root (`infra/gcp/cloud_run_api_demo/`) deploys a serverless-friendly setup:

- **Cloud Run** — API + UI
- **Cloud Storage** — raw landing zone (`STORAGE_BACKEND=gcs`)
- **Cloud Tasks** — async ingestion queue (`QUEUE_BACKEND=cloud_tasks`)
- **Secret Manager** — secrets:
  - `DATABASE_URL` (bring your own Postgres)
  - `TASK_TOKEN` (protects internal task endpoint)
- **Artifact Registry** — container images

Optional (not implemented in Terraform to keep the demo lightweight):

- **Cloud SQL** (Postgres)
- **BigQuery** curated warehouse + views
