# Incident runbook

This is a pragmatic incident guide for EventPulse running on:

- Cloud Run (single service)
- Postgres (Cloud SQL or equivalent)
- GCS (raw landing)
- Optional Cloud Tasks async processing

It is intentionally lightweight for a small team / field deployment.

## Phases

1.  Detect & declare
2.  Triage and assess impact
3.  Mitigate
4.  Root cause analysis
5.  Follow-ups and prevention

## Severity (example)

-   SEV0: Complete outage / major security incident
-   SEV1: Significant degradation for many users
-   SEV2: Partial degradation / limited scope
-   SEV3: Minor impact

## Mitigation principles

-   Stop the bleed first (rollback, disable feature flag, reduce load).
-   Prefer reversible changes.
-   Keep a timeline of actions.

## Communications

-   Identify incident commander.
-   Post regular updates at a fixed cadence.
-   Maintain a single source of truth (incident doc/ticket).

## Post-incident

-   Write a root cause analysis:
    -   what happened
    -   why it happened
    -   what prevented earlier detection
    -   what changes prevent recurrence
-   Convert follow-ups into tracked issues.

---

## Fast triage checklist

### Cloud Run

- `GET /healthz` (Cloud Run URL)
- `GET /api/meta` (confirm runtime flags + storage backend)
- Cloud Run logs:
  - elevated 5xx
  - timeouts
  - Postgres connection failures

### Postgres

- connections saturated?
- disk full?
- long-running queries?

### Cloud Tasks

- backlog growing?
- task handler returning non-2xx?

### GCS

- raw bucket writes succeeding?
- object finalize events arriving?

### Field devices

- Devices page: are many devices suddenly offline?
- Is `EDGE_OFFLINE_THRESHOLD_SECONDS` set appropriately for the upload cadence?
- If enrollment is failing:
  - confirm `EDGE_ENROLL_TOKEN` secret is present
  - check `/api/edge/enroll` logs
