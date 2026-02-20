# Deploy to Google Cloud Run

This repo supports two lanes:

- **Local lane:** Docker Compose (Postgres + Redis + API + worker)
- **Cloud lane:** Cloud Run + GCS + Cloud Tasks (and optional Pub/Sub event-driven ingestion)

The Terraform in `infra/gcp/cloud_run_api_demo/` provisions:

- Cloud Run service (API + built SPA)
- Artifact Registry repo
- GCS bucket for raw artifacts
- Cloud Tasks queue for async processing
- Secret Manager *containers* for runtime secrets (values are added out-of-band)
- Optional observability (dashboard + alert policies)

Optionally, it can also provision:

- Pub/Sub + GCS notifications for **event-driven ingestion** (GCS finalize → Pub/Sub push → Cloud Run)
- IAM plumbing for **GCS signed URLs** (no service account keys)
- Cloud Scheduler jobs for routine ops (**reclaim stuck ingestions**, optional retention prune)

What it does **not** provision (by design):

- **Postgres itself** (e.g., Cloud SQL). You provide a `DATABASE_URL` and EventPulse uses it for metadata + curated tables.

---

## Prereqs

- `gcloud` authenticated for your target project
- Terraform installed
- Container build permissions in the project

Recommended one-time setup:

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
gcloud config set run/region us-central1
```

---

## First-time deploy: secrets are required

EventPulse reads the following secrets at runtime:

- `eventpulse-database-url` → `DATABASE_URL` (**required**)
- `eventpulse-task-token` → `TASK_TOKEN` (**required only when** `allow_unauthenticated=true`)
- `eventpulse-ingest-token` → `INGEST_TOKEN` (**required only when** `INGEST_AUTH_MODE=token`)
- `eventpulse-edge-enroll-token` → `EDGE_ENROLL_TOKEN` (**required only when** `enable_edge_enroll=true`)

Terraform creates the **secret containers** only. You add secret **versions** using Make targets.

A clean first-time flow:

```bash
# 1) Create prerequisite infra (APIs, Artifact Registry, service accounts, secret containers)
make infra-gcp PROJECT_ID=your-project REGION=us-central1 ENV=dev

# 2) Add secret versions (paste values, then Ctrl-D)
make db-secret PROJECT_ID=your-project
make task-token-secret PROJECT_ID=your-project   # only needed for public deploys
make ingest-token-secret PROJECT_ID=your-project  # only needed when ingest token auth is enabled

# Optional (fast field provisioning): enable edge enrollment and add the enroll token secret
TF_VAR_enable_edge_enroll=true make edge-enroll-token-secret PROJECT_ID=your-project

# 3) Build + deploy
make deploy-gcp PROJECT_ID=your-project REGION=us-central1 ENV=dev
```

Tip: `make deploy-gcp` now runs a **secrets preflight** (`make check-secrets-gcp`) and will fail early with a clear message if versions are missing.

---

## Default demo deploy (public Cloud Run)

This is the simplest deploy:

```bash
make deploy-gcp PROJECT_ID=your-project REGION=us-central1 ENV=dev
```

Defaults:

- Cloud Run service is **public** (`allow_unauthenticated=true`).
- Cloud Tasks uses `TASK_AUTH_MODE=token` and calls internal endpoints with `X-Task-Token`.
- Large-file ingest is supported via direct-to-GCS upload + `POST /api/ingest/from_gcs`.

Verify:

```bash
make verify-gcp PROJECT_ID=your-project REGION=us-central1 ENV=dev
```

UI:

- Open the service URL (see `make url-gcp`).
- Use **Upload** to mint a signed URL (if enabled) and register an ingestion.
- Use **Ops** to set the task token in `localStorage` (required for internal endpoints when in token mode).

---

## Edge devices (RPi over 5G)

For field devices (Raspberry Pi sensors over a 5G SIM), the recommended posture is:

- **Public Cloud Run** (`allow_unauthenticated=true`) so devices can reach it over the internet
- **Per-device token auth** on the API edge endpoints (`EDGE_AUTH_MODE=token`)
- **Direct-to-GCS signed URL uploads** for reliability (`ENABLE_EDGE_SIGNED_URLS=true`)
- (Recommended for deployment speed) **bootstrap enrollment** via `EDGE_ENROLL_TOKEN` + `POST /api/edge/enroll`

Why this works well on Cloud Run:

- avoids request size/time limits on the API
- reduces API bandwidth (device uploads straight to GCS)
- supports token rotation/revocation per device

### Cost + abuse guardrails (start lean)

To keep costs minimal and deployments fast, start **without** Cloud Armor and rely on:

- strong device tokens + rotation/revocation
- signed URL uploads (reduces API load)
- Cloud Run `max_instances` (caps cost blast radius)

If you later need WAF/rate limiting at the edge, add Cloud Armor behind an external HTTP(S) Load Balancer.

Deploy with:

```bash
TF_VAR_allow_unauthenticated=true \
TF_VAR_edge_auth_mode=token \
TF_VAR_enable_edge_signed_urls=true \
TF_VAR_enable_edge_enroll=true \
make deploy-gcp PROJECT_ID=your-project REGION=us-central1 ENV=dev
```

Optional: set `TF_VAR_enable_signed_urls=true` if you want the internal `/api/uploads/gcs_signed_url` helper for human uploads (protected by internal auth).

Note: Terraform grants the runtime service account the IAM permission needed to mint signed URLs when either `enable_edge_signed_urls` or `enable_signed_urls` is enabled.

Then configure runtime env vars (Terraform already wires most; confirm in the Cloud Run service):

- `STORAGE_BACKEND=gcs`
- `EDGE_AUTH_MODE=token`
- `EDGE_ALLOWED_DATASETS=edge_telemetry`
- `ENABLE_EDGE_SIGNED_URLS=true`
- `EDGE_OFFLINE_THRESHOLD_SECONDS=600` (optional; device offline heuristic)

Provision each device using the internal admin endpoint:

- Option A (recommended): set `EDGE_ENROLL_TOKEN` on the Pi and let the agent self-enroll.
- Option B: `POST /internal/admin/devices` (returns `device_token` once)

Then run the edge agent container on the Pi with:

- `EDGE_API_BASE_URL=https://YOUR_CLOUD_RUN_URL`
- `EDGE_DEVICE_ID=rpi-001`
- `EDGE_ENROLL_TOKEN=...` (recommended) OR `EDGE_DEVICE_TOKEN=...` (manual provisioning)
- `EDGE_UPLOAD_MODE=signed_url`

See: `docs/EDGE_RPI.md`.

## Private deploy (IAM) with signed URLs + event-driven ingestion

This is the recommended "production-ish" posture:

- Cloud Run is **private** (Cloud Run IAM)
- Cloud Tasks and Pub/Sub push authenticate using **OIDC**
- Clients can upload large files directly to GCS using **signed URLs**
- GCS finalize events can auto-create ingestion records and enqueue processing

One command:

```bash
make deploy-gcp-private PROJECT_ID=your-project REGION=us-central1 ENV=dev
```

Under the hood this sets:

- `TF_VAR_allow_unauthenticated=false`
- `TF_VAR_enable_signed_urls=true`
- `TF_VAR_enable_gcs_event_ingestion=true`

### Note on the UI in IAM mode

The SPA does **not** attach `Authorization: Bearer …` identity tokens on requests.

So for a private Cloud Run deployment you typically:

- Use **CLI** calls (curl + `gcloud auth print-identity-token`) for internal endpoints, or
- Put the service behind an auth layer (IAP / Identity Platform / reverse proxy) if you want interactive UI access.

---

## Cloud Scheduler (optional ops hygiene)

To enable scheduled ops jobs (requires private Cloud Run):

```bash
TF_VAR_allow_unauthenticated=false \
TF_VAR_enable_scheduler_jobs=true \
make apply-gcp PROJECT_ID=your-project REGION=us-central1 ENV=dev
```

Defaults:

- `reclaim_stuck` runs every 15 minutes.
- `prune` is **disabled** by default.

To enable the prune job (recommended: start with dry-run):

```bash
TF_VAR_allow_unauthenticated=false \
TF_VAR_enable_scheduler_jobs=true \
TF_VAR_enable_prune_job=true \
TF_VAR_prune_dry_run=true \
make apply-gcp PROJECT_ID=your-project REGION=us-central1 ENV=dev
```

---

## Uploading large files on Cloud Run

### Option A: Signed URL upload (recommended)

1) Mint a signed URL:

```bash
URL=$(terraform -chdir=infra/gcp/cloud_run_api_demo output -raw service_url)

FILE=./data/samples/parcels_baseline.xlsx
SHA=$(shasum -a 256 "$FILE" | awk '{print $1}')

# Auth headers:
# - IAM mode (private Cloud Run):
AUTH_HEADERS=(-H "Authorization: Bearer $(gcloud auth print-identity-token --audiences=${URL})")

# - Token mode (public Cloud Run):
# AUTH_HEADERS=(-H "X-Task-Token: ${TASK_TOKEN}")

RESP=$(curl -sS -X POST "${URL}/api/uploads/gcs_signed_url" \
  "${AUTH_HEADERS[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"dataset":"parcels","filename":"parcels_baseline.xlsx","sha256":"'"$SHA"'","source":"curl"}')

echo "$RESP" | jq .
```

2) Upload the file directly to GCS:

```bash
UPLOAD_URL=$(echo "$RESP" | jq -r .upload_url)

CTYPE=$(echo "$RESP" | jq -r '.required_headers["Content-Type"]')
META_FN=$(echo "$RESP" | jq -r '.required_headers["x-goog-meta-original-filename"]')
META_DS=$(echo "$RESP" | jq -r '.required_headers["x-goog-meta-dataset"]')
META_SRC=$(echo "$RESP" | jq -r '.required_headers["x-goog-meta-source"] // empty')

HDRS=(-H "Content-Type: $CTYPE" -H "x-goog-meta-original-filename: $META_FN" -H "x-goog-meta-dataset: $META_DS")
if [ -n "$META_SRC" ]; then HDRS+=( -H "x-goog-meta-source: $META_SRC" ); fi

curl -sS -X PUT "${HDRS[@]}" --upload-file "$FILE" "$UPLOAD_URL"
```

3) If `enable_gcs_event_ingestion=true`, the ingestion record is created automatically.

Poll `GET /api/ingestions` until the new ingestion moves to `LOADED`.

### Option B: Manual GCS upload + register

```bash
URL=$(terraform -chdir=infra/gcp/cloud_run_api_demo output -raw service_url)
RAW_BUCKET=$(terraform -chdir=infra/gcp/cloud_run_api_demo output -raw raw_bucket)

gsutil cp ./data/samples/parcels_baseline.xlsx "gs://${RAW_BUCKET}/uploads/parcels_baseline.xlsx"

curl -sS -X POST "${URL}/api/ingest/from_gcs" \
  "${AUTH_HEADERS[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"dataset":"parcels","gcs_uri":"gs://'"${RAW_BUCKET}"'/uploads/parcels_baseline.xlsx","source":"gsutil"}' | jq .
```

---

## Troubleshooting

- **Signed URL generation fails** with a 500/metadata error:
  - This endpoint is intended for Cloud Run runtime; it uses the metadata server.

- **Signed URL upload returns 403**:
  - Make sure you are providing the `required_headers` exactly as returned.

- **GCS finalize events never create ingestions**:
  - Ensure `enable_gcs_event_ingestion=true` and `allow_unauthenticated=false`.
  - Check Pub/Sub subscription delivery errors in the Cloud Console.
  - Confirm Cloud Run IAM invoker includes the subscription's OIDC service account.

- **Tasks are created but ingestion stays PROCESSING**:
  - Check Cloud Run logs for the job handler.
  - Use the reclaimer endpoint to recover stuck ingestions.
