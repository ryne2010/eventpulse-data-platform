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
