# Release runbook (Cloud Run)

This repo is designed to be deployed as a **single Cloud Run service** (API + SPA), with optional
Cloud Tasks async processing.

## Pre-release checklist

-   CI is green on main
-   `make lint typecheck test` passes locally
-   Infra is up to date (Terraform plan is clean)
-   Rollback plan confirmed

## Release steps

### Option A: one-command deploy

```bash
make deploy-gcp
```

This runs:

- Cloud Build image build + push
- Terraform apply
- basic health verification

### Option B: staged deploy

```bash
make build-gcp
make plan-gcp
make apply-gcp
make verify-gcp
```

1.  Build/push the container image (Cloud Build)
2.  Apply Terraform (Cloud Run + IAM + secrets)
3.  Verify `/healthz` + `/api/meta`
4.  Smoke test a small ingestion
5.  Monitor logs + Postgres load

## Rollback

-   Define rollback triggers (error rate, latency, data integrity).
-   Prefer rolling back to the previous Cloud Run revision.
-   Keep rollback steps rehearsed.

Quick rollback options:

- In the Cloud Run console: set traffic back to a previous revision.
- With gcloud: update traffic to the prior revision.

## Post-release

-   Verify logs are clean and latency is stable
-   Confirm devices continue to upload (Devices page)
-   Capture issues and improvements
