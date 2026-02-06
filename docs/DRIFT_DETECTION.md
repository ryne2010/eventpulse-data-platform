# Drift detection (Terraform)

This repo includes a scheduled GitHub Actions workflow:

- `.github/workflows/terraform-drift.yml`

It runs `terraform plan -detailed-exitcode` to detect drift (resources changed outside of Terraform).

## How to enable

1) Bootstrap WIF + CI service account (see `docs/WIF_GITHUB_ACTIONS.md`).
2) Create and upload config to GCS (see `docs/WIF_GITHUB_ACTIONS.md`).
3) Set GitHub Environment variables (per env):
   - `GCP_WIF_PROVIDER`
   - `GCP_WIF_SERVICE_ACCOUNT`
   - `GCP_TF_CONFIG_GCS_PATH`
