resource "google_service_account" "runtime" {
  account_id   = var.runtime_account_id
  display_name = var.runtime_display_name
  project      = var.project_id
}

resource "google_project_iam_member" "runtime_roles" {
  for_each = toset(var.runtime_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.runtime.email}"
}


resource "google_service_account" "tasks_invoker" {
  count = var.create_tasks_invoker_account ? 1 : 0

  account_id   = var.tasks_invoker_account_id
  display_name = var.tasks_invoker_display_name
  project      = var.project_id
}


# Allow the runtime workload (which enqueues Cloud Tasks) to impersonate the
# tasks invoker service account for OIDC task dispatch.
resource "google_service_account_iam_member" "runtime_act_as_tasks_invoker" {
  count = var.create_tasks_invoker_account ? 1 : 0

  service_account_id = google_service_account.tasks_invoker[0].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_service_account" "ci" {
  count = var.create_ci_account ? 1 : 0

  account_id   = var.ci_account_id
  display_name = var.ci_display_name
  project      = var.project_id
}

resource "google_project_iam_member" "ci_roles" {
  for_each = var.create_ci_account ? toset(var.ci_roles) : []

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.ci[0].email}"
}
