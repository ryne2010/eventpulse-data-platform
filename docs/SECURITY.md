# Security & auth model

This project is designed to run as a single Cloud Run service for real-estate data ingestion and analytics UI with low operational overhead.

It supports multiple auth modes so you can start simple locally and progressively harden for production.

> This is not a compliance framework. It is a pragmatic security model for a Cloud Run + Postgres + GCS reference platform.

---

## Threat model (practical)

Assume:

- The Cloud Run service may be publicly reachable in simple deployments.
- Attackers can:
  - scan endpoints
  - try to spam ingest endpoints
  - replay/guess tokens
  - upload malformed or oversized files

We aim to prevent:

- unauthorized ingestion
- unauthorized access to internal ops endpoints
- accidental exposure of sensitive data
- cross-site request exfiltration from the SPA

---

## Auth layers

EventPulse separates responsibilities into two logical planes:

1) **Ingest plane**: humans/tools -> `/api/ingest/...`
2) **Ops plane**: admin/UI -> `/internal/...` + selected `/api/...` admin endpoints

### 1) Ingest plane: ingest token (optional)

**Goal:** protect direct upload APIs when the service is public.

- `INGEST_AUTH_MODE=token` requires `X-Ingest-Token` for `/api/ingest/upload`.
- Keep `INGEST_TOKEN` in Secret Manager.

For production-scale uploads, prefer **GCS signed URL uploads** instead of direct uploads.

### 2) Ops plane: Cloud Run IAM or task token

**Goal:** keep internal endpoints inaccessible to unauthenticated callers.

- `TASK_AUTH_MODE=iam` (recommended): deploy Cloud Run with `allow_unauthenticated=false` and call with OIDC.
- `TASK_AUTH_MODE=token`: requires `X-Task-Token`.

Defense-in-depth:

- If `TASK_TOKEN` is set, it is enforced even if `TASK_AUTH_MODE=iam`.

---

## Signed URL model (recommended)

For large files and reliability:

- API mints a **V4 signed URL** for a specific object name with preconditions.
- Client uploads directly to GCS.
- Client calls back to register the ingestion (or GCS events can trigger ingestion).

Hardening included:

- Optional `sha256` requirement (`REQUIRE_SIGNED_URL_SHA256=true`).
- Default precondition `ifGenerationMatch=0` (prevents overwrite).

---

## Security headers (CSP) and why they matter

The API sets baseline security headers for the SPA.

Important details:

- Browser-based **GCS signed URL uploads** require CSP `connect-src` to allow:
  - `https://storage.googleapis.com`

- FastAPI Swagger `/docs` and Redoc `/redoc` load assets from a CDN by default. CSP is configured so that:
  - only docs routes allow `https://cdn.jsdelivr.net`

If you prefer to avoid CDNs in production, disable FastAPI docs (or host assets yourself).

---

## Cloud Armor / WAF

This repo intentionally starts **without** Cloud Armor to keep costs minimal.

When Cloud Armor adds value:

- you are under sustained abuse (bot traffic, volumetric scanning)
- you need IP allowlists/denylists
- you want managed WAF rules

If you do not have those needs yet, you can generally rely on:

- strong tokens + limited surface area
- Cloud Run IAM for internal endpoints
- request limits + observability

---

## Practical production checklist

- [ ] Use `TASK_AUTH_MODE=iam` for internal endpoints (Cloud Run private)
- [ ] Keep `DATABASE_URL`, `TASK_TOKEN`, and `INGEST_TOKEN` in Secret Manager
- [ ] Prefer GCS signed URL uploads for large ingestion workloads
- [ ] Use a private GCS bucket for raw landing + signed URLs for access
- [ ] Keep retention under control (see `docs/MAINTENANCE.md`)
