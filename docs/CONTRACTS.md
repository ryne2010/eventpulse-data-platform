# Contracts

Contracts define **behavioral guarantees** and **compatibility rules**.

Treat this document as non-negotiable unless explicitly changed via ADR.

## Public interfaces

### HTTP API

- **Ingestion API**
  - `POST /api/ingest/from_path`
  - `POST /api/ingest/upload`
  - `/from_path` accepts: dataset, relative path, source
  - `/upload` accepts: dataset, filename, source + binary file body
  - Guarantees:
    - raw file is copied into the landing zone
    - an ingestion record exists and can be queried
    - processing is queued asynchronously

Notes:
- `POST /api/ingest/upload` may require `X-Ingest-Token` when `INGEST_AUTH_MODE=token`.
- **Edge device API**
  - `GET /api/edge/ping`
  - `POST /api/edge/ingest/upload` (device-authenticated direct upload)
  - `POST /api/edge/uploads/gcs_signed_url` (device-authenticated signed URL init)
  - `POST /api/edge/ingest/from_gcs` (device-authenticated finalize)

Notes:
- Edge endpoints use per-device tokens when `EDGE_AUTH_MODE=token`.
  - Required headers: `X-Device-Id`, `X-Device-Token`
- **Observability API**
  - `GET /api/ingestions`
  - `GET /api/ingestions/{id}`
  - `GET /api/audit_events`
  - `GET /api/trends/quality`
  - Returns ingestion status + quality/drift/audit telemetry
- **Curated data API**
  - `GET /api/datasets/{dataset}/curated/sample`
  - `GET /api/data_products` (catalog of marts)

(See `eventpulse/api_server.py` for authoritative route definitions.)

### Data contract YAML


### Contract validation + editing (optional)

- `POST /api/contracts/validate`
  - validates a YAML payload without persisting it
- `PUT /api/datasets/{dataset}/contract`
  - writes a contract file under `data/contracts/`
  - **disabled by default** (`ENABLE_CONTRACT_WRITE=false`)
  - requires internal auth (task token or Cloud Run IAM)

Notes:
- In Cloud Run, the container filesystem is typically read-only. In production, prefer GitOps (edit contracts in source control).
- Column names are intentionally restricted to safe SQL identifiers: `^[a-z_][a-z0-9_]*$`.


Contracts live under `data/contracts/*.yaml`.

A contract defines:

- `dataset`: name
- `primary_key`: (optional) column used for upserts
- `columns`: per-column rules
  - `type`: logical type
  - `required`: boolean
  - `unique`: boolean
  - `min` / `max`: numeric bounds (optional)
- `quality`:
  - `max_null_fraction`: per-column thresholds
- `drift_policy`: `warn` | `fail` | `allow`

See:
- `data/contracts/*.yaml` (examples)
- `docs/SCHEMA_DRIFT.md` (drift policies)

## Functional invariants

1. **Immutability of raw files**
   - Raw copies are content-addressed and never mutated.
2. **Idempotent curated loads**
   - If a primary key is configured, loads are upserts keyed by that column.
3. **Deterministic drift detection**
   - Schema hashes are stable regardless of input column order.
4. **Lineage columns exist for curated tables**
   - `_ingestion_id`, `_loaded_at`, `_source_sha256` are always present.

## Compatibility policy

This is a portfolio/reference repo, but we still keep changes legible:

- **Backwards compatible changes:**
  - additive API endpoints
  - additive contract fields with defaults
  - additive columns in curated tables
- **Breaking changes require:**
  - ADR
  - clear migration notes (docs + Make targets if needed)

## Testing contract

Minimum expectations:

- Unit tests for non-trivial logic (schema hashing, quality rules, drift policy)
- Regression test for bug fixes
- Prefer deterministic tests (no wall-clock dependency)

## Observability contract

- Structured logs (no secrets)
- Ingestion failures must be visible:
  - in logs
  - in ingestion metadata/status

See `docs/OBSERVABILITY.md`.
