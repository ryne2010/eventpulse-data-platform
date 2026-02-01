# Cloud Run API deployment (Terraform) — EventPulse

This Terraform root deploys the **EventPulse API + UI** as a single Cloud Run service.

What this demonstrates:
- remote Terraform state (GCS)
- plan/apply separation (team-friendly)
- Artifact Registry + Cloud Build build flow
- Secret Manager first-class dependency (DATABASE_URL)
- optional Google Groups IAM starter pack
- optional dashboards + alerts (observability as code)

## Recommended workflow

Use the repo root Makefile:

```bash
make deploy-gcp
```

Or:

```bash
make plan-gcp
make apply-gcp
```

## Configuration knobs

| Variable | Default | Description |
|---|---:|---|
| `ENV` | `dev` | Environment label (dev|stage|prod). Drives naming + labels. |
| `SERVICE_NAME` | `eventpulse-$(ENV)` | Cloud Run service name. |
| `WORKSPACE_DOMAIN` | (empty) | Enables group-based IAM if set. |
| `GROUP_PREFIX` | `eventpulse` | Prefix used to derive group emails. |
| `ENABLE_OBSERVABILITY` | `true` | Create a dashboard + 2 basic alert policies. |

## DATABASE_URL secret

Terraform creates the secret container `eventpulse-database-url` but **does not** set a value.

Add a version before the service can start successfully:

```bash
echo "postgresql://USER:PASSWORD@HOST:5432/eventpulse" | \
  gcloud secrets versions add eventpulse-database-url --data-file=-
```

## Next docs

- `docs/DEPLOY_GCP.md` — end-to-end deploy steps
- `docs/IAM_STARTER_PACK.md` — group roles (clients / engineers / auditors)
- `docs/OBSERVABILITY.md` — dashboards + alert policies
