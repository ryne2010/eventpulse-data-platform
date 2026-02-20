#!/usr/bin/env bash
set -euo pipefail

# Pre-commit hook: run `terraform fmt -recursive`.
#
# We prefer a local terraform binary when available. If not installed,
# fall back to Docker (since this repo already relies on Docker for local dev).

if command -v terraform >/dev/null 2>&1; then
  terraform fmt -recursive
  exit 0
fi

if command -v docker >/dev/null 2>&1; then
  echo "terraform not found; running terraform fmt via Docker" >&2
  docker run --rm -v "$(pwd):/workspace" -w /workspace hashicorp/terraform:1.9.8 fmt -recursive
  exit 0
fi

echo "terraform not found and docker not available; skipping terraform fmt" >&2
exit 0
