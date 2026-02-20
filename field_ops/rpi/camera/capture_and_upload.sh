#!/usr/bin/env bash
set -euo pipefail

API_BASE=${API_BASE:?Set API_BASE (no trailing slash)}
DEVICE_ID=${DEVICE_ID:?Set DEVICE_ID}
DEVICE_TOKEN=${DEVICE_TOKEN:?Set DEVICE_TOKEN}

OUT=${OUT:-/tmp/eventpulse_snapshot.jpg}

# Choose a default capture command based on what's installed.
if [[ -z "${CAPTURE_CMD:-}" ]]; then
  if command -v libcamera-still >/dev/null 2>&1; then
    CAPTURE_CMD="libcamera-still --timeout 2000 --width 1280 --height 720 -o"
  elif command -v fswebcam >/dev/null 2>&1; then
    CAPTURE_CMD="fswebcam -r 1280x720 --jpeg 90 -D 2"
  else
    echo "No camera capture tool found. Install 'libcamera-apps' or 'fswebcam'." >&2
    exit 1
  fi
fi

mkdir -p "$(dirname "$OUT")"

# Capture snapshot
echo "Capturing snapshot -> $OUT"
# Both tools accept the output path as the final argument.
$CAPTURE_CMD "$OUT"

bytes=$(stat -c%s "$OUT" 2>/dev/null || wc -c < "$OUT")

# Request signed URL
resp=$(curl -sS -X POST "$API_BASE/api/edge/media/signed_url" \
  -H "X-Device-Id: $DEVICE_ID" \
  -H "X-Device-Token: $DEVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"filename":"snapshot.jpg","content_type":"image/jpeg"}')

upload_url=$(echo "$resp" | jq -r '.upload_url')
gcs_uri=$(echo "$resp" | jq -r '.gcs_uri')

if [[ -z "$upload_url" || "$upload_url" == "null" ]]; then
  echo "Failed to mint signed URL:" >&2
  echo "$resp" >&2
  exit 2
fi

# Build curl headers from required_headers map
mapfile -t hdrs < <(echo "$resp" | jq -r '.required_headers | to_entries[] | "\(.key): \(.value)"')

curl_args=()
for h in "${hdrs[@]}"; do
  curl_args+=(-H "$h")
done

# Upload bytes
echo "Uploading bytes to GCS (signed URL)"
curl -sS -X PUT "$upload_url" "${curl_args[@]}" --data-binary @"$OUT" >/dev/null

# Finalize / record
captured_at=$(date -u +%FT%TZ)

finalize=$(jq -n \
  --arg gcs_uri "$gcs_uri" \
  --arg captured_at "$captured_at" \
  --arg media_type "image" \
  --argjson bytes "$bytes" \
  '{gcs_uri:$gcs_uri,captured_at:$captured_at,media_type:$media_type,bytes:$bytes}')

curl -sS -X POST "$API_BASE/api/edge/media/finalize" \
  -H "X-Device-Id: $DEVICE_ID" \
  -H "X-Device-Token: $DEVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$finalize" >/dev/null

echo "Uploaded + recorded: $gcs_uri"
