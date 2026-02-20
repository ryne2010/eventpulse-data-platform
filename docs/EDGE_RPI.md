# Field deployment: Raspberry Pi edge devices

This project includes a small **edge agent** container designed to run on a Raspberry Pi
(or any Linux edge device) collecting sensor readings and sending them upstream to the
EventPulse data platform.

The goal is to be realistic for “in the field” conditions:

- intermittent connectivity (5G / LTE)
- power loss / reboots
- limited disk + SD wear
- need for device-level authentication + revocation

## Architecture

**Recommended (Cloud Run production):**

1. Edge agent requests a **signed URL** from the API
2. Edge agent uploads the batch file **directly to GCS** via signed URL
3. Edge agent calls the API to **finalize** the upload (register ingestion + enqueue processing)

Why:
- avoids Cloud Run request size/time limits
- reduces API CPU/memory usage
- retry behavior is simpler and faster for the device

## Device auth model

Runtime model: **per-device tokens**.

- server stores only PBKDF2 hash+salt
- tokens can be rotated / revoked
- requests include:
  - `X-Device-Id`
  - `X-Device-Token`

Provisioning options:

### Option A (recommended for speed): bootstrap enrollment

- Configure the API with a shared `EDGE_ENROLL_TOKEN`
- Devices call `POST /api/edge/enroll` to mint/rotate their per-device token
- The edge agent supports this automatically and persists its token locally

This trades a bit of security (a shared enrollment token exists) for dramatically faster
field rollouts.

### Option B (most secure): manual provisioning via internal admin

- Use internal admin endpoints (requires `TASK_TOKEN` or Cloud Run IAM)
- Mint per-device tokens one-by-one and copy them to devices

## 1) Configure the API for edge devices (Cloud Run)

For production on Cloud Run, set:

- `STORAGE_BACKEND=gcs`
- `RAW_GCS_BUCKET=...` (the raw bucket)
- `EDGE_AUTH_MODE=token`
- `EDGE_ALLOWED_DATASETS=edge_telemetry` (tight default)
- `ENABLE_EDGE_SIGNED_URLS=true`

Optional (recommended for fast rollouts):

- `EDGE_ENROLL_TOKEN=...` (shared enrollment token; keep in Secret Manager)

You can keep the UI public, and still protect edge endpoints via device tokens.

## 2) Provisioning a device

### Option A: bootstrap enroll token (recommended)

On the Raspberry Pi, set `EDGE_ENROLL_TOKEN` (shared) and let the agent self-enroll.
No manual token copy/paste required.

The agent will:

1. POST to `/api/edge/enroll`
2. Receive a per-device token
3. Save it to `EDGE_DEVICE_TOKEN_FILE` (default: `/data/spool/device_token.txt`)

### Option B: manual provisioning (internal admin)

Use the internal admin endpoint (requires internal auth):

```bash
export API_BASE_URL="https://YOUR_CLOUD_RUN_URL"
export TASK_TOKEN="YOUR_TASK_TOKEN"   # only if TASK auth is token mode
export DEVICE_ID="rpi-001"

curl -sS -X POST "${API_BASE_URL}/internal/admin/devices" \
  -H "Content-Type: application/json" \
  -H "X-Task-Token: ${TASK_TOKEN}" \
  -d "$(jq -nc --arg device_id "${DEVICE_ID}" --arg label "Barn 1" '{device_id:$device_id,label:$label}')" | jq .
```

The response includes `device_token`. **Store it safely** — it is only returned at create/rotate time.

To rotate a token:

```bash
curl -sS -X POST "${API_BASE_URL}/internal/admin/devices/${DEVICE_ID}/rotate_token" \
  -H "X-Task-Token: ${TASK_TOKEN}" | jq .
```

To revoke a device:

```bash
curl -sS -X POST "${API_BASE_URL}/internal/admin/devices/${DEVICE_ID}/revoke" \
  -H "X-Task-Token: ${TASK_TOKEN}" | jq .
```

## 3) Install Docker on Raspberry Pi

### Fast path (recommended): systemd + installer script

For field deployments, the repo includes a **field ops** installer that:

- installs Docker (if missing)
- installs a hardened `systemd` unit
- writes `/etc/eventpulse-edge/edge.env`
- keeps the edge agent running across reboots

From the repo root on the Pi:

```bash
sudo bash field_ops/rpi/install.sh \
  --api-base-url "https://YOUR_CLOUD_RUN_URL" \
  --enroll-token "PASTE_EDGE_ENROLL_TOKEN"

sudo journalctl -u eventpulse-edge-agent -f
```

See `docs/FIELD_OPS.md` for the full runbook.

### Manual path

Use 64-bit Raspberry Pi OS for best results (ARM64).

Install Docker Engine and Docker Compose plugin following the official docs.
(Keeping this doc short on purpose—those steps change over time.)

## 4) Run the edge agent on Raspberry Pi

### Option A: run from this repo (build on the Pi)

```bash
git clone <this repo>
cd eventpulse-data-platform

# Configure env for the edge agent container:
cat > edge.env <<EOF
EDGE_API_BASE_URL=https://YOUR_CLOUD_RUN_URL
EDGE_UPLOAD_MODE=signed_url
EDGE_DATASET=edge_telemetry
EDGE_SOURCE=edge_agent
EDGE_DEVICE_ID=rpi-001
EDGE_ENROLL_TOKEN=PASTE_ENROLL_TOKEN_HERE
# Optional: set a friendly label
EDGE_DEVICE_LABEL=Barn 1
EOF

docker build -t eventpulse-edge-agent -f services/edge_agent/Dockerfile .
docker run -d --restart=always --name eventpulse-edge-agent \
  --security-opt=no-new-privileges \
  --cap-drop=ALL \
  --env-file ./edge.env \
  -v /var/lib/eventpulse-edge/spool:/data/spool \
  eventpulse-edge-agent
```

### Option B: run via Docker Compose (recommended for ops)

You can also use `docker compose` with a small compose file (example below):

```yaml
services:
  edge-agent:
    image: eventpulse-edge-agent:latest
    restart: always
    env_file: ./edge.env
    volumes:
      - /var/lib/eventpulse-edge/spool:/data/spool
```

## Operational hardening tips

These are out of scope for a demo, but worth considering for real deployments:

- **Time sync:** ensure NTP is enabled (timestamps + auth logs are more useful)
- **Disk:** mount spool volume on durable storage; set `EDGE_MAX_SPOOL_MB` to avoid disk-full
- **SD wear:** tune `EDGE_FLUSH_EVERY_ROWS` (trade durability vs write amplification)
- **Updates:** use a controlled update strategy (manual rollout, or a pull+restart timer)
- **Observability:** ship container logs (or at least capture them with journald)
- **Network:** consider VPN or private connectivity for higher assurance environments

## Troubleshooting

- Validate connectivity + auth:

```bash
curl -i "${API_BASE_URL}/api/edge/ping" \
  -H "X-Device-Id: rpi-001" \
  -H "X-Device-Token: PASTE_TOKEN_HERE"
```

- Inspect spool dirs on the Pi:

```bash
ls -lah /var/lib/eventpulse-edge/spool/{inflight,outbox,sent,dead}
```

If you see files accumulating in `outbox/`, the agent cannot upload (auth/network/API).

## Optional: webcam snapshots

If you attach a camera and enable `ENABLE_EDGE_MEDIA=true` on the API service, you can capture
and upload snapshots as field ops artifacts:

- `field_ops/rpi/camera/capture_and_upload.sh`
