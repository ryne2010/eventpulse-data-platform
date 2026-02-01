locals {
  labels = {
    app = "eventpulse-data-platform"
    env = var.env
  }

  # Minimal runtime configuration for the API.
  # NOTE: DATABASE_URL is provided via Secret Manager (see `module.secrets`).
  env_vars = {
    APP_ENV   = var.env
    LOG_LEVEL = "INFO"
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

module "service_accounts" {
  source     = "../modules/service_accounts"
  project_id = var.project_id

  runtime_account_id   = "sa-eventpulse-runtime-${var.env}"
  runtime_display_name = "EventPulse Runtime (${var.env})"

  runtime_roles = [
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/cloudtrace.agent",
    # For Secret Manager env vars
    "roles/secretmanager.secretAccessor",
  ]
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

  allow_unauthenticated = var.allow_unauthenticated
  env_vars              = local.env_vars
  labels                = local.labels

  # Secret Manager: DATABASE_URL comes from the secret's resource name.
  secret_env = {
    DATABASE_URL = module.secrets.secret_names["eventpulse-database-url"]
  }

  vpc_connector_id = var.enable_vpc_connector ? module.network[0].serverless_connector_id : null
  vpc_egress       = var.vpc_egress
}
