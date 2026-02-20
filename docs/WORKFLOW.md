# Workflow

This repo supports two developer loops:

1. **Local-first platform loop** (Docker Compose)
2. **Cloud demo loop** (GCP / Cloud Run via Terraform)

## Local dev loop

### Start

```bash
make doctor
make up
```

### Validate changes (harness)

```bash
python scripts/harness.py lint
python scripts/harness.py typecheck
python scripts/harness.py test
```

Or via Make shortcuts:

```bash
make lint
make typecheck
make test
```

### Useful ops

```bash
make logs
make down
make reset
```

## GCP demo loop

See:

- `docs/DEPLOY_GCP.md`
- `docs/TEAM_WORKFLOW.md`

Common flow:

```bash
make init GCLOUD_CONFIG=personal-portfolio PROJECT_ID=YOUR_PROJECT_ID REGION=us-central1
make auth
make doctor-gcp
make deploy-gcp
```

## Repo hygiene

- Keep runtime state out of git:
  - `.env` is local-only (use `.env.example` as the template)
  - Postgres data is local-only under `data/pg/`
- Prefer lockfiles:
  - `uv.lock` is committed
  - `pnpm-lock.yaml` should be committed when working on the UI
