#!/usr/bin/env bash
set -euo pipefail

# Run UI typechecking (tsc) if dependencies are installed.
#
# Skips gracefully if pnpm or node_modules are missing.

if [[ ! -d web ]]; then
  exit 0
fi

if ! command -v pnpm >/dev/null 2>&1; then
  echo "pnpm not found; skipping web typecheck" >&2
  exit 0
fi

if [[ ! -d web/node_modules ]]; then
  echo "web/node_modules not found; skipping web typecheck (run: pnpm install at repo root)" >&2
  exit 0
fi

(cd web && pnpm typecheck)
