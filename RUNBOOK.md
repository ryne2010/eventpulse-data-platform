# Runbook

This runbook covers local operations and the optional Cloud Run demo deployment.

## Local operations

### Start / stop

```bash
make up
make down
```

### Reset everything

```bash
make reset
```

### Generate sample files + ingest

```bash
make gen
make ingest
```

### Tail logs

```bash
make logs
```

---

## Cloud Run demo (optional)

### Deploy

```bash
make deploy-gcp
```

### Set DATABASE_URL

Before the service can start successfully, add a secret version:

```bash
make db-secret
```

### Verify and troubleshoot

```bash
make url-gcp
make verify-gcp
make logs-gcp
```

### Rollback

Use immutable image tags:

```bash
make deploy-gcp TAG=v2026-01-29-1
```

### Decommission

```bash
make destroy-gcp
```

Note: the Terraform state bucket is intentionally preserved.
