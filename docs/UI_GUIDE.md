# UI Guide

This UI is intentionally small (React + Vite + TanStack Router/Query) but it aims to feel like a “real” internal data platform console: contracts → ingestions → drift/quality → curated outputs → marts.

## Pages

### Dashboard

- Platform KPIs (totals, backlog, success rate, stuck processing)
- Activity chart (recent ingestions)
- Dataset shortlist (with “curated/contract” badges)
- Quick actions (Upload, open parcels, seed demo data)

### Ingestions

- Filter by dataset / status / text search (id, filename, source, raw path)
- Live refresh while new events arrive
- Click any row to open the detail view

### Ingestion detail

Tabs:

- **Overview** — raw path, SHA-256, timing, attempts, error
- **Quality** — pass/fail, errors/warnings, basic profiling + null fractions
- **Drift** — added/removed/type-changed columns, breaking vs non-breaking
- **Lineage** — persisted lineage artifact (JSON)
- **Curated rows** — sample rows from Postgres filtered by ingestion id

Actions:

- **Replay** — creates a new ingestion record and reprocesses the same raw file
- **Dataset** — jumps to dataset detail for contracts + schema history + marts

### Datasets

- Lists datasets from:
  - Contracts on disk (`CONTRACTS_DIR/*.yaml`)
  - Datasets observed in the ingestions table
- For each dataset: contract flags, curated availability, latest schema hash, last activity

### Dataset detail

Tabs:

- **Overview** — summary cards + contract-vs-observed diff
- **Contract** — YAML + parsed columns table
- **Schema history** — inferred schemas over time (for drift detection)
- **Curated sample** — sample rows from `curated_<dataset>`
- **Marts** — read-optimized Postgres views (warehouse-style aggregates)
- **Map** — lightweight geo scatter powered by the `geo_points` mart (when available)

> Marts are created automatically (best-effort) after the first successful ingestion for a dataset.

### Devices

Four tabs:

- **Status** — device health table powered by the `edge_telemetry` mart `marts_edge_telemetry_device_status`.
  - shows label/id, last seen, last event, and an offline heuristic
- **Map** — lightweight fleet map (scatter plot) of last-known device locations.
  - powered by `marts_edge_telemetry_device_geo_status` (device_status + last known lat/lon)
  - **no map tiles** (keeps it cheap + dependency-free); meant for quick ops triage
- **Alerts** — fleet-wide “active alerts” derived from the latest per-sensor readings.
  - powered by `marts_edge_telemetry_device_alerts`
  - shows severity + sensor + latest value + timestamp
  - thresholds are pragmatic defaults (tune in `eventpulse/loaders/postgres.py` → `marts_edge_telemetry_latest_readings`)
- **Provisioning** — field ops helpers:
  - quick `field_ops/rpi/install.sh` command
  - lightweight "quick deploy" wizard + copy-to-clipboard helpers
  - device registry actions (internal auth):
    - provision device (returns a device token)
    - rotate token
    - revoke device

Click any device id to open the **Device detail** view:

- status + offline basis
- sensor snapshot uses `marts_edge_telemetry_latest_readings` (server-scored severity)
- recent telemetry rows (raw event stream, filtered by device_id)
- audit events (filtered by actor)
- day-2 ops commands (copy/paste)

If `TASK_AUTH_MODE=token`, paste `TASK_TOKEN` into the Ops page (or Upload page). The UI stores it in:

- `localStorage["eventpulse.taskToken"]`

Offline heuristic tuning:

- `EDGE_OFFLINE_THRESHOLD_SECONDS` (default 600)

### Media

- Lists photo/video artifacts uploaded by edge devices (optional feature).
- Records are created via `POST /api/edge/media/finalize` after a direct-to-GCS upload.
- Preview uses short-lived signed GET URLs minted by internal endpoints:
  - `POST /internal/admin/media/gcs_read_signed_url`

> Because media can be sensitive, the Media page requires internal auth (task token or Cloud Run IAM).

### Upload

Two modes:

1) **Direct upload** (simple)
- Uploads file bytes to the API (`POST /api/ingest/upload`)
- Best for local dev and small files

If `INGEST_AUTH_MODE=token`, the request must include `X-Ingest-Token`.

2) **Signed URL upload** (production-friendly)
- Mints a signed URL (`POST /api/uploads/gcs_signed_url`) **(internal auth required)**
- Browser `PUT`s the file directly to GCS
- Registers the ingestion (`POST /api/ingest/from_gcs`) **(internal auth required)**

Backfill helpers (internal auth required):

- **Register existing GCS object** — if a file already exists in your raw bucket, register it without re-uploading.
- **Ingest from INCOMING_DIR path** — local backfill convenience. Requires:
  - `ENABLE_INGEST_FROM_PATH=true`
  - `ENABLE_INCOMING_LIST=true` (optional, only for listing)
  - internal auth (`TASK_TOKEN` in token mode, or Cloud Run IAM in iam mode)

If `TASK_AUTH_MODE=token`, paste `TASK_TOKEN` into the Upload page’s **Task token** field. The UI stores it in:

- `localStorage["eventpulse.taskToken"]`

### Ops

- Runtime configuration and feature flags
- DB ping + lightweight DB size widget (internal auth)
- Maintenance actions:
  - reclaim stuck ingestions
  - prune retention data (audit events + old terminal ingestions)
- Direct link to FastAPI `/docs` (Swagger UI; loads assets from a CDN by default — see `docs/SECURITY.md`)

## Recommended workflow

### Local dev (M2 Max MacBook Pro)

1) Start services:

```bash
make up
```

2) Open the UI:

- http://localhost:8081

3) Use **Dashboard → Seed demo data**, or **Upload → Direct upload** with a CSV/XLSX file.

4) Inspect an ingestion:
- Go to **Ingestions**
- Click a row
- Review Quality/Drift/Lineage

### Cloud Run (production)

- Prefer `STORAGE_BACKEND=gcs` and **signed URL upload**
- Keep internal endpoints protected:
  - `TASK_AUTH_MODE=iam` for fully private services
  - or `TASK_AUTH_MODE=token` with `TASK_TOKEN` stored in Secret Manager

See: `docs/DEPLOY_GCP.md`.
