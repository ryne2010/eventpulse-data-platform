#!/usr/bin/env bash
set -euo pipefail

# Run UI lint/typecheck (tsc) if dependencies are installed.
#
# This repo is Python-first; UI checks are opportunistic locally.
# CI runs UI checks in a dedicated job.

if [[ ! -d web ]]; then
  exit 0
fi

if ! command -v pnpm >/dev/null 2>&1; then
  echo "pnpm not found; skipping web lint" >&2
  exit 0
fi

if [[ ! -d web/node_modules ]]; then
  echo "web/node_modules not found; skipping web lint (run: pnpm install at repo root)" >&2
  exit 0
fi

(cd web && pnpm lint)
