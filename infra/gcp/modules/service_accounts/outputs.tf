output "runtime_service_account_email" {
  value       = google_service_account.runtime.email
  description = "Runtime service account email."
}

output "ci_service_account_email" {
  value       = var.create_ci_account ? google_service_account.ci[0].email : null
  description = "CI service account email (if created)."
}

output "tasks_invoker_service_account_email" {
  value       = var.create_tasks_invoker_account ? google_service_account.tasks_invoker[0].email : null
  description = "Service account email used for Cloud Tasks OIDC invocation of Cloud Run (if created)."
}
