#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="${1:-manual}"
cd "$ROOT/apps/api"
if [ ! -x .venv/bin/python ]; then
  echo "Run scripts/bootstrap-local.sh first" >&2
  exit 1
fi
exec .venv/bin/python scripts/backup.py --label "$LABEL"
