# Cloud Run API Demo (Terraform root)

This Terraform root deploys EventPulse to Cloud Run with a serverless-friendly configuration:

- GCS raw landing zone (`STORAGE_BACKEND=gcs`)
- Cloud Tasks async ingestion (`QUEUE_BACKEND=cloud_tasks`)
- Postgres metadata + curated tables (provide `DATABASE_URL` via Secret Manager)

Optional public ingest hardening:

- `TF_VAR_ingest_auth_mode=token` → sets `INGEST_AUTH_MODE=token` on the service and wires `INGEST_TOKEN` from Secret Manager.

Optional edge fleet convenience:

- `TF_VAR_enable_edge_enroll=true` → wires `EDGE_ENROLL_TOKEN` from Secret Manager and enables `/api/edge/enroll`
  for fast field-device provisioning.

See:

- `docs/DEPLOY_GCP.md`

## Optional: Cloud Scheduler jobs

This stack can optionally create Cloud Scheduler jobs for routine operations:

- reclaim stuck ingestions (PROCESSING without heartbeat)
- optional retention prune (audit + old ingestion metadata)

Enable:

```bash
TF_VAR_allow_unauthenticated=false \
TF_VAR_enable_scheduler_jobs=true \
make apply-gcp
```

Enable prune job (recommended: start with dry-run):

```bash
TF_VAR_allow_unauthenticated=false \
TF_VAR_enable_scheduler_jobs=true \
TF_VAR_enable_prune_job=true \
TF_VAR_prune_dry_run=true \
make apply-gcp
```
