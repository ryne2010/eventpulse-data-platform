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

- Pub/Sub + GCS notifications for **event-driven ingestion** (GCS finalize -> Pub/Sub push -> Cloud Run)
- IAM plumbing for **GCS signed URLs** (no service account keys)
- Cloud Scheduler jobs for routine ops (**reclaim stuck ingestions**, optional retention prune)

What it does **not** provision (by design):

- **Postgres itself** (for example Cloud SQL). You provide a `DATABASE_URL` and EventPulse uses it for metadata + curated tables.

If your `DATABASE_URL` uses the Cloud SQL unix-socket form (`host=/cloudsql/...`), also set:

- `TF_VAR_cloud_sql_instance_connection_name=PROJECT:REGION:INSTANCE`

This mounts `/cloudsql` in Cloud Run and grants `roles/cloudsql.client` to the runtime service account.

---

## Prereqs

- `gcloud` authenticated for your target project
- Terraform installed
- Container build permissions in the project

Terraform provider versions are pinned via `infra/gcp/cloud_run_api_demo/.terraform.lock.hcl`.
Keep that file committed so local, CI, and Cloud Run deploy lanes resolve the same provider builds.

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

- `eventpulse-database-url` -> `DATABASE_URL` (**required**)
- `eventpulse-task-token` -> `TASK_TOKEN` (**required only when** `allow_unauthenticated=true`)
- `eventpulse-ingest-token` -> `INGEST_TOKEN` (**required only when** `INGEST_AUTH_MODE=token`)

Terraform creates the **secret containers** only. You add secret **versions** using Make targets.

A clean first-time flow:

```bash
# 1) Create prerequisite infra (APIs, Artifact Registry, service accounts, secret containers)
make infra-gcp PROJECT_ID=your-project REGION=us-central1 ENV=dev

# 2) Add secret versions (paste values, then Ctrl-D)
make db-secret PROJECT_ID=your-project
make task-token-secret PROJECT_ID=your-project    # only needed for public deploys
make ingest-token-secret PROJECT_ID=your-project  # only needed when ingest token auth is enabled

# 3) Build + deploy
make deploy-gcp PROJECT_ID=your-project REGION=us-central1 ENV=dev
```

Cloud SQL socket example:

```bash
TF_VAR_cloud_sql_instance_connection_name=your-project:us-central1:your-pg \
make deploy-gcp PROJECT_ID=your-project REGION=us-central1 ENV=dev
```

Tip: `make deploy-gcp` runs a **secrets preflight** (`make check-secrets-gcp`) and fails early if required secret versions are missing.

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

## Private deploy (IAM) with signed URLs + event-driven ingestion

This is the recommended production posture:

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

The SPA does **not** attach `Authorization: Bearer ...` identity tokens on requests.

So for a private Cloud Run deployment you typically:

- Use CLI calls (`curl` + `gcloud auth print-identity-token`) for internal endpoints, or
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
  -d '{"dataset":"parcels","gcs_uri":"gs://'"$RAW_BUCKET"'/uploads/parcels_baseline.xlsx","source":"manual"}'
```
