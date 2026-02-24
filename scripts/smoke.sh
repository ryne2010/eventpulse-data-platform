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
import http.client
import os
import socket
import time
import urllib.error
import urllib.request

base = os.environ["SMOKE_BASE_URL"].rstrip("/")

def wait_for_status(path: str, expected: int = 200, timeout_seconds: int = 30) -> None:
    deadline = time.time() + timeout_seconds
    last_error: str | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + path, timeout=10) as resp:
                print(path, resp.status)
                if resp.status == expected:
                    return
                last_error = f"unexpected status: {resp.status}"
        except (
            urllib.error.URLError,
            http.client.RemoteDisconnected,
            ConnectionResetError,
            TimeoutError,
            socket.timeout,
            OSError,
        ) as exc:
            last_error = str(exc)
        time.sleep(1)
    raise SystemExit(f"{path} failed to return {expected} within {timeout_seconds}s ({last_error})")


for path in ["/api/healthz", "/api/meta", "/api/stats?hours=24", "/", "/datasets", "/products"]:
    wait_for_status(path, expected=200, timeout_seconds=30)

seed_req = urllib.request.Request(
    f"{base}/api/demo/seed/parcels?limit=60&per_ingestion_max=15",
    method="POST",
)
with urllib.request.urlopen(seed_req, timeout=30) as resp:
    payload = json.loads(resp.read().decode("utf-8"))
    print("seed", resp.status, payload.get("ok"), payload.get("rows"))

deadline = time.time() + 45
last_status = None
mart_ready = False
while time.time() < deadline:
    try:
        with urllib.request.urlopen(
            f"{base}/api/datasets/parcels/marts/sales_by_year?limit=5",
            timeout=10,
        ) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            print(
                "/api/datasets/parcels/marts/sales_by_year?limit=5",
                resp.status,
                f"rows={len(body.get('rows', []))}",
            )
            if resp.status == 200:
                mart_ready = True
                break
    except urllib.error.HTTPError as exc:
        last_status = exc.code
        if exc.code != 404:
            raise
    time.sleep(1)

if not mart_ready:
    raise SystemExit(f"parcels sales_by_year mart not ready within 45s (last status={last_status})")

deadline = time.time() + 45
last_status = None
analytics_mart_ready = False
while time.time() < deadline:
    try:
        with urllib.request.urlopen(
            f"{base}/api/datasets/parcels/marts/price_per_acre_by_land_type?limit=10",
            timeout=10,
        ) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            print(
                "/api/datasets/parcels/marts/price_per_acre_by_land_type?limit=10",
                resp.status,
                f"rows={len(body.get('rows', []))}",
            )
            if resp.status == 200:
                rows = body.get("rows", [])
                by_type = {str(r.get("land_type")): float(r.get("median_price_per_acre") or 0) for r in rows}
                if not {"grassland", "dry farmland", "irrigated farmland"}.issubset(set(by_type.keys())):
                    raise SystemExit("missing expected land_type buckets in price_per_acre mart")
                if any(v <= 0 for v in by_type.values()):
                    raise SystemExit("invalid non-positive median $/acre in mart response")
                analytics_mart_ready = True
                break
    except urllib.error.HTTPError as exc:
        last_status = exc.code
        if exc.code != 404:
            raise
    time.sleep(1)

if not analytics_mart_ready:
    raise SystemExit(f"parcels price_per_acre_by_land_type mart not ready within 45s (last status={last_status})")

raise SystemExit(0)
PY
then
	echo "Smoke route checks failed. Recent api/worker logs:"
	compose logs --tail=150 api worker || true
	exit 1
fi

echo "Smoke OK."
