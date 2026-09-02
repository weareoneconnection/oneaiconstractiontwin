#!/bin/sh
set -eu

# The realm ships with a placeholder for the web application's origin, because redirect
# URIs and web origins are deployment-specific and a wrong value fails at login time with
# an opaque "Invalid parameter: redirect_uri". Substituting here keeps the committed file
# free of any one environment's domains.
if [ -n "${WEB_ORIGIN:-}" ]; then
  sed -i "s|https://REPLACE-WEB-DOMAIN|${WEB_ORIGIN}|g" /opt/keycloak/data/import/realm.json
  echo "[keycloak] realm redirect URIs bound to ${WEB_ORIGIN}"
else
  echo "[keycloak] WEB_ORIGIN is not set; the realm keeps its placeholder origin and browser sign-in will be refused by Keycloak." >&2
fi

exec /opt/keycloak/bin/kc.sh start "$@"
