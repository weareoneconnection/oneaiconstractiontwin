#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/apps/web"
if [ ! -d node_modules ]; then
  npm install --registry=https://registry.npmjs.org
fi
exec npm run dev
