#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/apps/api"
if [ ! -x .venv/bin/python ]; then
  echo "Run scripts/bootstrap-local.sh first" >&2
  exit 1
fi
exec .venv/bin/python -m app.workers.asset_worker
