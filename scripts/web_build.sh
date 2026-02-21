#!/usr/bin/env bash
set -euo pipefail

PNPM_CMD=()
if command -v corepack >/dev/null 2>&1 && corepack pnpm -v >/dev/null 2>&1; then
  PNPM_CMD=(corepack pnpm)
elif command -v pnpm >/dev/null 2>&1; then
  PNPM_CMD=(pnpm)
else
  echo "[web_build] pnpm not installed; skipping"
  exit 0
fi

if [[ ! -d "web" ]]; then
  echo "[web_build] no web/ directory; skipping"
  exit 0
fi

# Install deps at the workspace root.
# NOTE: running `pnpm -C web install` would treat `web/` as a standalone project
# and bypass the workspace lockfile.
if [[ -f "pnpm-lock.yaml" ]]; then
  "${PNPM_CMD[@]}" install --frozen-lockfile
else
  echo "[web_build] WARNING: pnpm-lock.yaml missing; running non-frozen install"
  "${PNPM_CMD[@]}" install
fi

"${PNPM_CMD[@]}" -C web build
