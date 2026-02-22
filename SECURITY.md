# Security notes

This repo is a portfolio-grade reference. It keeps auth and secrets intentionally simple, while still demonstrating patterns teams use in production.

---

## Data sensitivity

EventPulse is built for ingesting datasets that may include PII/confidential data.

Recommended posture:
- classify datasets (public/internal/confidential)
- least-privilege access to storage/warehouse
- audit logs for ingestion actions and dataset reads

---

## Secrets

- Local dev: `.env` (never commit)
- Cloud: **Secret Manager** for `DATABASE_URL`, `TASK_TOKEN`, `INGEST_TOKEN`, and any API keys

---

## API surface

Treat write/ingest paths as privileged:
- `POST /api/ingest/upload`
- `POST /api/ingest/from_path` (local-only)
- `POST /api/ingest/from_gcs`
- `POST /api/uploads/gcs_signed_url`

Recommended deployment pattern:
- keep Cloud Run **private** (no unauthenticated invoker) for production
- front it with a real identity layer (IAP / OAuth / a gateway) for human access
- allow Cloud Tasks / Pub/Sub to invoke internal endpoints via OIDC

---

## Internal endpoints

EventPulse uses internal endpoints for async processing and administrative recovery:

- `POST /internal/tasks/process_ingestion`
- `POST /internal/admin/reclaim_stuck`
- `POST /internal/events/gcs_finalize` (optional, for event-driven ingestion)

They support two auth modes:

- `TASK_AUTH_MODE=token`: require `X-Task-Token` header (works even if Cloud Run is public)
- `TASK_AUTH_MODE=iam`: rely on Cloud Run IAM; Cloud Tasks / Pub/Sub push call with OIDC tokens

If you enable **signed URLs** or **event-driven ingestion**, prefer `TASK_AUTH_MODE=iam` and keep the service private.

---

## Ingest auth

For direct upload endpoints, use token mode when traffic is not behind an identity boundary:

- `INGEST_AUTH_MODE=token`
- `INGEST_TOKEN` stored in Secret Manager

For large-file and production workflows, prefer direct-to-GCS signed URLs and keep internal auth enabled.

---

## Supply chain / CI

- Python deps are pinned in `uv.lock`.
- Frontend deps are pinned in `pnpm-lock.yaml`.
- To refresh lockfiles: `make lock`.
- In CI, prefer Workload Identity Federation (avoid JSON service account keys).

---

## HTTP hardening (baseline)

The API sets conservative security headers (e.g., `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`).

If you need stricter controls (CSP, WAF rules, geo/IP allowlists), enforce them at the ingress/load-balancer layer rather than in-app.

This repo intentionally starts **without** Cloud Armor to keep costs and complexity low; it can be added later if/when you need DDoS/WAF features.
