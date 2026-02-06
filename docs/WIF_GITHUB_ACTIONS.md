# Workload Identity Federation (WIF) for GitHub Actions

This repo supports keyless GitHub Actions authentication to GCP via **Workload Identity Federation (WIF)**.

Goals:
- no long-lived JSON keys
- short-lived OIDC tokens
- GitHub Environments store only a few variables
- Terraform config lives in one place (GCS)

## What lives where

### In this repo
- `infra/gcp/wif_bootstrap/` creates:
  - a CI service account
  - a Workload Identity Pool + Provider scoped to your `OWNER/REPO`
  - bucket IAM so CI can read config + read/write Terraform state

### In GCS (single source of truth)
Store two files per environment:
- `backend.hcl` (remote state config)
- `terraform.tfvars` (Terraform variables)

### In GitHub (per environment)
Repo → Settings → Environments → `<env>` → Variables:
- `GCP_WIF_PROVIDER`
- `GCP_WIF_SERVICE_ACCOUNT`
- `GCP_TF_CONFIG_GCS_PATH` (example: `gs://MY_PROJECT-config/eventpulse/dev`)

## 0) One-time: create the buckets

Teaching point:
- Terraform state and config files are **production data**. Treat them like it.

Use your local `gcloud config` for project/region:

```bash
PROJECT_ID="$(gcloud config get-value project)"
REGION="$(gcloud config get-value run/region)"

TFSTATE_BUCKET="${PROJECT_ID}-tfstate"
CONFIG_BUCKET="${PROJECT_ID}-config"

# Terraform state bucket (remote backend)
gcloud storage buckets describe "gs://${TFSTATE_BUCKET}" >/dev/null 2>&1   || gcloud storage buckets create "gs://${TFSTATE_BUCKET}"     --location="${REGION}"     --uniform-bucket-level-access     --public-access-prevention

gcloud storage buckets update "gs://${TFSTATE_BUCKET}" --versioning

# Terraform config bucket (backend.hcl + terraform.tfvars)
gcloud storage buckets describe "gs://${CONFIG_BUCKET}" >/dev/null 2>&1   || gcloud storage buckets create "gs://${CONFIG_BUCKET}"     --location="${REGION}"     --uniform-bucket-level-access     --public-access-prevention

gcloud storage buckets update "gs://${CONFIG_BUCKET}" --versioning
```

## 1) Bootstrap WIF + CI service account (Terraform)

```bash
cd infra/gcp/wif_bootstrap

terraform init -reconfigure   -backend-config="bucket=${TFSTATE_BUCKET}"   -backend-config="prefix=eventpulse/wif_bootstrap"

terraform apply -auto-approve   -var "project_id=${PROJECT_ID}"   -var "github_repository=OWNER/REPO"   -var "tfstate_bucket_name=${TFSTATE_BUCKET}"   -var "config_bucket_name=${CONFIG_BUCKET}"

terraform output -raw workload_identity_provider
terraform output -raw ci_service_account_email
```

Copy the two outputs into GitHub Environment variables:
- `GCP_WIF_PROVIDER`
- `GCP_WIF_SERVICE_ACCOUNT`

## 2) Create config in GCS

Choose an env and prefix:

```bash
ENV=dev
GCP_TF_CONFIG_GCS_PATH="gs://${CONFIG_BUCKET}/eventpulse/${ENV}"
```

Example `backend.hcl`:

```hcl
bucket = "${TFSTATE_BUCKET}"
prefix = "eventpulse/${ENV}"
```

Example `terraform.tfvars` (minimum):

```hcl
project_id         = "${PROJECT_ID}"
region             = "${REGION}"
env                = "dev"
service_name       = "eventpulse-dev"
artifact_repo_name = "eventpulse"

# Used by CI to compute the full image URI (optional).
image_name = "eventpulse-api"

# CI will update this on each deploy.
image = "${REGION}-docker.pkg.dev/${PROJECT_ID}/eventpulse/eventpulse-api:latest"
```

Upload:

```bash
gcloud storage cp backend.hcl "${GCP_TF_CONFIG_GCS_PATH}/backend.hcl"
gcloud storage cp terraform.tfvars "${GCP_TF_CONFIG_GCS_PATH}/terraform.tfvars"
```

Now set GitHub Environment variable:
- `GCP_TF_CONFIG_GCS_PATH`

## 3) Workflows

- Manual plan/apply/drift:
  - `.github/workflows/gcp-terraform-plan.yml`
  - `.github/workflows/terraform-apply-gcp.yml`
  - `.github/workflows/terraform-drift.yml`

- Push-to-main build+deploy (dev):
  - `.github/workflows/gcp-build-and-deploy.yml`

Gotcha:
- `gcp-build-and-deploy.yml` updates `terraform.tfvars` in GCS to pin the image tag.
  - This requires the CI service account to have `roles/storage.objectAdmin` on the config bucket.
  - If you don’t want CI writing config, set `enable_config_bucket_write=false` in `wif_bootstrap` and update config manually.
