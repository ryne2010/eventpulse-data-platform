#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://localhost:8081}"
shift || true

if [ "$#" -eq 0 ]; then
	COMPOSE_CMD=(docker compose)
else
	COMPOSE_CMD=("$@")
fi

compose() {
	"${COMPOSE_CMD[@]}" "$@"
}

echo "== Smoke: starting core services =="
compose up --build -d api worker postgres redis

echo "== Smoke: verifying worker is running =="
if ! compose ps -a worker | awk 'NR>1 { print }' | grep -q "Up"; then
	echo "Worker is not running. Recent worker logs:"
	compose logs --tail=150 worker || true
	exit 1
fi

echo "== Smoke: checking API + SPA routes at ${BASE_URL} =="
if ! SMOKE_BASE_URL="${BASE_URL}" python3 - <<'PY'
import json
import os
import time
import urllib.error
import urllib.request

base = os.environ["SMOKE_BASE_URL"].rstrip("/")

for path in ["/api/healthz", "/api/meta", "/api/stats?hours=24", "/", "/devices", "/media"]:
    with urllib.request.urlopen(base + path, timeout=10) as resp:
        print(path, resp.status)
        if resp.status != 200:
            raise SystemExit(f"unexpected status for {path}: {resp.status}")

seed_req = urllib.request.Request(
    f"{base}/api/demo/seed/edge_telemetry?limit=120&per_ingestion_max=120",
    method="POST",
)
with urllib.request.urlopen(seed_req, timeout=30) as resp:
    payload = json.loads(resp.read().decode("utf-8"))
    print("seed", resp.status, payload.get("ok"), payload.get("rows"))

deadline = time.time() + 45
last_status = None
while time.time() < deadline:
    try:
        with urllib.request.urlopen(
            f"{base}/api/datasets/edge_telemetry/marts/device_status?limit=5",
            timeout=10,
        ) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            print(
                "/api/datasets/edge_telemetry/marts/device_status?limit=5",
                resp.status,
                f"rows={len(body.get('rows', []))}",
            )
            if resp.status == 200:
                raise SystemExit(0)
    except urllib.error.HTTPError as exc:
        last_status = exc.code
        if exc.code != 404:
            raise
    time.sleep(1)

raise SystemExit(f"device_status mart not ready within 45s (last status={last_status})")
PY
then
	echo "Smoke route checks failed. Recent api/worker logs:"
	compose logs --tail=150 api worker || true
	exit 1
fi

echo "Smoke OK."
