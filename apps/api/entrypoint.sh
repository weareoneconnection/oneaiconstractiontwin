#!/bin/sh
set -eu

if [ "${AUTO_MIGRATE:-false}" = "true" ]; then
  python -c "from app.services.migrations import upgrade_to_head; upgrade_to_head()"
fi

exec "$@"
