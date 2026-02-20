# Runbook

This runbook covers common operational and debugging tasks for EventPulse.

---

## Local development (Docker Compose)

### Start / stop

```bash
make up
make down
```

### Reset all local state

This deletes Postgres volume data and raw/archive directories.

```bash
make reset
make up
```

### View logs

```bash
make logs
```

### Generate sample files

```bash
make gen
ls -la data/samples
```

### Ingest a sample (no watcher required)

```bash
make ingest
```

### Ingest via watcher

Start the watcher, then copy a file into `data/incoming/` and it will enqueue it.

```bash
make watch
cp data/samples/parcels_baseline.xlsx data/incoming/
```

---

## API endpoints (handy for debugging)

### Health

- `GET /health`
- `GET /readyz` (checks DB + queue)

### Ingest

- `POST /api/ingest/upload?dataset=...&filename=...&source=...` (octet-stream body)
- `POST /api/ingest/from_gcs` (Cloud Run recommended for larger files)
- `POST /api/ingest/from_path` (watcher-only; disabled on Cloud Run)

### Recover stuck ingestions

If an ingestion is stuck in `PROCESSING` (worker crashed after claiming):

- Local/dev: `make reclaim-stuck`
- Cloud Run: `POST /internal/admin/reclaim_stuck` (protected via `TASK_AUTH_MODE`)

### Maintenance (DB stats + pruning)

- Fetch DB storage stats: `GET /internal/admin/db_stats`
- Prune retention data: `POST /internal/admin/prune`

For examples (dry run vs execute) see: `docs/MAINTENANCE.md`.

### Inspect results

- `GET /api/ingestions?limit=50`
- `GET /api/ingestions/{id}`
- `GET /api/ingestions/{id}/preview`
- `GET /api/ingestions/{id}/lineage`
- `GET /api/datasets/{dataset}/schemas`

---

## Cloud Run lane

### Verify service

```bash
make verify-gcp
```

### Typical failure modes

- **500 on startup** → missing `DATABASE_URL` secret version
- **Cloud Tasks failing** →
  - public service (`allow_unauthenticated=true`): missing `TASK_TOKEN` secret version, or queue misconfigured
  - private service (`allow_unauthenticated=false`): missing `roles/run.invoker` on the tasks invoker service account
- **GCS permission error** → Cloud Run service account missing bucket IAM

### Inspect Cloud Tasks

Use Cloud Console → Cloud Tasks:

- Look for retry spikes (transient errors)
- Check task logs in Cloud Run (filter by request ID)

---

## Debugging tips

### Request IDs

Every API response includes `X-Request-ID`. Use it to correlate UI actions with logs.

### Replays

Use the replay endpoint to re-run an ingestion without re-uploading:

```bash
curl -X POST "http://localhost:8081/api/ingestions/<ID>/replay"
```
