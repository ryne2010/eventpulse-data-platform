# Edge devices runbook (field ops)

This runbook covers day-2 operations for Raspberry Pi edge devices running the `eventpulse-edge-agent`.

## 1) Quick triage

### What is failing?

- **Device offline** in UI (Devices → Status)
- **Uploads failing** (spool grows, ingestion backlog)
- **401s / auth failures** (device revoked, token mismatch)

### What changed?

- Cloud Run deploy?
- rotated `EDGE_ENROLL_TOKEN` / device token?
- network/provider changes?
- OS updates on the Pi?

## 2) Check the platform first

### Cloud Run logs

- Filter by `device_id` if present
- Look for:
  - 401 responses on `/api/edge/*`
  - signed URL errors on `/api/edge/uploads/gcs_signed_url`
  - finalize errors on `/api/edge/ingest/from_gcs`

### GCS

- Is the raw bucket receiving new objects?
- Is lifecycle retention unexpectedly deleting objects?

### Postgres

- Is the curated table ingesting?
- Is `marts_edge_telemetry_device_status` updating?
- Are alerts updating?
  - `marts_edge_telemetry_latest_readings` (latest per sensor)
  - `marts_edge_telemetry_device_alerts` (active alerts)

If devices look "offline" too aggressively (or too slowly), tune:

- `EDGE_OFFLINE_THRESHOLD_SECONDS`

If alerts are too noisy / not noisy enough, tune default thresholds in:

- `eventpulse/loaders/postgres.py` → `marts_edge_telemetry_latest_readings`

## 3) Check a specific device

### On-device (SSH)

```bash
sudo systemctl status eventpulse-edge-agent
sudo journalctl -u eventpulse-edge-agent -n 200 --no-pager
```

Common fixes:

- restart service:

```bash
sudo systemctl restart eventpulse-edge-agent
```

- check disk usage:

```bash
df -h
sudo du -sh /var/lib/eventpulse-edge/spool
```

- verify time sync:

```bash
timedatectl
```

## 4) Auth issues

### Device token compromised / mismatched

- Rotate the device token:
  - `POST /internal/admin/devices/{device_id}/rotate_token`

Then update the device:

- delete token file and restart agent (re-enroll):

```bash
sudo rm -f /var/lib/eventpulse-edge/spool/device_token.txt
sudo systemctl restart eventpulse-edge-agent
```

> Requires `EDGE_ENROLL_TOKEN` enabled.

### Device should be decommissioned

- Revoke the device:
  - `POST /internal/admin/devices/{device_id}/revoke`

## 5) Connectivity issues

- if using a cellular router: check router signal + SIM status
- if using a modem HAT: verify Linux modem management (ModemManager, APN)
- verify DNS:

```bash
nslookup example.com
curl -I https://YOUR_CLOUD_RUN_URL/api/meta
```

## 6) Escalation

If the issue persists after restart + basic checks:

- collect:
  - `journalctl` logs
  - spool directory listing (counts + sizes)
  - current `/etc/eventpulse-edge/edge.env` (redact secrets)
  - Cloud Run request IDs for failing calls
- open an issue with:
  - device_id
  - timeframe
  - what changed
  - repro steps
