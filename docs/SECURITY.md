# Security & auth model

This project is designed to be **field-deployable** (internet-exposed ingestion from edge devices) while keeping the operational surface area small and costs minimal.

It supports multiple auth modes so you can start simple locally and progressively harden for production.

> This is not a compliance framework. It’s a pragmatic security model for a Cloud Run + Cloud SQL + GCS reference platform.

---

## Threat model (practical)

Assume:

- The Cloud Run service may be **publicly reachable** (edge devices send telemetry over 5G).
- Attackers can:
  - scan endpoints
  - try to spam ingest endpoints
  - replay/guess tokens
  - upload malformed or huge files

We aim to prevent:

- unauthorized ingestion
- unauthorized device enrollment
- unauthorized access to internal ops endpoints
- cross-site request exfiltration from the SPA

---

## Auth layers

EventPulse separates responsibilities into three logical planes:

1) **Edge plane**: device → `/api/edge/...`
2) **Ingest plane**: humans/tools → `/api/ingest/...` (direct uploads)
3) **Ops plane**: admin/UI → `/internal/...` + selected `/api/...` admin endpoints

### 1) Edge plane: device tokens + optional enrollment token

**Goal:** allow many cheap field devices to send telemetry securely with minimal setup.

Recommended production mode:

- `EDGE_AUTH_MODE=token`
- Devices send `X-Device-Id` + `X-Device-Token`.
- Tokens are stored **hashed** in Postgres (PBKDF2) and verified server-side.

Optional (recommended) bootstrapping:

- `ENABLE_EDGE_ENROLL=true`
- `EDGE_ENROLL_TOKEN` stored in Secret Manager
- Device calls `/api/edge/enroll` once to exchange the enroll token for a **per-device token**.

Operational notes:

- Token rotation is supported (`/api/edge/devices/{id}/rotate_token`).
- Revocation is supported (`/api/edge/devices/{id}/revoke`).

### 2) Ingest plane: ingest token

**Goal:** protect simple direct file uploads.

- `INGEST_AUTH_MODE=token` requires `X-Ingest-Token` for `/api/ingest/upload`.
- Recommended for demos or controlled environments.

For production-scale uploads, prefer **GCS signed URL uploads** instead of direct uploads.

### 3) Ops plane: Cloud Run IAM or task token

**Goal:** keep admin endpoints inaccessible to unauthenticated callers.

- `TASK_AUTH_MODE=iam` (recommended): deploy Cloud Run with `allow_unauthenticated=false` and call with OIDC.
- `TASK_AUTH_MODE=token`: requires `X-Task-Token`.

Defense-in-depth:

- If `TASK_TOKEN` is set, it is enforced even if `TASK_AUTH_MODE=iam`.

---

## Signed URL model (recommended)

For large files and field reliability:

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

- The SPA uses browser-based **GCS signed URL uploads**, so CSP `connect-src` must allow:
  - `https://storage.googleapis.com`

- FastAPI Swagger `/docs` and Redoc `/redoc` load assets from a CDN by default. The CSP is configured so that:
  - **only** the docs routes allow `https://cdn.jsdelivr.net`

If you prefer to avoid CDNs in production, you can disable FastAPI docs (or host the assets yourself).

---

## Cloud Armor / WAF

This repo intentionally starts **without** Cloud Armor to keep costs minimal.

When Cloud Armor adds value:

- you are under sustained abuse (bot traffic, volumetric scanning)
- you need IP allowlists/denylists at the edge
- you want managed WAF rules

If you don’t have those needs yet, you can generally rely on:

- strong tokens + limited surface area
- Cloud Run IAM for internal endpoints
- reasonable request limits + observability

---

## Practical production checklist

- [ ] Use `EDGE_AUTH_MODE=token` and rotate any leaked tokens
- [ ] Keep `EDGE_ENROLL_TOKEN` in Secret Manager (never in git)
- [ ] Use `TASK_AUTH_MODE=iam` for internal endpoints (Cloud Run private)
- [ ] Prefer GCS signed URL uploads for large ingestion workloads
- [ ] Use a private GCS bucket for raw landing + signed URLs for access
- [ ] Keep retention under control (see `docs/MAINTENANCE.md`)

