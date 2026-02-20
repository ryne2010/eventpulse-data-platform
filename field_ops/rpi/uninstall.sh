#!/usr/bin/env bash
set -euo pipefail

# EventPulse Field Ops — Raspberry Pi uninstaller

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "ERROR: run as root (use sudo)" >&2
  exit 1
fi

echo "[field-ops] stopping service…" >&2
systemctl disable --now eventpulse-edge-agent.service >/dev/null 2>&1 || true

# Best-effort: stop/remove the container
/usr/bin/docker rm -f eventpulse-edge-agent >/dev/null 2>&1 || true

echo "[field-ops] removing unit + helpers…" >&2
rm -f /etc/systemd/system/eventpulse-edge-agent.service
rm -f /usr/local/bin/eventpulse-edge-agent-run
rm -f /usr/local/bin/eventpulse-edge-agent-update
systemctl daemon-reload

echo "[field-ops] NOTE: leaving config + spool by default:" >&2
echo "  /etc/eventpulse-edge" >&2
echo "  /var/lib/eventpulse-edge" >&2
echo "Remove them manually if you are decommissioning the device." >&2
