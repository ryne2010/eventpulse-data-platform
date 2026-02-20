# Cloud Scheduler jobs
#
# These jobs are optional (toggle via enable_scheduler_jobs). They are meant to
# illustrate real-world "ops hygiene" for an event-driven ingestion service:
# - reclaim stuck ingestions (PROCESSING without heartbeat)
# - optional retention prune (audit + old ingestion metadata)
#
# Important:
# - Requires allow_unauthenticated=false (private Cloud Run). Jobs authenticate
#   using OIDC tokens, enforced by Cloud Run IAM.
# - The Cloud Scheduler service agent is granted token-creator on the invoker SA
#   (see main.tf).

locals {
  scheduler_enabled = var.enable_scheduler_jobs
}

resource "google_cloud_scheduler_job" "reclaim_stuck" {
  count = local.scheduler_enabled ? 1 : 0

  name        = "eventpulse-${var.env}-reclaim-stuck"
  description = "Reclaim ingestions stuck in PROCESSING (no heartbeat)"

  schedule  = var.reclaim_schedule
  time_zone = var.scheduler_timezone

  attempt_deadline = "300s"

  http_target {
    http_method = "POST"
    uri         = "${module.cloud_run.service_uri}/internal/admin/reclaim_stuck"

    headers = {
      "Content-Type" = "application/json"
      "X-Actor"      = "scheduler"
    }

    body = base64encode(jsonencode({
      older_than_seconds = var.reclaim_older_than_seconds
      limit              = var.reclaim_limit
    }))

    oidc_token {
      service_account_email = module.service_accounts.tasks_invoker_service_account_email
      audience              = "${module.cloud_run.service_uri}/internal/admin/reclaim_stuck"
    }
  }

  depends_on = [module.cloud_run]
}

resource "google_cloud_scheduler_job" "prune" {
  count = (local.scheduler_enabled && var.enable_prune_job) ? 1 : 0

  name        = "eventpulse-${var.env}-prune"
  description = "Retention prune: audit + old ingestion metadata (use dry-run first)"

  schedule  = var.prune_schedule
  time_zone = var.scheduler_timezone

  attempt_deadline = "900s"

  http_target {
    http_method = "POST"
    uri         = "${module.cloud_run.service_uri}/internal/admin/prune"

    headers = {
      "Content-Type" = "application/json"
      "X-Actor"      = "scheduler"
    }

    body = base64encode(jsonencode({
      dry_run                    = var.prune_dry_run
      confirm                    = "PRUNE"
      audit_older_than_days      = var.prune_audit_older_than_days
      audit_limit                = 50000
      ingestions_older_than_days = var.prune_ingestions_older_than_days
      ingestions_limit           = 50000
    }))

    oidc_token {
      service_account_email = module.service_accounts.tasks_invoker_service_account_email
      audience              = "${module.cloud_run.service_uri}/internal/admin/prune"
    }
  }

  depends_on = [module.cloud_run]
}
