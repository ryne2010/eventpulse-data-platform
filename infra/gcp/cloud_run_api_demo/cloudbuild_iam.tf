data "google_project" "this" {
  project_id = var.project_id
}

# Cloud Build pushes images to Artifact Registry.
# Teaching point: grant this once as code so builds are repeatable and keyless.
resource "google_project_iam_member" "cloudbuild_artifact_registry_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${data.google_project.this.number}@cloudbuild.gserviceaccount.com"

  depends_on = [module.core_services]
}
