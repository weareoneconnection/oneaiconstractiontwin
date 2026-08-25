#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/apps/api"
if [ ! -x .venv/bin/python ]; then
  echo "Run scripts/bootstrap-local.sh first" >&2
  exit 1
fi
exec .venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
