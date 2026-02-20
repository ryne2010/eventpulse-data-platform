# Field ops (RPi sensors over LTE/5G)

This doc is a pragmatic runbook for getting EventPulse running "for real" in the field.

Target environments:

- Development: **M2 Max MacBook Pro**
- Production ingestion backend: **Cloud Run** + **GCS** (signed URL uploads)
- Field device: **Raspberry Pi** (LTE/5G SIM connectivity)

This guide focuses on **ease of deployment** and **low operating cost**.

---

## Architecture (what runs where)

### Cloud

- **Cloud Run**: hosts the API + UI
- **GCS**: raw landing zone (device uploads directly using signed URLs)
- **Cloud Tasks**: async processing
- **Postgres** (Cloud SQL or other): metadata + curated tables + marts

### Field device (RPi)

- **eventpulse-edge-agent** container
  - buffers telemetry locally to disk (spool)
  - uploads using signed URLs when online
  - finalizes ingestions via the Cloud Run API

---

## Recommended field auth model (fast + safe)

Use **bootstrap enrollment**:

1) You configure a shared `EDGE_ENROLL_TOKEN` on the Cloud Run service.
2) A newly flashed device starts with only that enroll token.
3) The device calls `POST /api/edge/enroll` and receives a unique per-device token.
4) The device stores the token on disk and uses it for all subsequent calls.

Benefits:

- deployment is fast (no per-device token distribution step)
- tokens are revocable / rotatable per-device
- you can rotate the shared enroll token as needed

Security notes:

- treat `EDGE_ENROLL_TOKEN` as a secret (store in Secret Manager; do not commit)
- once your fleet is provisioned, you can disable enrollment by setting:
  - `enable_edge_enroll=false` (Terraform) or removing the secret/version

---

## Cloud-side setup (Cloud Run)

Follow `docs/DEPLOY_GCP.md` and ensure these are enabled:

- `STORAGE_BACKEND=gcs`
- `ENABLE_EDGE_SIGNED_URLS=true`
- `EDGE_AUTH_MODE=token`
- `EDGE_ALLOWED_DATASETS=edge_telemetry`
- `enable_edge_enroll=true` (Terraform) and `EDGE_ENROLL_TOKEN` secret version present

Then verify:

- `GET /api/meta` shows:
  - `edge_auth_mode: token`
  - `edge_enroll_enabled: true`
  - `enable_edge_signed_urls: true`

---

## Fleet monitoring + alerts (UI)

Once edge telemetry starts flowing, you get a basic field-ops console:

- **Dashboard → Field devices**: online/offline counts + alert counts
- **Devices → Status**: offline heuristic + per-device alert count
- **Devices → Map**: last-known device locations (lat/lon scatter)
- **Devices → Alerts**: fleet-wide active alerts (latest per-sensor + thresholds)
- **Device detail → Sensor snapshot**: per-sensor severity badges + trends

### Alert thresholds

Alerts are scored in Postgres (marts) for fast UI queries:

- `marts_edge_telemetry_latest_readings` (latest per device + sensor)
- `marts_edge_telemetry_device_alerts` (latest readings where severity > 0)
- `marts_edge_telemetry_device_geo_status` (device status joined with last known lat/lon)

Thresholds are intentionally simple defaults to accelerate bring-up in the field.
Tune them in:

- `eventpulse/loaders/postgres.py` → `ensure_marts_views()` → `marts_edge_telemetry_latest_readings`

If you need per-site/per-device thresholds, evolve to a table-driven model (device metadata → thresholds JSON) or a dedicated alerting service.

---

## Field hardware

Start with:

- Raspberry Pi 4 (2GB/4GB)
- high-endurance storage (microSD or USB SSD)
- LTE/5G connectivity (router or modem)

See: `docs/HARDWARE.md`.

---

## Build + ship the edge agent image (M2 → Pi)

The default field service expects a local image name:

- `eventpulse-edge-agent:latest`

On an **M2 Max** (arm64), the built image is natively compatible with **Pi OS 64-bit**.

By default, `make edge-image-build` targets **linux/arm64** (see `EDGE_IMAGE_PLATFORM` in the Makefile).
If you build on an x86_64 machine, you'll need Docker Buildx/QEMU to cross-build.

### Option A: no registry (fast + cheap)

Build + export:

```bash
make edge-image-build
make edge-image-export   # outputs dist/eventpulse-edge-agent_<tag>.tar.gz (see make output)
```

Copy + load on the Pi:

```bash
# Default output filename (EDGE_IMAGE_TAG=latest):
scp dist/eventpulse-edge-agent_latest.tar.gz pi@PI_HOST:/tmp/
ssh pi@PI_HOST 'gunzip -c /tmp/eventpulse-edge-agent_latest.tar.gz | docker load'
```

### Option B: push to a registry (best for remote updates)

If you push the image to Artifact Registry (or another registry), set:

- `EDGE_AGENT_IMAGE=REGISTRY/REPO/eventpulse-edge-agent:TAG`
- `EDGE_AGENT_PULL_POLICY=always`

Then you can use the built-in updater:

```bash
sudo eventpulse-edge-agent-update
```

---

## Field device setup (Raspberry Pi)

Tip: In the UI, go to **Devices → Provisioning** to copy a ready-to-run install command (auto-fills your Cloud Run URL) and, if provisioning manually, a ready-made `edge.env` snippet.

### 1) Install the edge agent service

On the Pi, clone this repo (or copy the `field_ops/` folder) and run:

```bash
sudo bash field_ops/rpi/install.sh \
  --api-base-url "https://YOUR_CLOUD_RUN_URL" \
  --enroll-token "PASTE_EDGE_ENROLL_TOKEN"
```

This will:

- install Docker (if missing)
- create:
  - `/etc/eventpulse-edge/edge.env`
  - `/var/lib/eventpulse-edge/spool/`
- install + enable:
  - `eventpulse-edge-agent.service`

### 2) Watch logs

```bash
sudo journalctl -u eventpulse-edge-agent -f
```

You should see:

- a `ping ok`
- enrollment success (if device token was missing)
- periodic uploads / finalize calls

### 3) Confirm the device appears in the UI

In the EventPulse UI:

- **Devices** page shows device activity + offline heuristics
- **Ops** page shows edge-related runtime flags

Offline heuristic tuning:

- `EDGE_OFFLINE_THRESHOLD_SECONDS` (default 600)

---



## Sensor setup (MVP → real hardware)

EventPulse treats edge telemetry as a **contract-backed dataset** (`edge_telemetry`).
For best results (and to match the UI dashboards), use these sensor names + units:

- `temp_c` (C)
- `humidity_pct` (%)
- `water_pressure_psi` (psi)
- `oil_pressure_psi` (psi)
- `oil_life_pct` (%)
- `oil_level_pct` (%)
- `drip_oil_level_pct` (%)

### Demo mode (no hardware)

By default, the edge agent runs with:

- `EDGE_SENSOR_MODE=simulated`

This mode already emits the sensors above (plus `vibration_g`) so you can validate
end-to-end ingestion, quality gates, and the Devices UI before wiring hardware.

### Script mode (recommended for real sensors)

For real sensors, keep the core agent lightweight and put hardware drivers in a script.

On the Pi, edit `/etc/eventpulse-edge/edge.env`:

```bash
EDGE_SENSOR_MODE=script
EDGE_SENSOR_SCRIPT="python3 /data/spool/read_sensors.py"
```

If your script needs direct hardware access from inside the container (I2C/SPI/USB camera), you can also set:

```bash
EDGE_DOCKER_DEVICES="/dev/i2c-1,/dev/spidev0.0,/dev/video0"
# Optionally run the container as root during bring-up (least secure):
EDGE_DOCKER_RUN_AS_ROOT="true"
```

Because `/var/lib/eventpulse-edge/spool` is mounted into the container at `/data/spool`, you can deploy/iterate the script **without rebuilding** the container image.

This repo includes a ready-to-copy template sensor script:

```bash
sudo cp field_ops/rpi/sensors/read_sensors.py /var/lib/eventpulse-edge/spool/read_sensors.py
sudo chmod +x /var/lib/eventpulse-edge/spool/read_sensors.py
```

Your script can print any of these formats:

- JSON object (single reading)
- JSON array (multiple readings per sample)
- CSV line: `sensor,value,units`

Example script output (JSON array):

```json
[
  {"sensor":"temp_c","value":22.8,"units":"C"},
  {"sensor":"water_pressure_psi","value":61.2,"units":"psi"}
]
```

Optional enrichment (useful for the UI):

- `EDGE_FIRMWARE_VERSION=edge-agent/0.3.5`
- `EDGE_LAT=...` and `EDGE_LON=...` (fixed site location)
- `EDGE_BATTERY_V=...` and `EDGE_RSSI_DBM=...` (if you can measure them)

See also: `services/edge_agent/README.md`.

---

## Optional: webcam photo/video uploads (field ops artifacts)

If you attach a USB webcam (or Pi camera), you may want **snapshots** or short clips for
field validation (leaks, spills, gauge readings). EventPulse supports a lightweight
**direct-to-GCS media flow** that stays separate from the strict tabular ingestion pipeline.

### Enable media uploads

Set these environment variables on the API service (Cloud Run recommended):

```bash
ENABLE_EDGE_MEDIA=true
# Optional: use a dedicated bucket; if empty, falls back to RAW_GCS_BUCKET
EDGE_MEDIA_GCS_BUCKET=
EDGE_MEDIA_GCS_PREFIX=media
EDGE_MEDIA_ALLOWED_EXTS=.jpg,.jpeg,.png,.mp4,.webm
```

### Device flow

1) Mint a signed URL (device token auth):

```bash
curl -s -X POST "$API_BASE/api/edge/media/signed_url" \
  -H "X-Device-Id: $DEVICE_ID" \
  -H "X-Device-Token: $DEVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"filename":"snapshot.jpg","content_type":"image/jpeg"}'
```

2) Upload the bytes directly to GCS with the returned `upload_url` and `required_headers`.

3) Finalize/record the media (so the UI can list it):

```bash
curl -s -X POST "$API_BASE/api/edge/media/finalize" \
  -H "X-Device-Id: $DEVICE_ID" \
  -H "X-Device-Token: $DEVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"gcs_uri":"gs://...","captured_at":"2026-02-20T12:34:56Z","media_type":"image"}'
```

### UI

The SPA includes a **Media** page for operators. Because media can be sensitive, it uses
`/internal/admin/media/*` endpoints (requires internal auth / task token or Cloud Run IAM).

Tip for cost control: configure a GCS lifecycle rule to delete `media/` objects after N days.


## Operations

### Rotate a device token

If a device token is compromised or you want routine rotation:

- Rotate via internal endpoint:
  - `POST /internal/admin/devices/{device_id}/rotate_token`

Update the device:

- easiest: delete the token file on the Pi and restart the agent so it re-enrolls

```bash
sudo rm -f /var/lib/eventpulse-edge/spool/device_token.txt
sudo systemctl restart eventpulse-edge-agent
```

(Requires `EDGE_ENROLL_TOKEN` still enabled.)

### Revoke a device

```bash
POST /internal/admin/devices/{device_id}/revoke
```

The device will start receiving 401s for edge endpoints.

### Update the edge agent container

If you publish a new container image (or retag `latest`):

```bash
sudo eventpulse-edge-agent-update
```

---

## Troubleshooting

### Device can’t enroll

Common causes:

- wrong `EDGE_ENROLL_TOKEN`
- `enable_edge_enroll=false` server-side
- clock skew on the Pi (ensure NTP)

### Signed URL uploads fail

Common causes:

- Cloud Run is not configured with `STORAGE_BACKEND=gcs`
- missing IAM for signing (Terraform sets this up when signed URLs are enabled)
- Pi is behind a captive portal / DNS issues

### Spool fills up

Tighten:

- `EDGE_MAX_SPOOL_MB`
- `EDGE_MAX_SPOOL_FILES`

Or increase device storage.

---

## Cost notes (start lean)

To keep costs minimal (especially for small fleets), start with:

- strong device tokens + revocation/rotation
- signed URL uploads (reduces API load and API bandwidth)
- Cloud Run `max_instances` (caps cost blast radius)
- logging/alerts on auth failures and unusual request rates

If you later need WAF/rate limiting at the edge, you can add Cloud Armor behind an external HTTP(S) Load Balancer — but start without it.
