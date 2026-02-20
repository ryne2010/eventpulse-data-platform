# Edge Agent (RPi)

This is the **buffered edge ingestion** container intended for **Raspberry Pi** (or any
Linux edge device) running in the field on intermittent connectivity (e.g. 5G SIM).

It:

1. Samples sensor readings (simulated by default)
2. Spools batches to **rotated CSV files** on local disk
3. Uploads batches to EventPulse:
   - **Preferred (Cloud Run):** GCS signed URL flow (device uploads directly to GCS)
   - **Fallback/local:** direct API upload

## Telemetry schema

The edge agent spools **contract-aligned** CSV batches for the `edge_telemetry` dataset
(see `data/contracts/edge_telemetry.yaml`). Each row is an event:

- `event_type`: `reading` | `heartbeat` | `error`
- `sensor`, `value`, `units`: present for `reading`
- `status`, `message`: useful for heartbeats/errors
- `lat`, `lon`, `battery_v`, `rssi_dbm`, `firmware_version`: optional enrichment fields

Columns (in order):

`event_id,device_id,event_type,sensor,value,units,ts,lat,lon,battery_v,rssi_dbm,firmware_version,status,message`

## Sensor input formats (stdin/script)

When `EDGE_SENSOR_MODE` is `stdin` or `script`, the agent can parse sensor output in
multiple lightweight formats (so hardware drivers can live outside the core agent):

- **JSON** object (single event) or JSON array (multiple events)
- **CSV line**: `sensor,value,units`
- **Float**: `value` (sensor defaults to `script_value`)

Example JSON (single reading):

```json
{"event_type":"reading","sensor":"oil_pressure_psi","value":42.3,"units":"psi"}
```

Example JSON (multiple readings):

```json
[
  {"sensor":"temp_c","value":23.2,"units":"C"},
  {"sensor":"humidity_pct","value":51.0,"units":"%"}
]
```


## Quick start (local Docker Compose)

From repo root:

```bash
make up
docker compose --profile edge up --build edge-agent
```

Then open:

- UI: http://localhost:8081
- Devices: http://localhost:8081/devices

## Upload modes

The edge agent supports three upload modes via `EDGE_UPLOAD_MODE`:

- `auto` (default): GETs `/api/meta` once and selects:
  - `signed_url` if `storage_backend=gcs` **and** `enable_edge_signed_urls=true`
  - otherwise `direct`
- `direct`: POSTs CSV batches to the API at `/api/edge/ingest/upload`
- `signed_url`: uses:
  1. `POST /api/edge/uploads/gcs_signed_url` (device-authenticated)
  2. `PUT` to the returned signed URL (direct-to-GCS)
  3. `POST /api/edge/ingest/from_gcs` (device-authenticated finalize)

## Device auth model

Recommended runtime model: **per-device tokens** (server-side revocable).

Fast provisioning option (recommended for *deployment speed*):

- Configure the API with a shared `EDGE_ENROLL_TOKEN`
- The edge agent will automatically call `/api/edge/enroll` on first boot (or after auth errors)
  to mint/rotate its per-device token.
- The token is persisted to `EDGE_DEVICE_TOKEN_FILE` so you don't need to bake secrets into images.

- API stores only a hash+salt per device
- tokens can be rotated/revoked
- edge agent sends `X-Device-Id` + `X-Device-Token`

Provision a device token via internal admin endpoints (see `docs/EDGE_RPI.md`).

## Raspberry Pi notes

- Best on **64-bit Raspberry Pi OS** (`linux/arm64`)
- Use a persistent spool volume (`/data/spool`) to survive power loss / outages
- Consider enabling read-only root FS and writing only to the spool volume (advanced)

## Environment variables

| Variable | Default | Notes |
|---|---:|---|
| `EDGE_API_BASE_URL` | `http://localhost:8081` | Cloud Run URL in production |
| `EDGE_DATASET` | `edge_telemetry` | Contract-backed dataset |
| `EDGE_SOURCE` | `edge_agent` | Source label stored with ingestions |
| `EDGE_DEVICE_ID` | hostname | Unique ID per device |
| `EDGE_DEVICE_TOKEN` | empty | Required when API `EDGE_AUTH_MODE=token` |
| `EDGE_DEVICE_LABEL` | empty | Optional human-friendly label (stored in device registry) |
| `EDGE_DEVICE_TOKEN_FILE` | `/data/spool/device_token.txt` | Persisted token location (recommended) |
| `EDGE_ENROLL_TOKEN` | empty | Optional: shared enrollment token used for `/api/edge/enroll` |
| `EDGE_ENROLL_EVERY_SECONDS` | `300` | Enrollment retry interval when offline |
| `EDGE_ENROLL_FINGERPRINT` | auto | Optional override for fingerprint (default is derived + hashed) |
| `EDGE_UPLOAD_MODE` | `auto` | `auto`, `direct`, `signed_url` |
| `EDGE_SAMPLE_HZ` | `2.0` | Sensor read frequency |
| `EDGE_HEARTBEAT_SECONDS` | `30` | Heartbeat event cadence |
| `EDGE_ROTATE_EVERY_SECONDS` | `60` | Rotate spool file cadence |
| `EDGE_SPOOL_DIR` | `/data/spool` | Persistent buffer location |
| `EDGE_MAX_SPOOL_MB` | `256` | Backpressure threshold |
| `EDGE_MAX_SPOOL_FILES` | `2000` | Backpressure threshold |
| `EDGE_FLUSH_EVERY_ROWS` | `10` | Reduce SD wear vs flush every row |
| `EDGE_UPLOAD_INTERVAL_SECONDS` | `10` | How often to try uploads |
| `EDGE_MAX_RETRIES_PER_FILE` | `12` | After this, file goes to `dead/` |
| `EDGE_REQUEST_TIMEOUT_SECONDS` | `30` | API/GCS request timeout |
| `EDGE_SENSOR_MODE` | `simulated` | `simulated`, `stdin`, `script` |
| `EDGE_SENSOR_SCRIPT` | empty | Used when `EDGE_SENSOR_MODE=script` |
| `EDGE_SENSOR_SCRIPT_SHELL` | `false` | If `true`, run sensor script via a shell (allows pipes); default runs without a shell for safety |
| `EDGE_FIRMWARE_VERSION` | `edge-agent/0.3.5` | Optional firmware string included in events |
| `EDGE_LAT` | empty | Optional fixed latitude (float) |
| `EDGE_LON` | empty | Optional fixed longitude (float) |
| `EDGE_BATTERY_V` | empty | Optional fixed battery voltage |
| `EDGE_RSSI_DBM` | empty | Optional fixed cellular RSSI (dBm) |
| `EDGE_SEED` | empty | Deterministic simulation |

## Production recommendation (Cloud Run)

1. Enable edge signed URLs on the API:
   - `STORAGE_BACKEND=gcs`
   - `ENABLE_EDGE_SIGNED_URLS=true`
2. Enable per-device auth on the API:
   - `EDGE_AUTH_MODE=token`
3. (Recommended for speed) Configure `EDGE_ENROLL_TOKEN` on the API and set it on the Pi.
   The agent will self-provision and persist a per-device token.
4. Deploy edge agent with `EDGE_UPLOAD_MODE=signed_url`.

Further hardening options: Cloud Run max instances, token rotation/revocation, basic network allowlists (when feasible), and monitoring/alerts.

### Idempotency note

When using `signed_url` mode the API generates signed URLs with an `ifGenerationMatch=0`
precondition. This prevents accidental overwrites. If an upload is retried and the object
already exists, GCS returns **412 Precondition Failed** and the agent will still call
finalize to register/enqueue ingestion.
