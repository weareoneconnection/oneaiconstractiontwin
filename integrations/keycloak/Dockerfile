# Keycloak for the Construction Twin, with the realm baked in.
#
# The realm is imported from a file rather than clicked together in the admin console.
# That matters for one reason above the others: the audience mapper. Without it every
# token Keycloak issues carries the wrong `aud` and the API rejects all of them, with
# nothing in the Keycloak UI to suggest anything is wrong. A file cannot forget it.
FROM quay.io/keycloak/keycloak:26.0

COPY realm-construction-twin.json /opt/keycloak/data/import/realm.json
COPY entrypoint.sh /opt/keycloak/entrypoint.sh

USER root
# The entrypoint rewrites the realm's redirect URIs in place, so the import directory has
# to be writable by the runtime user rather than only by root.
RUN chmod +x /opt/keycloak/entrypoint.sh \
    && chown -R keycloak:keycloak /opt/keycloak/data/import
USER keycloak

ENV KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true \
    KC_HTTP_ENABLED=true \
    KC_PROXY_HEADERS=xforwarded \
    KC_HOSTNAME_STRICT=false

ENTRYPOINT ["/opt/keycloak/entrypoint.sh"]
