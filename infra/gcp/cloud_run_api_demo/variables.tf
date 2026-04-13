variable "project_id" {
  type        = string
  description = "GCP project ID."
}

variable "region" {
  type        = string
  description = "GCP region."
  default     = "us-central1"
}

variable "env" {
  type        = string
  description = "Deployment environment label (dev|stage|prod). Used for naming + labels."
  default     = "dev"

  validation {
    condition     = contains(["dev", "stage", "prod"], var.env)
    error_message = "env must be one of: dev, stage, prod"
  }
}

variable "service_name" {
  type        = string
  description = "Cloud Run service name."
  default     = "eventpulse-dev"
}

variable "artifact_repo_name" {
  type        = string
  description = "Artifact Registry repository name."
  default     = "eventpulse"
}

variable "image" {
  type        = string
  description = <<EOT
Optional full container image URI.

If empty, the image URI is derived from:
- region
- project_id
- artifact_repo_name
- image_name
- image_tag
EOT
  default     = ""
}

variable "image_name" {
  type        = string
  description = "Artifact Registry image name (the part after the repo)."
  default     = "eventpulse-api"
}

variable "image_tag" {
  type        = string
  description = "Artifact Registry image tag used when deriving the image URI."
  default     = "latest"

  validation {
    condition     = length(var.image) > 0 || length(trimspace(var.image_tag)) > 0
    error_message = "Set either image (full URI) or image_tag (when using the derived image URI)."
  }
}

variable "allow_unauthenticated" {
  type        = bool
  description = "Whether the Cloud Run service is public."
  default     = true
}

variable "ingest_auth_mode" {
  type        = string
  description = "Auth mode for the public ingest endpoint (/api/ingest/upload): none|token."
  default     = "none"

  validation {
    condition     = contains(["none", "token"], lower(var.ingest_auth_mode))
    error_message = "ingest_auth_mode must be one of: none, token"
  }
}

variable "min_instances" {
  type        = number
  description = "Minimum Cloud Run instances (0 for scale-to-zero)."
  default     = 0
}

variable "max_instances" {
  type        = number
  description = "Maximum Cloud Run instances (cost guardrail)."
  default     = 1
}

variable "cloud_sql_instance_connection_name" {
  type        = string
  description = "Optional Cloud SQL instance connection name (PROJECT:REGION:INSTANCE). Enables /cloudsql mount in Cloud Run for unix-socket DATABASE_URL values."
  default     = ""
}

variable "enable_vpc_connector" {
  type        = bool
  description = "Create and attach a Serverless VPC Access connector (NOT free)."
  default     = false
}

variable "vpc_egress" {
  type        = string
  description = "VPC egress setting when a connector is attached."
  default     = "PRIVATE_RANGES_ONLY"
}

# -----------------------------
# Team IAM (Google Groups)
# -----------------------------

variable "workspace_domain" {
  type        = string
  description = "Google Workspace domain used for group-based IAM (e.g., company.com). If empty, no group IAM bindings are created."
  default     = ""
}

variable "group_prefix" {
  type        = string
  description = "Prefix used to derive group emails (e.g., eventpulse-engineers@<domain>)."
  default     = "eventpulse"
}

# -----------------------------
# Observability as code
# -----------------------------

variable "enable_observability" {
  type        = bool
  description = "Create a Cloud Monitoring dashboard + basic alerts for the Cloud Run service."
  default     = true
}

variable "notification_channels" {
  type        = list(string)
  description = "Optional Monitoring notification channel IDs to attach to alert policies."
  default     = []
}


# --- Staff-level hygiene toggles (recommended defaults) ---

variable "enable_project_iam" {
  type        = bool
  description = <<EOT
If true, this stack will manage *project-level* IAM bindings for your Google Groups.

Staff-level recommendation:
- Manage project-level IAM centrally in the Terraform GCP Platform Baseline repo (repo 3),
  and keep application repos focused on *app-scoped* resources.
- Leave this false unless you explicitly want this repo to be standalone.
EOT
  default     = false
}

variable "log_retention_days" {
  type        = number
  description = "Retention (days) for the service-scoped log bucket used for client log views."
  default     = 30
}

variable "enable_log_views" {
  type        = bool
  description = "Create a service-scoped log bucket + Logs Router sink + log view for least-privilege client access."
  default     = true
}

variable "enable_slo" {
  type        = bool
  description = "Create a Service Monitoring Service + Availability SLO + burn-rate alert policy."
  default     = true
}

# -----------------------------
# Event-driven ingestion (GCS -> Pub/Sub push -> Cloud Run)
# -----------------------------

variable "enable_signed_urls" {
  type        = bool
  description = "Enable the /api/uploads/gcs_signed_url endpoint (recommended only for a private service)."
  default     = false
}

variable "signed_url_expires_seconds" {
  type        = number
  description = "Signed URL TTL in seconds (max 7 days)."
  default     = 900
}

variable "enable_gcs_event_ingestion" {
  type        = bool
  description = "Provision Pub/Sub + GCS notifications and enable /internal/events/gcs_finalize. Requires a private Cloud Run service (allow_unauthenticated=false)."
  default     = false

  validation {
    condition     = !(var.enable_gcs_event_ingestion && var.allow_unauthenticated)
    error_message = "enable_gcs_event_ingestion requires allow_unauthenticated=false (Pub/Sub push uses OIDC + Cloud Run IAM)."
  }
}

# -----------------------------
# Cloud Scheduler (optional)
# -----------------------------

variable "enable_scheduler_jobs" {
  type        = bool
  description = "Create Cloud Scheduler jobs for routine ops (reclaim stuck ingestions, optional retention prune). Requires a private Cloud Run service (allow_unauthenticated=false)."
  default     = false

  validation {
    condition     = !(var.enable_scheduler_jobs && var.allow_unauthenticated)
    error_message = "enable_scheduler_jobs requires allow_unauthenticated=false (jobs authenticate via OIDC + Cloud Run IAM)."
  }
}

variable "scheduler_timezone" {
  type        = string
  description = "Time zone used for Cloud Scheduler jobs."
  default     = "America/Denver"
}

variable "reclaim_schedule" {
  type        = string
  description = "Cron schedule for the reclaim-stuck job."
  default     = "*/15 * * * *"
}

variable "reclaim_older_than_seconds" {
  type        = number
  description = "Reclaim ingestions stuck in PROCESSING older than this many seconds."
  default     = 1800
}

variable "reclaim_limit" {
  type        = number
  description = "Max stuck ingestions to reclaim per job run."
  default     = 50
}

variable "enable_prune_job" {
  type        = bool
  description = "If true, create a scheduled retention prune job (audit + old ingestion metadata)."
  default     = false
}

variable "prune_schedule" {
  type        = string
  description = "Cron schedule for the prune job."
  default     = "0 4 * * *"
}

variable "prune_dry_run" {
  type        = bool
  description = "If true, the scheduled prune job runs in dry-run mode (recommended first)."
  default     = true
}

variable "prune_audit_older_than_days" {
  type        = number
  description = "Delete audit events older than N days (when prune job runs, and when prune_dry_run=false)."
  default     = 30
}

variable "prune_ingestions_older_than_days" {
  type        = number
  description = "Delete ingestion metadata older than N days (when prune job runs, and when prune_dry_run=false)."
  default     = 90
}
