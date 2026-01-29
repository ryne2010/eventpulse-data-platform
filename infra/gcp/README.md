# GCP Infrastructure Skeleton

This folder is intentionally minimal.

Recommended approach:
- Use your existing Terraform baseline (landing zone, IAM, networking, Cloud Run patterns)
- Add project-specific resources (bucket, Pub/Sub, BigQuery datasets/tables) here

See `docs/gcp_deploy.md` for suggested patterns.

If you want a working example, you can wire this repo into the
`terraform-gcp-platform-baseline` modules and deploy:
- Cloud Run API
- Cloud Run worker (or Cloud Run job)
- Storage bucket for raw
- Pub/Sub topic/subscription for ingestion events
- BigQuery dataset for curated tables
