#!/usr/bin/env bash
set -euo pipefail

if ! command -v pnpm >/dev/null 2>&1; then
  echo "[web_build] pnpm not installed; skipping (corepack enable && pnpm -v)"
  exit 0
fi

# In some sandboxed environments, corepack cannot download pnpm from npmjs.
if ! pnpm -v >/dev/null 2>&1; then
  echo "[web_build] pnpm is present but cannot run (corepack download blocked); skipping"
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
  pnpm install --frozen-lockfile
else
  echo "[web_build] WARNING: pnpm-lock.yaml missing; running non-frozen install"
  pnpm install
fi

pnpm -C web build
