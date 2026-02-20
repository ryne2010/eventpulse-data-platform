#!/usr/bin/env bash
set -euo pipefail

# Pre-flight check for Terraform formatting.
#
# We treat Terraform as a first-class citizen, but not every contributor will
# have Terraform installed. Prefer a local terraform binary; fall back to Docker.

if command -v terraform >/dev/null 2>&1; then
  terraform fmt -check -recursive
  exit 0
fi

if command -v docker >/dev/null 2>&1; then
  echo "terraform not found; running terraform fmt -check via Docker" >&2
  docker run --rm -v "$(pwd):/workspace" -w /workspace hashicorp/terraform:1.9.8 fmt -check -recursive
  exit 0
fi

echo "terraform not found and docker not available; skipping terraform fmt check" >&2
exit 0
