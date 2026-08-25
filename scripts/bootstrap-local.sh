#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if command -v python3.12 >/dev/null 2>&1; then
  PYTHON=python3.12
elif command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
else
  echo "Python 3.12+ is required" >&2
  exit 1
fi

"$PYTHON" - <<'PYCODE'
import sys
if sys.version_info < (3, 12):
    raise SystemExit(f"Python 3.12+ is required; found {sys.version.split()[0]}")
PYCODE

cd "$ROOT/apps/api"
if [ ! -d .venv ]; then
  "$PYTHON" -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
if [ "${INSTALL_IFC:-0}" = "1" ]; then
  .venv/bin/python -m pip install -r requirements-ifc.txt
fi
if [ "${INSTALL_OBSERVABILITY:-0}" = "1" ]; then
  .venv/bin/python -m pip install -r requirements-observability.txt
fi
if [ ! -f .env ]; then
  cp "$ROOT/.env.example" .env
fi
.venv/bin/python scripts/migrate.py

cd "$ROOT/apps/web"
if [ ! -f .env.local ]; then
  cp .env.local.example .env.local
fi
npm install --registry=https://registry.npmjs.org

echo "Bootstrap complete. Run scripts/run-api.sh, scripts/run-worker.sh and scripts/run-web.sh in separate terminals."
