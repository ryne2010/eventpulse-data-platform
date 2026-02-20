#!/usr/bin/env bash
set -euo pipefail

python scripts/harness.py lint
python scripts/harness.py typecheck
python scripts/harness.py test
