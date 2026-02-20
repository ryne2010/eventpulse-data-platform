# Domain

EventPulse is a **local-first reference implementation** of an **event-driven data platform**.

It is designed to be:

- **Runnable on a laptop** (Docker Compose)
- **Replayable / auditable** (immutable raw landing zone + ingestion metadata)
- **Contract-driven** (YAML contracts for schema + quality + drift policies)
- **Production-patterned** (worker queue, idempotency, observability, IaC demo for GCP)

If you are an agent or a contributor, this is the durable “what and why”.

## What are we building?

- **Problem:** Teams ingest recurring files/events from operational systems and need a safe path to:
  - validate schema and quality
  - detect and handle schema drift
  - load curated, queryable tables
  - provide observability for stakeholders
- **Primary users:**
  - data engineers / platform engineers
  - analytics engineers
  - operators who need visibility into ingestion status
- **Non-goals (in this repo):**
  - a full multi-tenant enterprise product
  - every connector/protocol under the sun
  - complex auth/entitlements (kept intentionally simple)

## Domain invariants

These are “must always hold” properties. If you change any invariant, you must document it via an ADR (`docs/DECISIONS/`).

1. **Raw immutability**
   - Once a file is copied into `data/raw/<dataset>/<date>/<sha256>.<ext>`, it is never modified.
2. **Idempotent ingestion**
   - Re-ingesting the same raw file should not create duplicate curated facts.
   - Upserts are keyed on the dataset contract primary key (when provided).
3. **Contract-first validation**
   - Contract violations (missing required columns, uniqueness failures, null thresholds) are surfaced as quality errors.
4. **Drift is explicit**
   - Schema drift is detected by comparing inferred schema hashes and recorded in a drift report.
   - Drift policy is applied consistently (`warn`, `fail`, `allow`).
5. **Every ingestion has an audit trail**
   - Ingestion metadata records the source, raw path, file hash, timestamps, and status.

## Core workflows

1. **Ingest a file**
   - API accepts a dataset + file path
   - file is copied into immutable raw
   - an ingestion record is created
   - worker job validates, detects drift, loads curated tables, records reports
2. **Observe ingestion outcomes**
   - list ingestions
   - fetch ingestion details (status, quality report, drift report)
3. **Query curated data**
   - preview “sample curated” data
   - (optional) use the UI to view curated tables

## Vocabulary

- **Dataset:** a named stream of records (e.g., `parcels`)
- **Contract:** YAML spec that defines expected columns, types, primary key, and quality constraints
- **Ingestion:** a single processing attempt of one raw file
- **Raw landing zone:** immutable, content-addressed storage of received files
- **Schema drift:** addition/removal/type changes in columns compared to previously-seen schema
- **Curated table:** a typed, queryable table materialized from raw files (e.g., Postgres in local mode)

## Data model overview

EventPulse stores metadata and curated data in Postgres:

- **Metadata tables:**
  - ingestions (status, timestamps, hashes)
  - schema history
  - quality reports
  - drift reports
- **Curated tables:**
  - `curated_<dataset>` containing contract-defined columns + lineage columns

See also:
- `ARCHITECTURE.md`
- `docs/CONTRACTS.md`
- `docs/DRIFT_DETECTION.md`

## Failure modes to keep in mind

- malformed files / unsupported extensions
- partial schema drift (columns renamed, type widened)
- primary key violations
- missing required columns
- duplicated deliveries
- transient database or queue outages

## Acceptance criteria patterns

A change is “done” when it satisfies:

- **Correctness:** preserves invariants above and has tests for non-trivial logic
- **Operability:** errors are observable via logs and recorded reports
- **Reproducibility:** `uv.lock` stays up to date; terraform formatting stays clean
