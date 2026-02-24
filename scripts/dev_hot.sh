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

if ! command -v uv >/dev/null 2>&1; then
	echo "uv is required for hot-reload dev. Install it first (brew install uv)."
	exit 1
fi
if ! command -v pnpm >/dev/null 2>&1; then
	echo "pnpm is required for hot-reload dev. Install it first (corepack enable)."
	exit 1
fi

cp -n .env.host.example .env.host || true

echo "== Dev hot reload: starting Postgres + Redis =="
compose up -d postgres redis

echo "== Dev hot reload: waiting for Postgres + Redis health =="
for svc in postgres redis; do
	deadline=$((SECONDS + 60))
	while true; do
		row="$(compose ps -a "$svc" | awk 'NR>1 { print }')"
		if echo "$row" | grep -q "healthy"; then
			echo "  ✓ $svc healthy"
			break
		fi
		if [ "$SECONDS" -ge "$deadline" ]; then
			echo "  ✗ $svc did not become healthy within 60s"
			compose logs --tail=120 "$svc" || true
			exit 1
		fi
		sleep 1
	done
done

echo "== Dev hot reload: syncing dependencies =="
uv sync --dev
corepack enable >/dev/null 2>&1 || true
pnpm install --frozen-lockfile

set -a
# shellcheck disable=SC1091
source .env.host
set +a

api_pid=""
worker_pid=""
web_pid=""

cleanup() {
	local code=$?
	trap - EXIT INT TERM
	echo ""
	echo "== Dev hot reload: stopping processes =="
	stop_pid() {
		local pid="$1"
		if [ -z "$pid" ]; then
			return 0
		fi
		if kill -0 "$pid" 2>/dev/null; then
			kill "$pid" 2>/dev/null || true
			local deadline=$((SECONDS + 8))
			while kill -0 "$pid" 2>/dev/null && [ "$SECONDS" -lt "$deadline" ]; do
				sleep 1
			done
		fi
		if kill -0 "$pid" 2>/dev/null; then
			kill -9 "$pid" 2>/dev/null || true
		fi
		wait "$pid" 2>/dev/null || true
	}
	stop_pid "$api_pid"
	stop_pid "$worker_pid"
	stop_pid "$web_pid"
	echo "== Dev hot reload: stopping Postgres + Redis =="
	compose down >/dev/null 2>&1 || true
	exit "$code"
}
trap cleanup EXIT INT TERM

echo "== Dev hot reload: starting API, worker, and Vite =="
uv run uvicorn eventpulse.api_server:app --reload --host 0.0.0.0 --port 8081 --proxy-headers --forwarded-allow-ips '*' &
api_pid=$!
uv run rq worker --url "${REDIS_URL}" --worker-class rq.SimpleWorker eventpulse &
worker_pid=$!
pnpm -C web dev --host 0.0.0.0 --port 5174 --strictPort &
web_pid=$!

echo "== Dev hot reload: waiting for API + Vite and seeding parcels =="
DEV_BASE_URL="${BASE_URL}" python3 - <<'PY'
import json
import http.client
import os
import socket
import time
import urllib.error
import urllib.request

base = os.environ["DEV_BASE_URL"].rstrip("/")


def wait_for_status(url: str, expected: int = 200, timeout_seconds: int = 45) -> None:
    deadline = time.time() + timeout_seconds
    last_error: str | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
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
    raise SystemExit(f"{url} failed to return {expected} within {timeout_seconds}s ({last_error})")


wait_for_status(f"{base}/api/healthz", expected=200, timeout_seconds=45)
wait_for_status("http://localhost:5174/", expected=200, timeout_seconds=60)

seed_req = urllib.request.Request(
    f"{base}/api/demo/seed/parcels?limit=60&per_ingestion_max=15",
    method="POST",
)
with urllib.request.urlopen(seed_req, timeout=30) as resp:
    payload = json.loads(resp.read().decode("utf-8"))
    if resp.status != 200 or not payload.get("ok"):
        raise SystemExit(f"seed failed: status={resp.status} payload={payload}")

deadline = time.time() + 45
last_status = None
while time.time() < deadline:
    try:
        with urllib.request.urlopen(
            f"{base}/api/datasets/parcels/marts/price_per_acre_by_land_type?limit=10",
            timeout=10,
        ) as resp:
            if resp.status == 200:
                break
    except urllib.error.HTTPError as exc:
        last_status = exc.code
        if exc.code != 404:
            raise
    time.sleep(1)
else:
    raise SystemExit(
        f"parcels mart not ready within 45s (last status={last_status})"
    )
PY

echo "== Dev hot reload ready =="
echo "API: ${BASE_URL}"
echo "Web: http://localhost:5174"
echo "Press Ctrl-C to stop."

while true; do
	if ! kill -0 "$api_pid" 2>/dev/null; then
		echo "API process exited unexpectedly."
		exit 1
	fi
	if ! kill -0 "$worker_pid" 2>/dev/null; then
		echo "Worker process exited unexpectedly."
		exit 1
	fi
	if ! kill -0 "$web_pid" 2>/dev/null; then
		echo "Vite process exited unexpectedly."
		exit 1
	fi
	sleep 2
done
