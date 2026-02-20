# RPi Camera (optional) — capture + upload

This folder contains a small helper script to capture a snapshot (USB webcam via `fswebcam` **or** Pi camera via `libcamera-still`) and upload it to EventPulse using the **edge media** signed-URL flow.

> Media uploads are **optional** and disabled by default. On the API service, set `ENABLE_EDGE_MEDIA=true`.

## Prereqs (RPi)

- A camera:
  - USB webcam: install `fswebcam`
  - Pi camera module: install `libcamera-apps`
- `curl`
- `jq`

## Env vars

```bash
export API_BASE="https://<cloud-run-url>"   # no trailing slash
export DEVICE_ID="..."
export DEVICE_TOKEN="..."

# Optional: override capture command
# export CAPTURE_CMD='fswebcam -r 1280x720 --jpeg 90 -D 2'
```

## Run

```bash
./capture_and_upload.sh
```

The script prints the resulting `gs://...` URI and records a `device_media` row so operators can view it in the SPA (**Media** page).

## Notes

- For cost control, set a GCS lifecycle rule to expire `media/` objects after N days.
- This is meant for operational snapshots (e.g., verify a leak/drip), not continuous surveillance.
