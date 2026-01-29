# Optional GCP Deployment (Design Notes + Skeleton)

This repo is **local-first**. For cloud, the recommended mapping is:

- Raw landing: **Cloud Storage**
- Eventing: **Pub/Sub**
- Processing: **Cloud Run** (API + worker)
- Warehouse: **BigQuery**
- Secrets: **Secret Manager**
- Observability: **Cloud Logging/Monitoring**

## Practical cloud patterns

### Pattern A: Storage event → Pub/Sub → Cloud Run worker
1) GCS bucket notification publishes to Pub/Sub
2) Push subscription calls Cloud Run `/ingest/gcs_event`
3) Worker fetches the object from GCS, validates, and loads curated tables

Pros: serverless, event-driven, good fit for file drops  
Cons: requires IAM + object fetch logic + careful idempotency

### Pattern B: Scheduled poller (when source isn't event-friendly)
1) Cloud Scheduler triggers Cloud Run job periodically
2) Job checks inbox/FTP/SFTP for new files, downloads, writes to GCS raw
3) Pub/Sub triggers processing

Pros: works with “manual email attachment” sources  
Cons: not fully event-driven at the edge

## Terraform skeleton
See `infra/gcp/terraform/` for a starter layout. It intentionally omits full deployment wiring
so you can integrate with your preferred baseline (e.g., the `terraform-gcp-platform-baseline` repo).

If you want the BigQuery loader, implement it in `eventpulse/loaders/bigquery.py`.
