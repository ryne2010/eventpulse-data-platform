# Design

This document encodes **architecture, boundaries, and dependency rules**.

If you need to change any boundary, write an ADR in `docs/DECISIONS/`.

## Architecture overview

EventPulse is a small-but-realistic “data platform slice”:

- **UI**: React (Vite + TanStack) in `web/`
- **API**: FastAPI service in `eventpulse/api_server.py`
- **Worker**:
  - Local/dev: RQ worker in `services/worker/` and `eventpulse/jobs.py`
  - Cloud Run: Cloud Tasks calls the internal task endpoint, which runs `eventpulse/jobs.py`
- **State**:
  - Postgres for ingestion metadata + curated tables
  - Redis for queueing jobs (local/dev)
  - Cloud Tasks for async processing (Cloud Run)
- **Storage**:
  - local filesystem under `./data` for raw / incoming / archive / contracts (local/dev)
  - GCS for raw storage (Cloud Run)
- **IaC demo**:
  - Terraform under `infra/gcp/cloud_run_api_demo/` for Cloud Run patterns

Local runtime is orchestrated by Docker Compose (`docker-compose.yml`).

## Layering model (Python)

The Python package is intentionally simple, but we still enforce a layering mindset:

1. **API / Adapters**
   - `eventpulse/api_server.py` (HTTP boundary)
2. **Application orchestration**
   - `eventpulse/ingest.py` (ingestion orchestration)
   - `eventpulse/jobs.py` (worker job orchestration)
3. **Domain / Rules**
   - `eventpulse/contracts.py` (contract parsing)
   - `eventpulse/schema.py` (schema inference + hashing)
   - `eventpulse/quality.py` (quality validation)
4. **Infrastructure adapters**
   - `eventpulse/db.py` (Postgres access)
   - `eventpulse/loaders/` (Postgres loader; future: BigQuery loader)

### Allowed dependencies

- API layer may call application orchestration
- Orchestration may call domain rules and infrastructure adapters
- Domain rules must avoid importing the API layer
- Infrastructure adapters must not import the API layer

## UI boundary

- The UI should treat the API as the source of truth.
- Avoid duplicating data validation rules in the UI (display contract/quality results from the API).

## Terraform boundary

Terraform is treated as **first-class code**.

- Formatting is enforced via pre-commit (`terraform fmt -recursive`).
- IaC changes should include:
  - plan output (or a description of intended diffs)
  - rollout notes (especially if touching IAM)

## Error handling policy

- Use structured exceptions for domain errors.
- API layer converts domain/application errors into:
  - consistent HTTP status codes
  - safe messages (no secrets)
- Worker jobs must:
  - mark ingestion status explicitly
  - persist error details to ingestion records

## Performance / scaling notes

Local mode is not tuned for extreme throughput, but the design supports:

- file-level parallelism (workers)
- idempotency to enable retries
- batching inserts via `execute_values`

## Change policy

When a change impacts:

- an invariant in `docs/DOMAIN.md`
- a public interface in `docs/CONTRACTS.md`
- a boundary defined above

…write an ADR and update docs + tests accordingly.
