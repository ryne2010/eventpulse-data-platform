variable "project_id" {
  type        = string
  description = "GCP project ID."
}

variable "github_repository" {
  type        = string
  description = "GitHub repository in OWNER/REPO format (e.g., 'ryne2010/eventpulse-data-platform')."
}

variable "tfstate_bucket_name" {
  type        = string
  description = "GCS bucket name used for Terraform remote state."
}

variable "config_bucket_name" {
  type        = string
  description = "GCS bucket name used to store backend.hcl + terraform.tfvars (single source of truth)."
}

variable "ci_service_account_id" {
  type        = string
  description = "Service account id (account_id) used by GitHub Actions via WIF."
  default     = "sa-eventpulse-ci"
}

variable "allowed_branches" {
  type        = list(string)
  description = "Allowed GitHub branches for OIDC auth (e.g., ['main'])."
  default     = ["main"]
}

variable "enable_config_bucket_write" {
  type        = bool
  description = "If true, grant CI roles/storage.objectAdmin on the config bucket (lets CI update terraform.tfvars)."
  default     = true
}

variable "ci_project_roles" {
  type        = list(string)
  description = "Project-level roles granted to the CI service account (demo defaults)."
  default = [
    "roles/run.admin",
    "roles/artifactregistry.admin",
    "roles/iam.serviceAccountUser",
    "roles/monitoring.admin",
    "roles/logging.admin",
    "roles/secretmanager.admin",
    "roles/serviceusage.serviceUsageAdmin",
  ]
}
