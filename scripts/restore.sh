#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP="${1:?usage: scripts/restore.sh <backup-directory> RESTORE}"
CONFIRM="${2:-}"
if [ "$CONFIRM" != "RESTORE" ]; then
  echo "Restore requires the literal second argument RESTORE" >&2
  exit 1
fi
cd "$ROOT/apps/api"
if [ ! -x .venv/bin/python ]; then
  echo "Run scripts/bootstrap-local.sh first" >&2
  exit 1
fi
exec .venv/bin/python scripts/restore.py "$ROOT/$BACKUP" --confirm RESTORE
