# Maintenance & retention

This project is designed to run unattended on Cloud Run, but it still benefits from basic operational hygiene:

- **Reclaiming stuck ingestions** (worker crash mid-flight)
- **Capping retries** (avoid infinite churn on pathological inputs)
- **Pruning retention data** (audit log growth, terminal ingestion history)
- **Watching DB size** (avoid surprise Cloud SQL storage growth)

The UI **Ops** page surfaces these actions, and the API exposes internal endpoints for automation.

### Retry cap (MAX_PROCESSING_ATTEMPTS)

Each ingestion increments a Postgres-side `processing_attempts` counter whenever a worker claims it.
If `MAX_PROCESSING_ATTEMPTS` is exceeded, the ingestion is marked terminal as:

- `FAILED_MAX_ATTEMPTS`

At that point it will not be auto-processed again unless you **reprocess** it (which creates a new ingestion record).

---

## Internal endpoint auth

Internal endpoints are protected via `TASK_AUTH_MODE`:

- `TASK_AUTH_MODE=token`: send `X-Task-Token: $TASK_TOKEN`
- `TASK_AUTH_MODE=iam`: Cloud Run must be private (`allow_unauthenticated=false`) and callers authenticate using OIDC (`Authorization: Bearer ...`)

---

## Make targets (local)

If you run the API locally on `$(LOCAL_URL)` (default `http://localhost:8081`), these are convenient shortcuts:

```bash
make db-stats
make prune-dry
make prune
```

`make prune` runs with `confirm=PRUNE` for safety.

---

## DB stats

Fetch lightweight DB storage stats (database size + key table sizes):

```bash
URL=http://localhost:8081
TOKEN=devtoken

curl -sS "${URL}/internal/admin/db_stats" \
  -H "X-Task-Token: ${TOKEN}" | jq .
```

This is intentionally cheap:

- **table row counts are estimates** (planner stats)
- sizes come from `pg_total_relation_size()`

---

## Prune retention data

This repo supports pruning two categories:

1) **Audit events** (`audit_events`)
2) **Terminal ingestions** (`ingestions` where status is `LOADED` or `FAILED_*`)

### Dry run (recommended)

```bash
curl -sS -X POST "${URL}/internal/admin/prune" \
  -H "X-Task-Token: ${TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{
    "dry_run": true,
    "audit_older_than_days": 30,
    "audit_limit": 50000,
    "ingestions_older_than_days": 90,
    "ingestions_limit": 5000
  }' | jq .
```

### Execute prune

For safety, destructive runs require `confirm=PRUNE`.

```bash
curl -sS -X POST "${URL}/internal/admin/prune" \
  -H "X-Task-Token: ${TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{
    "dry_run": false,
    "confirm": "PRUNE",
    "audit_older_than_days": 30,
    "audit_limit": 50000,
    "ingestions_older_than_days": 90,
    "ingestions_limit": 5000
  }' | jq .
```

Notes:

- Deletes are **oldest-first** and **limited** so you can run them safely as periodic jobs.
- Deleting ingestion rows cascades to `quality_reports` + `lineage_artifacts`.
- Audit events referencing pruned ingestions will keep the event but set `ingestion_id` to `NULL`.

---

## Suggested defaults

These are reasonable defaults for a demo/staff-level project:

- **Audit log retention:** 30–90 days
- **Terminal ingestion retention:** 60–180 days (depending on how much lineage/history you want)

If you want longer history, keep ingestion rows and prune only audit events.
