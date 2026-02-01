# EventPulse Data Platform — team-ready workflow (Makefile)
#
# This repo has two "lanes":
#   1) Local-first stack (Docker Compose) for development and demos
#   2) Optional GCP deployment (Cloud Run) to demonstrate staff-level cloud delivery
#
# Staff-level goals:
# - No manual `export ...` blocks (defaults come from `gcloud config`)
# - Reproducible: every value can be overridden per-command
# - Remote Terraform state by default (GCS)
# - Plan/apply separation
# - Clear, discoverable commands (help + commented targets)
#
# Quickstart (local):
#   make up
#
# Quickstart (GCP):
#   gcloud auth login
#   gcloud auth application-default login
#   gcloud config set project YOUR_PROJECT_ID
#   gcloud config set run/region us-central1
#   make deploy-gcp

SHELL := /bin/bash

# -----------------------------
# Local stack (Docker Compose)
# -----------------------------
COMPOSE ?= docker compose

# -----------------------------
# GCP deployment defaults
# -----------------------------
PROJECT_ID ?= $(shell gcloud config get-value project 2>/dev/null)
REGION     ?= $(shell gcloud config get-value run/region 2>/dev/null)
REGION     ?= us-central1

ENV ?= dev

SERVICE_NAME ?= eventpulse-$(ENV)
AR_REPO      ?= eventpulse
IMAGE_NAME   ?= eventpulse-api
TAG          ?= latest

TF_DIR ?= infra/gcp/cloud_run_api_demo

TF_STATE_BUCKET ?= $(PROJECT_ID)-tfstate
TF_STATE_PREFIX ?= eventpulse/$(ENV)

# Workspace IAM starter pack (optional; Google Groups)
WORKSPACE_DOMAIN ?=
GROUP_PREFIX ?= eventpulse

# Observability as code
ENABLE_OBSERVABILITY ?= true

IMAGE := $(REGION)-docker.pkg.dev/$(PROJECT_ID)/$(AR_REPO)/$(IMAGE_NAME):$(TAG)

# -----------------------------
# Helpers
# -----------------------------

define require
	@command -v $(1) >/dev/null 2>&1 || (echo "Missing dependency: $(1)"; exit 1)
endef

.PHONY: help init auth \
	doctor doctor-gcp \
	up down reset logs \
	gen ingest list sample \
	bootstrap-state-gcp tf-init-gcp infra-gcp plan-gcp apply-gcp build-gcp deploy-gcp url-gcp verify-gcp logs-gcp destroy-gcp \
	db-secret lock

help:
	@echo "Local targets:"
	@echo "  init              One-time setup for GCP deploys (persist gcloud project/region)"
	@echo "  auth              Authenticate gcloud user + ADC (interactive)"
	@echo "  up               Start local stack (Postgres + API + worker + UI)"
	@echo "  down             Stop local stack"
	@echo "  reset            Remove volumes + reset local data directories"
	@echo "  logs             Tail local logs"
	@echo "  gen              Generate sample incoming files"
	@echo "  ingest           Trigger an ingestion via the API"
	@echo "  list             List recent ingestions"
	@echo "  sample           Fetch curated sample rows"
	@echo ""
	@echo "GCP targets (optional):"
	@echo "  deploy-gcp       Team-ready deploy to Cloud Run (remote state + Cloud Build)"
	@echo "  plan-gcp         Terraform plan"
	@echo "  apply-gcp        Terraform apply"
	@echo "  url-gcp          Print service URL"
	@echo "  verify-gcp       Hit /health"
	@echo "  logs-gcp         Read Cloud Run logs"
	@echo "  destroy-gcp      Terraform destroy (keeps tfstate bucket)"
	@echo "  db-secret        Add a DATABASE_URL secret version (reads from stdin)"
	@echo ""
	@echo "Reproducibility:"
	@echo "  lock             Generate uv.lock + pnpm-lock.yaml locally"





# -----------------------------
# Init (team onboarding)
# -----------------------------
# `make init` persists `PROJECT_ID` and `REGION` into your active gcloud configuration.
# This avoids copy/pasting `export ...` blocks and keeps team workflows consistent.
#
# Usage (recommended for teams):
#   make init GCLOUD_CONFIG=personal-portfolio PROJECT_ID=my-proj REGION=us-central1
#
# Usage (current gcloud config):
#   make init PROJECT_ID=my-proj REGION=us-central1
#
# Notes:
# - This target does NOT create projects or enable billing.
# - This target does NOT run Terraform; it only configures gcloud defaults and prints next steps.
# - If you switch gcloud configs in this command, re-run your next make command in a fresh invocation.
init:
	@command -v gcloud >/dev/null 2>&1 || (echo "Missing dependency: gcloud (https://cloud.google.com/sdk/docs/install)"; exit 1)
	@set -e; \
	  echo "== Init: configure gcloud defaults =="; \
	  if [ -n "$(GCLOUD_CONFIG)" ]; then \
	    if gcloud config configurations describe "$(GCLOUD_CONFIG)" >/dev/null 2>&1; then :; else \
	      echo "Creating gcloud configuration: $(GCLOUD_CONFIG)"; \
	      gcloud config configurations create "$(GCLOUD_CONFIG)" >/dev/null; \
	    fi; \
	    echo "Activating gcloud configuration: $(GCLOUD_CONFIG)"; \
	    gcloud config configurations activate "$(GCLOUD_CONFIG)" >/dev/null; \
	  fi; \
	  proj="$(PROJECT_ID)"; \
	  if [ -z "$$proj" ]; then proj=$$(gcloud config get-value project 2>/dev/null || true); fi; \
	  region="$(REGION)"; \
	  if [ -z "$$proj" ]; then \
	    echo "ERROR: PROJECT_ID is not set."; \
	    echo "Fix: run 'make init PROJECT_ID=<your-project-id> REGION=<region>'"; \
	    exit 1; \
	  fi; \
	  echo "Setting gcloud defaults..."; \
	  gcloud config set project "$$proj" >/dev/null; \
	  gcloud config set run/region "$$region" >/dev/null; \
	  active=$$(gcloud config configurations list --filter=is_active:true --format='value(name)' 2>/dev/null | head -n1); \
	  echo ""; \
	  echo "Configured:"; \
	  echo "  project: $$proj"; \
	  echo "  region:  $$region"; \
	  echo "  gcloud config: $${active:-default}"; \
	  echo ""; \
	  acct=$$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -n1 || true); \
	  if [ -z "$$acct" ]; then \
	    echo "Auth status: not logged in"; \
	    echo "Next: make auth"; \
	  else \
	    echo "Auth status: $$acct"; \
	  fi; \
	  echo ""; \
	  echo "Next steps (GCP deploy lane):"; \
	  echo "  make doctor-gcp"; \
	  echo "  make deploy-gcp"; \
	  echo ""; \
	  echo "Tip: if you changed gcloud configs, run the next make command in a fresh invocation."

# Interactive auth helper (explicit on purpose).
# This will open browser windows for OAuth flows.
auth:
	@command -v gcloud >/dev/null 2>&1 || (echo "Missing dependency: gcloud"; exit 1)
	@echo "This will open a browser window for gcloud login + ADC."
	gcloud auth login
	gcloud auth application-default login

# Local doctor: only checks local dev prerequisites.
# -----------------------------
# Doctor (prerequisite checks)
# -----------------------------
# Local lane doctor: verifies tools needed to run the local Docker Compose stack and UI dev.
doctor:
	@set -e; \
	fail=0; \
	echo "== Doctor: EventPulse (local) =="; \
	echo ""; \
	echo "Required for local dev (Docker Compose lane):"; \
	if command -v docker >/dev/null 2>&1; then \
	  echo "  ✓ docker: $$(docker --version)"; \
	  if docker info >/dev/null 2>&1; then \
	    echo "  ✓ docker daemon: running"; \
	  else \
	    echo "  ✗ docker daemon not running (start Docker Desktop)"; \
	    fail=1; \
	  fi; \
	  if docker compose version >/dev/null 2>&1; then \
	    echo "  ✓ docker compose: $$(docker compose version | head -n1)"; \
	  else \
	    echo "  ✗ docker compose not available (install Docker Desktop / Compose v2)"; \
	    fail=1; \
	  fi; \
	else \
	  echo "  ✗ docker not found (install Docker Desktop)"; \
	  fail=1; \
	fi; \
	if command -v uv >/dev/null 2>&1; then \
	  echo "  ✓ uv: $$(uv --version)"; \
	else \
	  echo "  ✗ uv not found. Install: https://docs.astral.sh/uv/"; \
	  fail=1; \
	fi; \
	if command -v node >/dev/null 2>&1; then \
	  echo "  ✓ node: $$(node -v)"; \
	else \
	  echo "  ✗ node not found. Install: https://nodejs.org/"; \
	  fail=1; \
	fi; \
	if command -v pnpm >/dev/null 2>&1; then \
	  echo "  ✓ pnpm: $$(pnpm -v)"; \
	else \
	  echo "  ✗ pnpm not found. Enable corepack: corepack enable"; \
	  fail=1; \
	fi; \
	if command -v jq >/dev/null 2>&1; then \
	  echo "  ✓ jq: $$(jq --version)"; \
	else \
	  echo "  ⚠ jq not found (optional; makes curl output pretty). Install: brew install jq"; \
	fi; \
	echo ""; \
	if [ "$$fail" -ne 0 ]; then \
	  echo "Doctor failed: fix missing items above, then re-run."; \
	  exit $$fail; \
	fi; \
	echo "Doctor OK."
# Cloud lane doctor: verifies tools and config required to deploy the API to Cloud Run using Terraform + Cloud Build.
doctor-gcp:
	@set -e; \
	fail=0; \
	echo "== Doctor: EventPulse (GCP deploy) =="; \
	echo ""; \
	echo "Resolved config (override with VAR=...):"; \
	echo "  PROJECT_ID=$(PROJECT_ID)"; \
	echo "  REGION=$(REGION)"; \
	echo "  ENV=$(ENV)"; \
	echo "  SERVICE_NAME=$(SERVICE_NAME)"; \
	echo "  IMAGE=$(IMAGE)"; \
	echo "  TF_STATE_BUCKET=$(TF_STATE_BUCKET)"; \
	echo "  TF_STATE_PREFIX=$(TF_STATE_PREFIX)"; \
		echo "  WORKSPACE_DOMAIN=$(WORKSPACE_DOMAIN)"; \
		echo "  GROUP_PREFIX=$(GROUP_PREFIX)"; \
		echo "  ENABLE_OBSERVABILITY=$(ENABLE_OBSERVABILITY)"; \
	echo ""; \
	echo "Required for Cloud deploy:"; \
	if command -v gcloud >/dev/null 2>&1; then \
	  echo "  ✓ gcloud: $$(gcloud --version 2>/dev/null | head -n1)"; \
	else \
	  echo "  ✗ gcloud not found. Install: https://cloud.google.com/sdk/docs/install"; \
	  fail=1; \
	fi; \
	if command -v terraform >/dev/null 2>&1; then \
	  echo "  ✓ terraform: $$(terraform version | head -n1)"; \
	else \
	  echo "  ✗ terraform not found. Install: https://developer.hashicorp.com/terraform/downloads"; \
	  fail=1; \
	fi; \
	if [ -z "$(PROJECT_ID)" ]; then \
	  echo "  ✗ gcloud project not set. Run: gcloud config set project <PROJECT_ID>"; \
	  fail=1; \
	else \
	  echo "  ✓ gcloud project set"; \
	fi; \
	if [ -z "$(REGION)" ]; then \
	  echo "  ⚠ gcloud run/region not set. Recommended: gcloud config set run/region us-central1"; \
	else \
	  echo "  ✓ gcloud run/region: $(REGION)"; \
	fi; \
	if command -v gcloud >/dev/null 2>&1; then \
	  acct=$$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -n1); \
	  if [ -n "$$acct" ]; then \
	    echo "  ✓ gcloud user auth: $$acct"; \
	  else \
	    echo "  ⚠ gcloud user not authenticated. Run: gcloud auth login"; \
	  fi; \
	  if gcloud auth application-default print-access-token >/dev/null 2>&1; then \
	    echo "  ✓ ADC credentials: OK"; \
	  else \
	    echo "  ⚠ ADC not configured. Run: gcloud auth application-default login"; \
	  fi; \
	fi; \
	echo ""; \
	if [ "$$fail" -ne 0 ]; then \
	  echo "Doctor failed: fix missing items above, then re-run."; \
	  exit $$fail; \
	fi; \
	echo "Doctor OK."
up: doctor
	cp -n .env.example .env || true
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

reset:
	$(COMPOSE) down -v
	rm -rf data/pg data/raw data/archive
	mkdir -p data/pg data/raw data/archive data/incoming data/contracts

logs:
	$(COMPOSE) logs -f --tail=200

# Generate sample "incoming" files using uv-managed deps.
gen: doctor
	uv run python scripts/generate_sample_data.py --out ./data/incoming --rows 500

# Trigger an ingestion run against the local API.
ingest:
	curl -s -X POST "http://localhost:8081/api/ingest/from_path" \
	  -H "Content-Type: application/json" \
	  -d '{"dataset":"parcels","relative_path":"parcels_baseline.xlsx","source":"make"}' | jq

list:
	curl -s "http://localhost:8081/api/ingestions?limit=20" | jq

sample:
	curl -s "http://localhost:8081/api/datasets/parcels/curated/sample?limit=10" | jq

# -----------------------------
# GCP deploy lane (Cloud Run)
# -----------------------------

bootstrap-state-gcp: doctor-gcp
	@echo "Ensuring tfstate bucket exists: gs://$(TF_STATE_BUCKET)"
	@if gcloud storage buckets describe "gs://$(TF_STATE_BUCKET)" >/dev/null 2>&1; then \
		echo "Bucket already exists."; \
	else \
		echo "Creating bucket..."; \
		gcloud storage buckets create "gs://$(TF_STATE_BUCKET)" --location="$(REGION)" --uniform-bucket-level-access --public-access-prevention=enforced; \
		echo "Enabling versioning..."; \
		gcloud storage buckets update "gs://$(TF_STATE_BUCKET)" --versioning; \
	fi

tf-init-gcp: bootstrap-state-gcp
	@echo "Terraform init (remote state)"
	terraform -chdir=$(TF_DIR) init -reconfigure \
		-backend-config="bucket=$(TF_STATE_BUCKET)" \
		-backend-config="prefix=$(TF_STATE_PREFIX)"

# Apply prerequisite infra before building/pushing images.
infra-gcp: tf-init-gcp
	terraform -chdir=$(TF_DIR) apply -auto-approve \
		-var "project_id=$(PROJECT_ID)" \
		-var "region=$(REGION)" \
		-var "env=$(ENV)" \
		-var "workspace_domain=$(WORKSPACE_DOMAIN)" \
		-var "group_prefix=$(GROUP_PREFIX)" \
		-var "enable_observability=$(ENABLE_OBSERVABILITY)" \
		-var "service_name=$(SERVICE_NAME)" \
		-var "artifact_repo_name=$(AR_REPO)" \
		-var "image=$(IMAGE)" \
		-target=module.core_services \
		-target=module.artifact_registry \
		-target=module.service_accounts \
		-target=module.secrets

plan-gcp: tf-init-gcp
	terraform -chdir=$(TF_DIR) plan \
		-var "project_id=$(PROJECT_ID)" \
		-var "region=$(REGION)" \
		-var "env=$(ENV)" \
		-var "workspace_domain=$(WORKSPACE_DOMAIN)" \
		-var "group_prefix=$(GROUP_PREFIX)" \
		-var "enable_observability=$(ENABLE_OBSERVABILITY)" \
		-var "service_name=$(SERVICE_NAME)" \
		-var "artifact_repo_name=$(AR_REPO)" \
		-var "image=$(IMAGE)"

apply-gcp: tf-init-gcp
	terraform -chdir=$(TF_DIR) apply -auto-approve \
		-var "project_id=$(PROJECT_ID)" \
		-var "region=$(REGION)" \
		-var "env=$(ENV)" \
		-var "workspace_domain=$(WORKSPACE_DOMAIN)" \
		-var "group_prefix=$(GROUP_PREFIX)" \
		-var "enable_observability=$(ENABLE_OBSERVABILITY)" \
		-var "service_name=$(SERVICE_NAME)" \
		-var "artifact_repo_name=$(AR_REPO)" \
		-var "image=$(IMAGE)"

# Ensure Cloud Build can push to Artifact Registry.
grant-cloudbuild-gcp: doctor-gcp
	@PROJECT_NUMBER=$$(gcloud projects describe "$(PROJECT_ID)" --format='value(projectNumber)'); \
	echo "Granting Cloud Build writer on Artifact Registry (project $$PROJECT_NUMBER)"; \
	gcloud projects add-iam-policy-binding "$(PROJECT_ID)" \
	  --member="serviceAccount:$${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
	  --role="roles/artifactregistry.writer" >/dev/null

# Build+push using Cloud Build.
# This uses the repo root Dockerfile (Cloud Run deploy lane).
build-gcp: doctor-gcp infra-gcp grant-cloudbuild-gcp
	@echo "Building + pushing via Cloud Build: $(IMAGE)"
	gcloud builds submit --tag "$(IMAGE)" .

deploy-gcp: build-gcp apply-gcp verify-gcp

url-gcp: tf-init-gcp
	@terraform -chdir=$(TF_DIR) output -raw service_url

verify-gcp: tf-init-gcp
	@URL=$$(terraform -chdir=$(TF_DIR) output -raw service_url); \
	echo "Service URL: $$URL"; \
	curl -fsS "$$URL/health" >/dev/null && echo "OK: /health" || (echo "Health check failed"; exit 1)

logs-gcp: doctor-gcp
	gcloud run services logs read "$(SERVICE_NAME)" --region "$(REGION)" --limit 100

destroy-gcp: tf-init-gcp
	terraform -chdir=$(TF_DIR) destroy -auto-approve \
		-var "project_id=$(PROJECT_ID)" \
		-var "region=$(REGION)" \
		-var "env=$(ENV)" \
		-var "workspace_domain=$(WORKSPACE_DOMAIN)" \
		-var "group_prefix=$(GROUP_PREFIX)" \
		-var "enable_observability=$(ENABLE_OBSERVABILITY)" \
		-var "service_name=$(SERVICE_NAME)" \
		-var "artifact_repo_name=$(AR_REPO)" \
		-var "image=$(IMAGE)"

# Add a DATABASE_URL secret version (reads from stdin so you don't put secrets in shell history).
# Usage:
#   make db-secret
#   (paste a DATABASE_URL and press Ctrl-D)
db-secret: doctor-gcp
	@echo "Paste DATABASE_URL then press Ctrl-D (example: postgresql://user:pass@host:5432/eventpulse)";
	@gcloud secrets versions add eventpulse-database-url --data-file=-

# Generate lockfiles locally for team reproducibility.
lock: doctor
	@echo "Generating uv.lock (Python)"
	uv lock
	@echo "Generating pnpm-lock.yaml (web)"
	cd web && pnpm install
	@echo "Done. Commit uv.lock and pnpm-lock.yaml for team reproducibility."


# -----------------------------------------------------------------------------
# Staff-level IaC hygiene (lint / security / policy)
#
# These targets are optional locally (CI always runs them). They are convenient
# for "pre-flight" checks before a PR.
#
# We try to use locally-installed tools if present; otherwise we fall back to
# running the tool in a container (requires Docker).
# -----------------------------------------------------------------------------

POLICY_DIR := infra/gcp/policy

.PHONY: tf-fmt tf-validate tf-lint tf-sec tf-policy tf-check

tf-fmt: ## Terraform fmt check (no changes)
	@terraform -chdir=$(TF_DIR) fmt -check -recursive

tf-validate: ## Terraform validate (no remote backend required)
	@terraform -chdir=$(TF_DIR) init -backend=false -upgrade >/dev/null
	@terraform -chdir=$(TF_DIR) validate

tf-lint: ## tflint (falls back to docker)
	@if command -v tflint >/dev/null 2>&1; then \
	  echo "Running tflint (local)"; \
	  (cd $(TF_DIR) && tflint --init && tflint); \
	else \
	  echo "tflint not found; running via Docker"; \
	  docker run --rm -v "$$(pwd)/$(TF_DIR):/workspace" -w /workspace ghcr.io/terraform-linters/tflint:latest --init && \
	  docker run --rm -v "$$(pwd)/$(TF_DIR):/workspace" -w /workspace ghcr.io/terraform-linters/tflint:latest; \
	fi

tf-sec: ## tfsec (falls back to docker)
	@if command -v tfsec >/dev/null 2>&1; then \
	  echo "Running tfsec (local)"; \
	  tfsec $(TF_DIR); \
	else \
	  echo "tfsec not found; running via Docker"; \
	  docker run --rm -v "$$(pwd):/src" aquasec/tfsec:latest /src/$(TF_DIR); \
	fi

tf-policy: ## OPA/Conftest policy gate for Terraform (falls back to docker)
	@if command -v conftest >/dev/null 2>&1; then \
	  echo "Running conftest (local)"; \
	  conftest test --parser hcl2 --policy $(POLICY_DIR) $(TF_DIR); \
	else \
	  echo "conftest not found; running via Docker"; \
	  docker run --rm -v "$$(pwd):/project" -w /project openpolicyagent/conftest:latest test --parser hcl2 --policy $(POLICY_DIR) $(TF_DIR); \
	fi

tf-check: tf-fmt tf-validate tf-lint tf-sec tf-policy ## Run all Terraform hygiene checks

