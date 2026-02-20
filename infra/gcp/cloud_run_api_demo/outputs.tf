output "service_url" {
  description = "Cloud Run service URL."
  value       = module.cloud_run.service_url
}

output "artifact_repo" {
  description = "Artifact Registry repository ID."
  value       = module.artifact_registry.repository_id
}

output "runtime_service_account" {
  description = "Cloud Run runtime service account email."
  value       = module.service_accounts.runtime_service_account_email
}

output "tasks_invoker_service_account" {
  description = "Service account used for Cloud Tasks OIDC invocation of Cloud Run (when TASK_AUTH_MODE=iam)."
  value       = module.service_accounts.tasks_invoker_service_account_email
}

output "database_url_secret" {
  description = "Secret Manager secret name for DATABASE_URL (add a secret version before starting the service)."
  value       = module.secrets.secret_names["eventpulse-database-url"]
}

output "monitoring_dashboard_name" {
  description = "Cloud Monitoring dashboard resource name (if enabled)."
  value       = try(google_monitoring_dashboard.cloudrun[0].name, null)
}

output "alert_policy_5xx_name" {
  description = "Alert policy resource name (if enabled)."
  value       = try(google_monitoring_alert_policy.cloudrun_5xx[0].name, null)
}

output "alert_policy_latency_name" {
  description = "Alert policy resource name (if enabled)."
  value       = try(google_monitoring_alert_policy.cloudrun_latency_p95[0].name, null)
}

output "raw_bucket" {
  description = "GCS bucket used for the raw landing zone (STORAGE_BACKEND=gcs)."
  value       = google_storage_bucket.raw.name
}

output "cloud_tasks_queue" {
  description = "Cloud Tasks queue name used for async ingestion."
  value       = google_cloud_tasks_queue.ingest.name
}

output "task_token_secret" {
  description = "Secret Manager secret name for TASK_TOKEN (used when allow_unauthenticated=true / TASK_AUTH_MODE=token)."
  value       = module.secrets.secret_names["eventpulse-task-token"]
}

output "ingest_token_secret" {
  description = "Secret Manager secret name for INGEST_TOKEN (used when INGEST_AUTH_MODE=token)."
  value       = module.secrets.secret_names["eventpulse-ingest-token"]
}

output "gcs_finalize_topic" {
  description = "Pub/Sub topic receiving GCS OBJECT_FINALIZE notifications (if enable_gcs_event_ingestion=true)."
  value       = try(google_pubsub_topic.gcs_finalize[0].name, null)
}

output "gcs_finalize_push_subscription" {
  description = "Pub/Sub push subscription delivering finalize events to Cloud Run (if enable_gcs_event_ingestion=true)."
  value       = try(google_pubsub_subscription.gcs_finalize_push[0].name, null)
}
