# Team workflow

This repo is designed to be readable and team-friendly.

## Onboarding (GCP deploy lane)

Recommended first steps for a teammate deploying the Cloud Run demo:

```bash
make init GCLOUD_CONFIG=personal-portfolio PROJECT_ID=YOUR_PROJECT_ID REGION=us-central1
make auth          # only needed once per machine/user
make doctor-gcp
make deploy-gcp
```

Notes:
- `make init` writes to your active gcloud configuration; if you use `GCLOUD_CONFIG=...` it will create/activate a dedicated config.
- If you changed gcloud configs during `make init`, run your next Make command in a fresh invocation.

---

## Defaults + overrides

Most deploy values default from `gcloud config`.
For CI or multi-project work, override explicitly:

```bash
make deploy-gcp PROJECT_ID=my-proj REGION=us-central1 TAG=v1
```

## Remote state

The Cloud Run demo uses a GCS backend. The Makefile creates the bucket automatically:

```bash
make bootstrap-state-gcp
```

For shared environments, keep `backend.hcl` and `terraform.tfvars` in the config bucket and use:

```bash
make tf-config-print-gcp ENV=dev
make tf-config-pull-gcp ENV=dev
make tf-config-push-gcp ENV=dev
```

CI apply/deploy also updates the shared `terraform.tfvars` image pin (`image_name` + `image_tag`) so
plan/drift use the same promoted image.

## Team IAM (Google Groups)

This repo can optionally manage access bindings for common roles (clients/observers, engineers-min, engineers, auditors, platform-admins) using Google Groups.

Set these Make variables when you want Terraform to create IAM bindings:

```bash
make plan-gcp ENV=dev WORKSPACE_DOMAIN=yourdomain.com GROUP_PREFIX=eventpulse
```

See `docs/IAM_STARTER_PACK.md` for the role mapping.

## CI (recommended)

For automated deploys:
- use Workload Identity Federation (no JSON keys)
- require plan output review for IaC changes

See:
- `.github/workflows/ci.yml` (lint/typecheck/test)
- `.github/workflows/terraform-hygiene.yml`
- `.github/workflows/gcp-terraform-plan.yml`
- `.github/workflows/terraform-apply-gcp.yml`
- `.github/workflows/deploy-gcp.yml`
- `.github/workflows/terraform-drift.yml`
- `docs/WIF_GITHUB_ACTIONS.md` (keyless GCP auth for deploy workflows)


## Dependency lockfiles

Generate and commit:
- `uv.lock`
- `pnpm-lock.yaml`

```bash
make lock
```
