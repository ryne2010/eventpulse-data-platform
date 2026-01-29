# Architecture (Local)

EventPulse runs as 4 containers (3 by default):

- **api** (FastAPI): accepts ingestion requests, writes immutable raw copies, enqueues jobs
- **worker** (RQ): processes ingestion jobs (parse → drift detect → quality validate → load curated)
- **postgres**: metadata + curated tables
- **redis**: queue transport
- **watcher** (optional): polls `INCOMING_DIR` and calls the API for any new files

## Data flow

1) A file arrives (manual drop or watcher) under `INCOMING_DIR`
2) API copies it to the immutable raw landing zone: `RAW_DATA_DIR/<dataset>/<date>/<sha256>.<ext>`
3) API creates an `ingestions` record and enqueues a job
4) Worker:
   - loads raw file into a dataframe
   - infers observed schema and records schema history
   - computes drift vs. prior schema
   - validates against YAML contract (required columns, types, null thresholds, uniqueness, min/max)
   - loads into a curated table (`curated_<dataset>`) using upsert
   - persists a quality report, drift report, and final status

## Why this structure?
This mirrors a production cloud implementation (e.g., GCS → Pub/Sub → Cloud Run → BigQuery)
while being easy to run locally.
