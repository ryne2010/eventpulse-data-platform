# Security notes

This repo is a portfolio-grade reference. It intentionally keeps secrets and auth simple while demonstrating the patterns teams use.

## Data sensitivity

EventPulse is built for ingesting datasets that may include PII/confidential data.
Recommended posture:
- classify datasets (public/internal/confidential)
- least-privilege access to storage/warehouse
- audit logs for ingestion actions and dataset reads

## Secrets

- Local dev: `.env` (never commit)
- Cloud: **Secret Manager** for `DATABASE_URL` and any API keys

## API surface

- Treat ingestion endpoints as privileged: lock them behind OIDC/IAP or allowlisted networks
- Expose read APIs separately when needed (API-led connectivity)

## Supply chain / CI

- Pin dependencies via lockfiles (`uv.lock`, `pnpm-lock.yaml`)
- In CI, use Workload Identity Federation (no JSON keys)

