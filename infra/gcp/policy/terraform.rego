package terraform

# Conftest policy gate for Terraform (parsed via --parser hcl2)
#
# This is intentionally small and demonstrative. In real landing zones you would
# expand this with org-policy parity checks, naming rules, network controls, etc.

deny contains msg if {
  bucket := input.resource.google_storage_bucket[_][_]
  not bucket.uniform_bucket_level_access
  msg := "google_storage_bucket must enable uniform_bucket_level_access"
}

deny contains msg if {
  bucket := input.resource.google_storage_bucket[_][_]
  bucket.public_access_prevention != "enforced"
  msg := "google_storage_bucket must set public_access_prevention = "enforced""
}

deny contains msg if {
  sa := input.resource.google_service_account[_][_]
  sa.disabled == true
  msg := "google_service_account should not be created disabled"
}

# Avoid granting overly-broad privileges in examples.
deny contains msg if {
  b := input.resource.google_project_iam_binding[_][_]
  b.role == "roles/owner"
  msg := "Do not grant roles/owner via google_project_iam_binding"
}
