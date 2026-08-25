#!/bin/sh
set -eu
API_URL="${API_URL:-http://127.0.0.1:8000}"
curl -sS -X POST "$API_URL/api/v1/auth/dev-token" \
  -H 'Content-Type: application/json' \
  -d "{\"user_id\":\"${USER_ID:-pilot-admin}\",\"tenant_id\":\"${TENANT_ID:-demo-tenant}\",\"organization_id\":\"${ORGANIZATION_ID:-demo-org}\",\"role\":\"${ROLE:-project_director}\"}"
printf '\n'
