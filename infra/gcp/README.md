# GCP infrastructure

This folder contains a **working, team-ready** GCP deployment example.

- `cloud_run_api_demo/` — deploys the EventPulse API + UI to Cloud Run
- `modules/` — reusable baseline modules (APIs, AR, Cloud Run, IAM, optional VPC connector)

This repo is designed to be driven from the repo root **Makefile** (no manual `export ...`).

See:
- `docs/DEPLOY_GCP.md`
- `docs/TEAM_WORKFLOW.md`
