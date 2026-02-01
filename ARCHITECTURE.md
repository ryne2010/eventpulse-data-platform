# Architecture

EventPulse is a **contract-driven, event-based data ingestion platform** designed to look like a scaled-down version of a modern enterprise data stack.

It demonstrates "Data Architect" and "Cloud Engineer" patterns:
- data contracts + schema drift handling
- idempotent ingestion + replay/backfill
- curated modeling + versioned API access
- lineage artifacts per ingestion
- observable operations (logs, metrics, clear runbook)

---

## Logical flow

```
Source feeds (files, e.g., Excel)
        |
        v
Raw landing (immutable copy)
        |
        v
Contract validation + normalization
        |
        v
Curated tables (warehouse-ready)
        |
        +--> Lineage artifact (JSON)
        |
        +--> Versioned API endpoints (compatibility guarantees)
```

## Local stack (Docker Compose)

- **Postgres** — system of record for ingestions, curated outputs, and lineage
- **API (FastAPI)** — ingestion endpoints + read APIs + UI static hosting
- **Worker** — performs parsing/validation/curation jobs
- **Watcher** — optional file watcher that auto-enqueues new drops
- **Web UI** — React/TanStack, read-only dashboards for ingestions and datasets

## Cloud mapping (GCP)

This repo includes an optional GCP demo deployment:
- **Cloud Run** — API + UI
- **Artifact Registry** — images
- **Cloud Build** — consistent builds
- **Secret Manager** — DATABASE_URL

For a full production mapping (not implemented here to keep costs low):
- Cloud Storage raw landing
- Pub/Sub ingestion events
- Cloud Run Jobs (worker)
- BigQuery curated warehouse

