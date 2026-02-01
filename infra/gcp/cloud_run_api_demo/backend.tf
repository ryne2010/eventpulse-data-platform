// Terraform remote state (GCS)
//
// Backend config is passed at init time by the repo root Makefile:
//   terraform init -backend-config="bucket=..." -backend-config="prefix=..."
terraform {
  backend "gcs" {}
}
