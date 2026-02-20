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

# Load optional local env vars (TASK_TOKEN, DATABASE_URL, etc.)
# Safe if .env does not exist.
-include .env

# -----------------------------
# Local stack (Docker Compose)
# -----------------------------
COMPOSE ?= docker compose

# Local API base URL
LOCAL_URL ?= http://localhost:8081

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

# Edge agent image (for Raspberry Pi / field devices)
EDGE_IMAGE_NAME  ?= eventpulse-edge-agent
EDGE_IMAGE_TAG   ?= $(TAG)

EDGE_IMAGE_LOCAL := $(EDGE_IMAGE_NAME):$(EDGE_IMAGE_TAG)
EDGE_IMAGE_REMOTE := $(REGION)-docker.pkg.dev/$(PROJECT_ID)/$(AR_REPO)/$(EDGE_IMAGE_NAME):$(EDGE_IMAGE_TAG)

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
	up down reset clean clean-py clean-web logs watch \
	gen ingest list sample \
	bootstrap-state-gcp tf-init-gcp infra-gcp plan-gcp apply-gcp build-gcp deploy-gcp url-gcp verify-gcp logs-gcp destroy-gcp \
	db-secret edge-enroll-token-secret edge-image-build edge-image-export edge-image-load edge-image-push lock

help:
	@echo "Local targets:"
	@echo "  init              One-time setup for GCP deploys (persist gcloud project/region)"
	@echo "  auth              Authenticate gcloud user + ADC (interactive)"
	@echo "  up               Start local stack (Postgres + API + worker + UI)"
	@echo "  down             Stop local stack"
	@echo "  reset            Remove volumes + reset local data directories"
	@echo "  clean            Remove local build artifacts (.venv, caches, node_modules, dist)"
	@echo "  logs             Tail local logs"
	@echo "  watch            Start the watcher (monitors data/incoming)"
	@echo "  gen              Generate sample incoming files"
	@echo "  ingest           Trigger an ingestion via the API"
	@echo "  list             List recent ingestions"
	@echo "  sample           Fetch curated sample rows"
	@echo ""
	@echo "GCP targets (optional):"
	@echo "  bootstrap-state-gcp  Create/verify Terraform state bucket"
	@echo "  infra-gcp            End-to-end infra (plan+apply+postchecks)"
	@echo "  deploy-gcp       Team-ready deploy to Cloud Run (remote state + Cloud Build)"
	@echo "  plan-gcp         Terraform plan"
	@echo "  apply-gcp        Terraform apply"
	@echo "  url-gcp          Print service URL"
	@echo "  verify-gcp       Hit /health"
	@echo "  logs-gcp         Read Cloud Run logs"
	@echo "  destroy-gcp      Terraform destroy (keeps tfstate bucket)"
	@echo "  db-secret           Add a DATABASE_URL secret version (reads from stdin)"
	@echo "  task-token-secret   Add a TASK_TOKEN secret version (reads from stdin)"
	@echo "  ingest-token-secret Add an INGEST_TOKEN secret version (reads from stdin)"
	@echo "  edge-enroll-token-secret  Add an EDGE_ENROLL_TOKEN secret version (optional; enables /api/edge/enroll)"
	@echo ""
	@echo "Field ops (edge agent):"
	@echo "  edge-image-build   Build the Raspberry Pi edge-agent container image"
	@echo "  edge-image-export  Export the edge-agent image to a tar.gz (scp to device + docker load)"
	@echo "  edge-image-load    Load an exported edge-agent image tar.gz (run on the Pi)"
	@echo "  edge-image-push    Push the edge-agent image to Artifact Registry (optional)"
	@echo ""
	@echo "Reproducibility:"
	@echo "  lock             Generate uv.lock + pnpm-lock.yaml locally"
	@echo ""
	@echo "Repo quality gates (harness):"
	@echo "  fmt              Format (ruff + terraform fmt via pre-commit)"
	@echo "  lint             Lint (ruff + terraform fmt check via pre-commit)"
	@echo "  typecheck        Typecheck (pyright + mypy where configured)"
	@echo "  test             Run tests (pytest)"
	@echo "  harness-doctor    Explain what the harness will run"





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
	echo "Required for Docker Compose lane:"; \
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
	echo ""; \
	echo "Optional (hybrid dev / tooling):"; \
	if command -v uv >/dev/null 2>&1; then \
	  echo "  ✓ uv: $$(uv --version)"; \
	else \
	  echo "  ⚠ uv not found (optional; needed for running API locally)"; \
	fi; \
	if command -v node >/dev/null 2>&1; then \
	  echo "  ✓ node: $$(node -v)"; \
	else \
	  echo "  ⚠ node not found (optional; needed for running UI locally)"; \
	fi; \
	if command -v pnpm >/dev/null 2>&1; then \
	  echo "  ✓ pnpm: $$(command -v pnpm)"; \
	else \
	  echo "  ⚠ pnpm not found (optional; enable corepack: corepack enable)"; \
	fi; \
	if command -v jq >/dev/null 2>&1; then \
	  echo "  ✓ jq: $$(jq --version)"; \
	else \
	  echo "  ⚠ jq not found (optional; makes curl output pretty). Install: brew install jq"; \
	fi; \
	echo ""; \
	if [ "$$fail" -ne 0 ]; then \
	  echo "Doctor failed: fix missing required items above, then re-run."; \
	  exit $$fail; \
	fi; \
	echo "Doctor OK."
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
init-data: ## Ensure local data directories exist (and are writable for non-root containers)
	# NOTE: We intentionally do NOT chmod data/pg. Postgres is strict about data directory permissions.
	mkdir -p data/pg data/raw data/archive data/incoming data/contracts
	chmod -R a+rwX data/raw data/archive data/incoming data/contracts

up: doctor init-data
	cp -n .env.example .env || true
	# Work around occasional Docker/Compose stale container networking issues by
	# force-recreating core dependencies first (preserves bind-mounted data).
	$(COMPOSE) up -d --force-recreate postgres redis
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

reset:
	$(COMPOSE) down -v
	rm -rf data/pg data/raw data/archive data/incoming
	mkdir -p data/pg data/raw data/archive data/incoming data/contracts
	chmod -R a+rwX data/raw data/archive data/incoming data/contracts

clean: clean-py clean-web ## Remove local build artifacts/caches
	@echo "Cleaned local artifacts."

clean-py: ## Remove Python venv + caches
	rm -rf .venv .mypy_cache .pytest_cache .ruff_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} + || true
	find . -name '*.pyc' -delete || true
	rm -rf .coverage htmlcov coverage.xml

clean-web: ## Remove Node artifacts
	rm -rf node_modules web/node_modules web/dist

logs:
	$(COMPOSE) logs -f --tail=200

watch: ## Start watcher service (profile watch)
	$(COMPOSE) --profile watch up -d --build watcher

edge: ## Run the edge-agent profile (simulated RPi telemetry)
	$(COMPOSE) --profile edge up --build edge-agent

edge-up: ## Start the edge-agent profile in the background
	$(COMPOSE) --profile edge up -d --build edge-agent

edge-logs: ## Tail edge-agent logs
	$(COMPOSE) logs -f --tail=200 edge-agent


# Generate contract-compliant sample files under data/samples (uses uv-managed deps).
gen: doctor
	uv run python scripts/generate_sample_data.py --out-dir data/samples --rows 120

# Trigger an ingestion run against the local API.
ingest: ## Upload a sample file for ingestion (no watcher required)
	@echo "Uploading sample: data/samples/parcels_baseline.xlsx"
	@curl -sS -X POST "$(LOCAL_URL)/api/ingest/upload?dataset=parcels&filename=parcels_baseline.xlsx&source=make" \
		-H "Content-Type: application/octet-stream" \
		--data-binary @data/samples/parcels_baseline.xlsx | jq .

ingest-edge: ## Upload edge telemetry sample (CSV)
	@echo "Uploading sample: data/samples/edge_telemetry_sample.csv"
	@curl -sS -X POST "$(LOCAL_URL)/api/ingest/upload?dataset=edge_telemetry&filename=edge_telemetry_sample.csv&source=make" \
		-H "Content-Type: application/octet-stream" \
		--data-binary @data/samples/edge_telemetry_sample.csv | jq .


list:
	curl -s "$(LOCAL_URL)/api/ingestions?limit=20" | jq

sample:
	curl -s "$(LOCAL_URL)/api/datasets/parcels/curated/sample?limit=10" | jq

reclaim-stuck: ## Reclaim stuck PROCESSING ingestions and re-enqueue them (dev/debug)
	$(UV_RUN) python scripts/reclaim_stuck.py

# Ops/maintenance helpers (internal endpoints)
# These require TASK_TOKEN when TASK_AUTH_MODE=token.

db-stats: ## Fetch lightweight DB size stats (internal endpoint)
	@curl -sS "$(LOCAL_URL)/internal/admin/db_stats" \
		-H "X-Task-Token: $(TASK_TOKEN)" | jq .

prune-dry: ## Preview retention pruning (dry run)
	@curl -sS -X POST "$(LOCAL_URL)/internal/admin/prune" \
		-H "X-Task-Token: $(TASK_TOKEN)" \
		-H 'Content-Type: application/json' \
		-d '{"dry_run": true, "audit_older_than_days": 30, "audit_limit": 50000, "ingestions_older_than_days": 90, "ingestions_limit": 5000}' | jq .

prune: ## Execute retention pruning (requires confirm=PRUNE)
	@curl -sS -X POST "$(LOCAL_URL)/internal/admin/prune" \
		-H "X-Task-Token: $(TASK_TOKEN)" \
		-H 'Content-Type: application/json' \
		-d '{"dry_run": false, "confirm": "PRUNE", "audit_older_than_days": 30, "audit_limit": 50000, "ingestions_older_than_days": 90, "ingestions_limit": 5000}' | jq .


# -----------------------------
# Edge device registry helpers (internal endpoints)
# -----------------------------

device-list: ## List provisioned devices (internal endpoint)
	@curl -sS "$(LOCAL_URL)/internal/admin/devices?limit=200" \
		-H "X-Task-Token: $(TASK_TOKEN)" | jq .

device-create: ## Provision a device. Usage: make device-create DEVICE_ID=rpi-001 LABEL="Barn 1"
	@if [ -z "$(DEVICE_ID)" ]; then echo "ERROR: set DEVICE_ID=..."; exit 2; fi
	@curl -sS -X POST "$(LOCAL_URL)/internal/admin/devices" \
		-H "X-Task-Token: $(TASK_TOKEN)" \
		-H 'Content-Type: application/json' \
		-d '{"device_id":"$(DEVICE_ID)","label":"$(LABEL)"}' | jq .

device-rotate: ## Rotate a device token. Usage: make device-rotate DEVICE_ID=rpi-001
	@if [ -z "$(DEVICE_ID)" ]; then echo "ERROR: set DEVICE_ID=..."; exit 2; fi
	@curl -sS -X POST "$(LOCAL_URL)/internal/admin/devices/$(DEVICE_ID)/rotate_token" \
		-H "X-Task-Token: $(TASK_TOKEN)" | jq .

device-revoke: ## Revoke a device. Usage: make device-revoke DEVICE_ID=rpi-001
	@if [ -z "$(DEVICE_ID)" ]; then echo "ERROR: set DEVICE_ID=..."; exit 2; fi
	@curl -sS -X POST "$(LOCAL_URL)/internal/admin/devices/$(DEVICE_ID)/revoke" \
		-H "X-Task-Token: $(TASK_TOKEN)" | jq .

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
check-secrets-gcp: doctor-gcp infra-gcp
	@set -euo pipefail; \
	ALLOW_UNAUTH="$${TF_VAR_allow_unauthenticated:-true}"; \
	INGEST_MODE="$${TF_VAR_ingest_auth_mode:-none}"; \
	EDGE_ENROLL="$${TF_VAR_enable_edge_enroll:-false}"; \
	echo "Checking required Secret Manager versions..."; \
	missing=0; \
	check_secret() { \
		local secret="$$1"; local label="$$2"; local hint="$$3"; \
		if ! gcloud secrets describe "$$secret" >/dev/null 2>&1; then \
			echo "  ✗ Missing secret container: $$secret (run: make infra-gcp)"; \
			missing=1; return; \
		fi; \
		local v; v=$$(gcloud secrets versions list "$$secret" --filter="state:ENABLED" --format="value(name)" --limit=1 2>/dev/null | head -n1); \
		if [ -z "$$v" ]; then \
			echo "  ✗ $$label has no ENABLED versions in $$secret (run: $$hint)"; \
			missing=1; \
		else \
			echo "  ✓ $$label version: $$v"; \
		fi; \
	}; \
	check_secret eventpulse-database-url DATABASE_URL "make db-secret"; \
	if [ "$$ALLOW_UNAUTH" != "false" ]; then \
		check_secret eventpulse-task-token TASK_TOKEN "make task-token-secret"; \
	else \
		echo "  ✓ TASK_TOKEN not required (allow_unauthenticated=false / IAM mode)"; \
	fi; \
	if [ "$${INGEST_MODE,,}" = "token" ]; then \
		check_secret eventpulse-ingest-token INGEST_TOKEN "make ingest-token-secret"; \
	else \
		echo "  ✓ INGEST_TOKEN not required (INGEST_AUTH_MODE!=token)"; \
	fi; \
	if [ "$${EDGE_ENROLL,,}" = "true" ]; then \
		check_secret eventpulse-edge-enroll-token EDGE_ENROLL_TOKEN "make edge-enroll-token-secret"; \
	else \
		echo "  ✓ EDGE_ENROLL_TOKEN not required (enable_edge_enroll=false)"; \
	fi; \
	if [ "$$missing" -ne 0 ]; then \
		echo ""; \
		echo "Secrets check failed. Add the missing secret versions, then re-run."; \
		exit 1; \
	fi; \
	echo "Secrets OK."



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
build-gcp: doctor-gcp check-secrets-gcp grant-cloudbuild-gcp
	@echo "Building + pushing via Cloud Build: $(IMAGE)"
	gcloud builds submit --tag "$(IMAGE)" .

deploy-gcp: build-gcp apply-gcp verify-gcp

# Production-ish posture: private Cloud Run + IAM, direct-to-GCS signed URLs, and event-driven ingestion.
deploy-gcp-private:
	TF_VAR_allow_unauthenticated=false \
	TF_VAR_enable_signed_urls=true \
	TF_VAR_enable_gcs_event_ingestion=true \
	$(MAKE) deploy-gcp


url-gcp: tf-init-gcp
	@terraform -chdir=$(TF_DIR) output -raw service_url

verify-gcp: tf-init-gcp
	@URL=$$(terraform -chdir=$(TF_DIR) output -raw service_url); \
	echo "Service URL: $$URL"; \
	curl -fsS "$$URL/health" >/dev/null && echo "OK: /health" || (echo "Health check failed"; exit 1); \
	curl -fsS "$$URL/readyz" >/dev/null && echo "OK: /readyz" || (echo "Readiness check failed"; exit 1)
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

# Add a TASK_TOKEN secret version (reads from stdin).
# Usage:
#   make task-token-secret
#   (paste a random token and press Ctrl-D)
task-token-secret: doctor-gcp
	@echo "Paste TASK_TOKEN then press Ctrl-D (recommend: 32+ random bytes urlsafe)";
	@gcloud secrets versions add eventpulse-task-token --data-file=-

# Add an INGEST_TOKEN secret version (reads from stdin).
# Usage:
#   make ingest-token-secret
#   (paste a random token and press Ctrl-D)
ingest-token-secret: doctor-gcp
	@echo "Paste INGEST_TOKEN then press Ctrl-D (recommend: 32+ random bytes urlsafe)";
	@gcloud secrets versions add eventpulse-ingest-token --data-file=-

# Add an EDGE_ENROLL_TOKEN secret version (reads from stdin).
# Usage:
#   TF_VAR_enable_edge_enroll=true make edge-enroll-token-secret
#   (paste a random token and press Ctrl-D)
edge-enroll-token-secret: doctor-gcp
	@echo "Paste EDGE_ENROLL_TOKEN then press Ctrl-D (recommend: 32+ random bytes urlsafe)";
	@gcloud secrets versions add eventpulse-edge-enroll-token --data-file=-


# -----------------------------
# Field ops: edge agent image
# -----------------------------

EDGE_IMAGE_TAR ?= dist/$(EDGE_IMAGE_NAME)_$(EDGE_IMAGE_TAG).tar.gz

# Target platform for the edge-agent image (default: arm64 for Raspberry Pi OS 64-bit).
#
# Notes:
# - On an M2 MacBook Pro, linux/arm64 is the native arch (fast builds).
# - On an x86_64 machine, use Docker Buildx + QEMU to build linux/arm64.
EDGE_IMAGE_PLATFORM ?= linux/arm64

edge-image-build: ## Build the edge-agent container image (default: linux/arm64)
	$(call require,docker)
	@echo "Building edge agent image: $(EDGE_IMAGE_LOCAL) (platform=$(EDGE_IMAGE_PLATFORM))"
	@if docker buildx version >/dev/null 2>&1; then \
		docker buildx build --platform "$(EDGE_IMAGE_PLATFORM)" -t "$(EDGE_IMAGE_LOCAL)" -f services/edge_agent/Dockerfile --load .; \
	else \
		echo "docker buildx not available; falling back to docker build (host arch)" >&2; \
		docker build -t "$(EDGE_IMAGE_LOCAL)" -f services/edge_agent/Dockerfile .; \
	fi

edge-image-export: edge-image-build ## Export the edge-agent image to a tar.gz (scp to device + docker load)
	$(call require,docker)
	@mkdir -p dist
	@echo "Exporting $(EDGE_IMAGE_LOCAL) -> $(EDGE_IMAGE_TAR)"
	@docker save "$(EDGE_IMAGE_LOCAL)" | gzip > "$(EDGE_IMAGE_TAR)"
	@echo ""
	@echo "Copy to a Pi and load:";
	@echo "  scp $(EDGE_IMAGE_TAR) pi@PI_HOST:/tmp/";
	@echo "  ssh pi@PI_HOST 'gunzip -c /tmp/$(EDGE_IMAGE_NAME)_$(EDGE_IMAGE_TAG).tar.gz | docker load'";
	@echo ""
	@echo "Then set EDGE_AGENT_IMAGE=$(EDGE_IMAGE_LOCAL) in /etc/eventpulse-edge/edge.env and restart the service."

edge-image-load: ## Load an exported edge-agent image tar.gz (run on the Pi)
	$(call require,docker)
	@if [ ! -f "$(EDGE_IMAGE_TAR)" ]; then echo "Missing $(EDGE_IMAGE_TAR)"; exit 1; fi
	@echo "Loading $(EDGE_IMAGE_TAR)"
	@gunzip -c "$(EDGE_IMAGE_TAR)" | docker load

edge-image-push: edge-image-build doctor-gcp ## Push the edge-agent image to Artifact Registry (optional)
	$(call require,docker)
	@echo "Tagging $(EDGE_IMAGE_LOCAL) -> $(EDGE_IMAGE_REMOTE)"
	@docker tag "$(EDGE_IMAGE_LOCAL)" "$(EDGE_IMAGE_REMOTE)"
	@echo "Pushing: $(EDGE_IMAGE_REMOTE)"
	@gcloud auth configure-docker "$(REGION)-docker.pkg.dev" -q
	@docker push "$(EDGE_IMAGE_REMOTE)"

# Generate lockfiles locally for team reproducibility.
lock: doctor
	@echo "Generating uv.lock (Python)"
	uv lock
	@echo "Generating pnpm-lock.yaml (workspace)"
	corepack enable
	pnpm install
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
	@if command -v terraform >/dev/null 2>&1; then \
		terraform -chdir=$(TF_DIR) fmt -check -recursive; \
		elif command -v docker >/dev/null 2>&1; then \
		  echo "terraform not found; running terraform fmt check via Docker"; \
		  docker run --rm -v "$$(pwd)/$(TF_DIR):/workspace" -w /workspace hashicorp/terraform:1.9.8 fmt -check -recursive; \
		else \
		  echo "terraform not found and docker not available; skipping tf-fmt" >&2; \
		fi

tf-validate: ## Terraform validate (no remote backend required)
	@if command -v terraform >/dev/null 2>&1; then \
		terraform -chdir=$(TF_DIR) init -backend=false -upgrade >/dev/null; \
		terraform -chdir=$(TF_DIR) validate; \
		elif command -v docker >/dev/null 2>&1; then \
		  echo "terraform not found; running terraform validate via Docker"; \
		  docker run --rm -v "$$(pwd)/$(TF_DIR):/workspace" -w /workspace hashicorp/terraform:1.9.8 init -backend=false -upgrade >/dev/null; \
		  docker run --rm -v "$$(pwd)/$(TF_DIR):/workspace" -w /workspace hashicorp/terraform:1.9.8 validate; \
		else \
		  echo "terraform not found and docker not available; skipping tf-validate" >&2; \
		fi

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


# -----------------------------------------------------------------------------
# Repo quality gates (harness)
# -----------------------------------------------------------------------------

.PHONY: fmt lint typecheck test build harness-doctor

fmt: ## Format repo (ruff + terraform fmt via pre-commit)
	@python scripts/harness.py fmt

lint: ## Lint repo (ruff + terraform fmt check via pre-commit)
	@python scripts/harness.py lint

typecheck: ## Typecheck repo (pyright + mypy where configured)
	@python scripts/harness.py typecheck

test: ## Run tests (pytest)
	@python scripts/harness.py test

build: ## Build (frontend build if configured)
	@python scripts/harness.py build

harness-doctor: ## Explain what the harness will run
	@python scripts/harness.py doctor
