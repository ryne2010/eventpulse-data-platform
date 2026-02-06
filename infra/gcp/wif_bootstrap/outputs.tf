output "workload_identity_provider" {
  description = "Set this as GitHub Environment variable: GCP_WIF_PROVIDER"
  value       = module.github_oidc.workload_identity_provider
}

output "ci_service_account_email" {
  description = "Set this as GitHub Environment variable: GCP_WIF_SERVICE_ACCOUNT"
  value       = google_service_account.ci.email
}
