#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/apps/api/.venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "Missing API virtualenv. Run: make install or ./scripts/bootstrap-local.sh" >&2
  exit 1
fi

cd "$ROOT/apps/api"
"$PY" -m compileall -q app scripts
"$PY" -m pytest -q ../../tests
"$PY" -c "from app.services.migrations import migration_status; print(migration_status())"

cd "$ROOT/apps/web"
if [ -f package-lock.json ]; then
  npm ci --registry=https://registry.npmjs.org
else
  npm install --registry=https://registry.npmjs.org
fi
npm run build

echo "v0.7 verification passed"
