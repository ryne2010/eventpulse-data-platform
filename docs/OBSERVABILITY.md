# Observability (Logging + Monitoring + SLOs)

This repo treats observability as **code**: dashboards, alerts, log routing, and SLOs are provisioned via Terraform.

Files to review:
- `infra/gcp/cloud_run_api_demo/observability.tf` — dashboards + basic alerts
- `infra/gcp/cloud_run_api_demo/log_views.tf` — service-scoped log bucket + sink + log view
- `infra/gcp/cloud_run_api_demo/slo.tf` — Service Monitoring + Availability SLO + burn-rate alerts


## Application logs (request IDs + trace correlation)

The API emits structured JSON logs (Cloud Logging friendly) and automatically attaches:

- `request_id` — from `X-Request-ID` (if provided) or generated per request
- `logging.googleapis.com/trace` — derived from `X-Cloud-Trace-Context` on Cloud Run

This makes it easy to correlate:
- a user action in the UI → API logs
- a Cloud Run request → Cloud Trace span → application logs

Tip: when reporting a bug, paste the `X-Request-ID` from the response headers.

---

## Logging: service-scoped logs (client-safe pattern)

Instead of giving stakeholders broad `roles/logging.viewer` access on the project, this repo:

1) Routes only this service’s logs into a dedicated log bucket (Logs Router sink).
2) Creates a log view over that bucket.
3) Grants clients `roles/logging.viewAccessor` with an IAM condition pinned to that view.

This is a common pattern for:
- government/regulated work
- consulting engagements with shared observability
- multi-tenant environments

---

## Monitoring dashboards

The default dashboard includes:
- request volume
- error (5xx) rate
- p95-ish latency (via Cloud Run metrics)

Dashboards are safe to share with view-only audiences via `roles/monitoring.viewer`.

---

## SLOs and error budgets (staff-level ops story)

`slo.tf` creates:
- a **Service Monitoring service** for the Cloud Run service
- an **availability SLO** (2xx / total)
- **burn-rate alerts**:
  - fast burn (5m > 14.4x)
  - slow burn (1h > 6x)

Why burn rate alerts?
- They reflect **error budget consumption** instead of static thresholds.
- They are robust across traffic volume changes.

---

## Troubleshooting drills (great interview practice)

Try these controlled failures and document your findings:

1) **IAM failure**  
   Remove Secret Manager access (if used) or remove invoker role (for private services) and watch:
   - Cloud Run revision fails or 401/403 spikes
   - logs show permission errors

2) **Bad deploy**  
   Deploy a container that listens on the wrong port and confirm:
   - revision fails health checks
   - error surfaces in Cloud Run + logs

3) **Performance regression**  
   Add an artificial delay and observe:
   - latency metrics rise
   - alert thresholds trigger
   - SLO burn-rate trends change

Capture your results in `RUNBOOK.md` — that’s interview gold.

---

## In-app audit + quality trends (UI-facing observability)

In addition to Cloud Logging/Monitoring, the app persists lightweight, queryable telemetry:

- **Audit events**: `/api/audit_events`
  - ingestion lifecycle (received, processing_started, loaded, failed_quality, etc.)
  - ops actions (reclaim stuck, replay)
  - contract edits (when enabled)

- **Quality trend series**: `/api/trends/quality`
  - aggregated pass/fail counts over time buckets

These power the UI pages **Audit** and **Trends** and are useful for:
- debugging regressions without digging through logs
- building simple “data reliability” dashboards


