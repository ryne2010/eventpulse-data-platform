module "core_services" {
  source     = "../modules/core_services"
  project_id = var.project_id

  # Minimum set for WIF + Terraform workflows.
  services = [
    "serviceusage.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "storage.googleapis.com",
  ]
}

resource "google_service_account" "ci" {
  account_id   = var.ci_service_account_id
  display_name = "EventPulse CI (Terraform)"
}

resource "google_project_iam_member" "ci_roles" {
  for_each = toset(var.ci_project_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.ci.email}"
}

resource "google_storage_bucket_iam_member" "tfstate_rw" {
  bucket = var.tfstate_bucket_name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.ci.email}"
}

resource "google_storage_bucket_iam_member" "config_reader" {
  bucket = var.config_bucket_name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.ci.email}"
}

resource "google_storage_bucket_iam_member" "config_writer" {
  count  = var.enable_config_bucket_write ? 1 : 0
  bucket = var.config_bucket_name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.ci.email}"
}

module "github_oidc" {
  source = "../modules/github_oidc"

  project_id = var.project_id

  github_repository = var.github_repository
  allowed_branches  = var.allowed_branches

  service_account_email = google_service_account.ci.email
}
