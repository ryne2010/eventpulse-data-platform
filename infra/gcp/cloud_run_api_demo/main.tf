locals {
  labels = {
    app = "eventpulse-data-platform"
    env = var.env
  }

  # Names kept deterministic (good for demo / teardown).
  raw_bucket_name   = "${var.project_id}-eventpulse-raw-${var.env}"
  tasks_queue_name  = "eventpulse-${var.env}"
  raw_bucket_prefix = "raw"

  # Runtime configuration for the API.
  # NOTE: DATABASE_URL is provided via Secret Manager (see `module.secrets`).
  env_vars = {
    APP_ENV                 = var.env
    LOG_LEVEL               = "INFO"
    LOG_FORMAT              = "json"
    CONTRACTS_DIR           = "/app/data/contracts"
    ENABLE_INGEST_FROM_PATH = "false" # Cloud Run doesn't have the /data/incoming volume

    # Raw landing zone
    STORAGE_BACKEND = "gcs"
    RAW_GCS_BUCKET  = local.raw_bucket_name
    RAW_GCS_PREFIX  = local.raw_bucket_prefix

    # Async ingestion
    QUEUE_BACKEND        = "cloud_tasks"
    CLOUD_TASKS_PROJECT  = var.project_id
    CLOUD_TASKS_LOCATION = var.region
    CLOUD_TASKS_QUEUE    = local.tasks_queue_name
    CLOUD_TASKS_DISPATCH_DEADLINE_SECONDS = "900"

    # Internal endpoint auth
    # - token: Cloud Run can be public; Cloud Tasks includes X-Task-Token
    # - iam:   Cloud Run requires auth; Cloud Tasks uses OIDC
    TASK_AUTH_MODE                  = var.allow_unauthenticated ? "token" : "iam"
    TASK_OIDC_SERVICE_ACCOUNT_EMAIL = var.allow_unauthenticated ? "" : module.service_accounts.tasks_invoker_service_account_email

    # Public ingest auth (shared secret) for /api/ingest/upload
    INGEST_AUTH_MODE = lower(var.ingest_auth_mode)
    EDGE_AUTH_MODE = lower(var.edge_auth_mode)
    EDGE_ALLOWED_DATASETS = var.edge_allowed_datasets
    ENABLE_EDGE_SIGNED_URLS = tostring(var.enable_edge_signed_urls)

    # Processing hardening (reclaimer defaults)
    PROCESSING_TTL_SECONDS = "900"
    RECLAIM_MAX_PER_RUN    = "50"

    # Optional (tune for demo / cost)
    # Cloud Run has a 32MiB HTTP/1 request size limit; keep this <= 30 for direct upload.
    MAX_FILE_MB = "30"

    # Direct-to-GCS signed URLs (recommended only for a private service)
    ENABLE_SIGNED_URLS        = var.enable_signed_urls ? "true" : "false"
    SIGNED_URL_EXPIRES_SECONDS = tostring(var.signed_url_expires_seconds)
    REQUIRE_SIGNED_URL_SHA256  = "true"

    # Event-driven ingestion (GCS finalize -> Pub/Sub push -> Cloud Run)
    ENABLE_GCS_EVENT_INGESTION = var.enable_gcs_event_ingestion ? "true" : "false"
  }
}

module "core_services" {
  source     = "../modules/core_services"
  project_id = var.project_id
}

module "artifact_registry" {
  source        = "../modules/artifact_registry"
  project_id    = var.project_id
  location      = var.region
  repository_id = var.artifact_repo_name
  description   = "Images for EventPulse Cloud Run deploy"

  # Cost hygiene: keep demo repositories from growing forever.
  cleanup_policy_dry_run = true
  cleanup_policies = [
    {
      id     = "delete-untagged-old"
      action = "DELETE"
      condition = {
        tag_state  = "UNTAGGED"
        older_than = "1209600s" # 14d
      }
    },
    {
      id     = "keep-latest-tag"
      action = "KEEP"
      condition = {
        tag_state    = "TAGGED"
        tag_prefixes = ["latest"]
      }
    }
  ]
}

# Raw landing zone bucket (immutable-ish).
resource "google_storage_bucket" "raw" {
  name                        = local.raw_bucket_name
  project                     = var.project_id
  location                    = var.region
  uniform_bucket_level_access = true

  public_access_prevention = "enforced"

  versioning {
    enabled = false
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age = 30 # days
    }
  }

  labels = local.labels
}

# Cloud Tasks queue for async ingestion.
resource "google_cloud_tasks_queue" "ingest" {
  name     = local.tasks_queue_name
  project  = var.project_id
  location = var.region

  rate_limits {
    max_dispatches_per_second = 5
    max_concurrent_dispatches = 10
  }

  retry_config {
    max_attempts = 10
  }
}

module "service_accounts" {
  source     = "../modules/service_accounts"
  project_id = var.project_id

  runtime_account_id   = "sa-eventpulse-runtime-${var.env}"
  runtime_display_name = "EventPulse Runtime (${var.env})"

  runtime_roles = [
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/cloudtrace.agent",
    # Secret Manager env vars
    "roles/secretmanager.secretAccessor",
    # Enqueue Cloud Tasks
    "roles/cloudtasks.enqueuer",
  ]

  tasks_invoker_account_id   = "sa-eventpulse-tasks-invoker-${var.env}"
  tasks_invoker_display_name = "EventPulse Tasks Invoker (${var.env})"
}

# Bucket-level IAM (least privilege vs project-wide roles/storage.*)
resource "google_storage_bucket_iam_member" "raw_bucket_object_admin" {
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${module.service_accounts.runtime_service_account_email}"
}

module "secrets" {
  source     = "../modules/secret_manager"
  project_id = var.project_id

  # We create secret containers only (no secret versions).
  # Add the value out-of-band with:
  #   gcloud secrets versions add eventpulse-database-url --data-file=-
  secrets = {
    "eventpulse-database-url" = {
      labels = local.labels
    }
    "eventpulse-task-token" = {
      labels = local.labels
    }
    "eventpulse-ingest-token" = {
      labels = local.labels
    }
    "eventpulse-edge-enroll-token" = {
      labels = local.labels
    }
  }
}

module "network" {
  count  = var.enable_vpc_connector ? 1 : 0
  source = "../modules/network"

  project_id   = var.project_id
  network_name = "eventpulse-${var.env}-vpc"

  subnets = {
    "eventpulse-${var.env}-subnet" = {
      region = var.region
      cidr   = "10.20.0.0/24"
    }
  }

  create_serverless_connector         = true
  serverless_connector_name           = "eventpulse-${var.env}-connector"
  serverless_connector_region         = var.region
  serverless_connector_cidr           = "10.28.0.0/28"
  serverless_connector_min_throughput = 200
  serverless_connector_max_throughput = 300
}

module "cloud_run" {
  source = "../modules/cloud_run_service"

  project_id            = var.project_id
  region                = var.region
  service_name          = var.service_name
  image                 = var.image
  service_account_email = module.service_accounts.runtime_service_account_email

  cpu           = "1"
  memory        = "512Mi"
  min_instances = var.min_instances
  max_instances = var.max_instances

  concurrency = 10
  timeout     = "900s"

  allow_unauthenticated = var.allow_unauthenticated
  invoker_service_account_emails = compact([
    module.service_accounts.tasks_invoker_service_account_email
  ])
  env_vars              = local.env_vars
  labels                = local.labels

  # Secret Manager
  secret_env = merge(
    {
      DATABASE_URL = module.secrets.secret_names["eventpulse-database-url"]
    },
    var.allow_unauthenticated ? {
      TASK_TOKEN = module.secrets.secret_names["eventpulse-task-token"]
    } : {},
    lower(var.ingest_auth_mode) == "token" ? {
      INGEST_TOKEN = module.secrets.secret_names["eventpulse-ingest-token"]
    } : {},
    var.enable_edge_enroll ? {
      EDGE_ENROLL_TOKEN = module.secrets.secret_names["eventpulse-edge-enroll-token"]
    } : {}
  )

  vpc_connector_id = var.enable_vpc_connector ? module.network[0].serverless_connector_id : null
  vpc_egress       = var.vpc_egress
}

# -----------------------------
# IAM plumbing for OIDC + Signed URLs
# -----------------------------

data "google_project" "this" {
  project_id = var.project_id
}

locals {
  gcs_service_agent_email        = "service-${data.google_project.this.number}@gs-project-accounts.iam.gserviceaccount.com"
  pubsub_service_agent_email     = "service-${data.google_project.this.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
  cloudtasks_service_agent_email = "service-${data.google_project.this.number}@gcp-sa-cloudtasks.iam.gserviceaccount.com"
  cloudscheduler_service_agent_email = "service-${data.google_project.this.number}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"
}

# Allow Cloud Tasks service agent to mint OIDC tokens for the invoker SA.
resource "google_service_account_iam_member" "cloudtasks_token_creator" {
  count = var.allow_unauthenticated ? 0 : 1

  service_account_id = "projects/${var.project_id}/serviceAccounts/${module.service_accounts.tasks_invoker_service_account_email}"
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${local.cloudtasks_service_agent_email}"
}

# Allow Cloud Scheduler service agent to mint OIDC tokens for the invoker SA.
resource "google_service_account_iam_member" "cloudscheduler_token_creator" {
  count = var.enable_scheduler_jobs ? 1 : 0

  service_account_id = "projects/${var.project_id}/serviceAccounts/${module.service_accounts.tasks_invoker_service_account_email}"
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${local.cloudscheduler_service_agent_email}"
}

# Allow runtime SA to sign blobs (used for GCS signed URLs) without a private key.
#
# IMPORTANT:
# - Edge devices rely on device-authenticated signed URLs under /api/edge/uploads/*.
# - Human/admin flows can use /api/uploads/* (internal auth).
#
# Both flows require IAMCredentials signBlob (roles/iam.serviceAccountTokenCreator) on the
# runtime service account. We enable this binding when either lane is enabled.
resource "google_service_account_iam_member" "runtime_self_token_creator" {
  count = (var.enable_signed_urls || var.enable_edge_signed_urls) ? 1 : 0

  service_account_id = "projects/${var.project_id}/serviceAccounts/${module.service_accounts.runtime_service_account_email}"
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${module.service_accounts.runtime_service_account_email}"
}

# -----------------------------
# Event-driven ingestion (optional)
# -----------------------------

resource "google_pubsub_topic" "gcs_finalize" {
  count = var.enable_gcs_event_ingestion ? 1 : 0

  name   = "eventpulse-${var.env}-gcs-finalize"
  labels = local.labels
}

# Allow GCS to publish object finalize notifications into Pub/Sub.
resource "google_pubsub_topic_iam_member" "gcs_publisher" {
  count = var.enable_gcs_event_ingestion ? 1 : 0

  topic  = google_pubsub_topic.gcs_finalize[0].name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${local.gcs_service_agent_email}"
}

# Allow Pub/Sub service agent to mint OIDC tokens for the invoker SA.
resource "google_service_account_iam_member" "pubsub_token_creator" {
  count = var.enable_gcs_event_ingestion ? 1 : 0

  service_account_id = "projects/${var.project_id}/serviceAccounts/${module.service_accounts.tasks_invoker_service_account_email}"
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${local.pubsub_service_agent_email}"
}

resource "google_pubsub_subscription" "gcs_finalize_push" {
  count = var.enable_gcs_event_ingestion ? 1 : 0

  name  = "eventpulse-${var.env}-gcs-finalize-push"
  topic = google_pubsub_topic.gcs_finalize[0].name

  push_config {
    push_endpoint = "${module.cloud_run.service_uri}/internal/events/gcs_finalize"

    oidc_token {
      service_account_email = module.service_accounts.tasks_invoker_service_account_email
      audience              = "${module.cloud_run.service_uri}/internal/events/gcs_finalize"
    }
  }

  ack_deadline_seconds = 30

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  depends_on = [google_service_account_iam_member.pubsub_token_creator]
}

resource "google_storage_notification" "raw_finalize" {
  count = var.enable_gcs_event_ingestion ? 1 : 0

  bucket         = google_storage_bucket.raw.name
  topic          = google_pubsub_topic.gcs_finalize[0].id
  payload_format = "JSON_API_V1"

  event_types        = ["OBJECT_FINALIZE"]
  object_name_prefix = "${local.raw_bucket_prefix}/"

  depends_on = [google_pubsub_topic_iam_member.gcs_publisher]
}
