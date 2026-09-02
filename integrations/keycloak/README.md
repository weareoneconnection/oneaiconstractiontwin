# Keycloak for the Construction Twin

The twin validates tokens; it does not issue them. This directory is the identity
provider that does, packaged so the realm arrives configured rather than clicked
together by hand.

## Why the realm is a file

The realm defines one thing that is easy to miss and fatal to omit: an **audience
mapper** putting `construction-twin-api` into every access token's `aud`. Without it
Keycloak issues tokens that look perfectly valid and the API rejects every one of them,
with nothing in the Keycloak UI suggesting anything is wrong. The file also carries the
tenant and organization attribute mappers, and realm roles whose names match the twin's
own RBAC vocabulary — `platform_admin`, `project_manager`, `planner`, `viewer` and the
rest. A role Keycloak issues that the twin does not recognise is not an error; the user
is quietly downgraded to `viewer`, which is safe but confusing, so the names are aligned
here instead.

## Verified locally

The whole chain was run before this was written, against Keycloak 26.0.8:

| Step | Result |
|---|---|
| Realm import | `Realm 'oneai' imported` |
| Token claims | `aud: construction-twin-api`, `tenant_id`, `organization_id`, `realm_access.roles` |
| `GET /api/v1/auth/me` with that token | `auth_source: oidc`, correct tenant, organization and role |
| Browser sign-in (PKCE) | Sign-in page → Keycloak → callback → dashboard, with `ALLOW_DEV_HEADER_AUTH=false` |
| Sign-out | Local session cleared and the session ended at Keycloak |
| `APP_ENV=production` | Configuration validator passes |

## Deploying on Railway

**1. A database.** Keycloak must not share the twin's schema. Add a second Postgres
service, or create a separate `keycloak` database on the existing one.

**2. The service.**

| Setting | Value |
|---|---|
| Source | this repository |
| Config as code path | `integrations/keycloak/railway.json` |
| Public domain | generate one, e.g. `twin-idp.up.railway.app` |

Variables:

```bash
KC_DB=postgres
KC_DB_URL=jdbc:postgresql://${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/keycloak
KC_DB_USERNAME=${{Postgres.PGUSER}}
KC_DB_PASSWORD=${{Postgres.PGPASSWORD}}
KC_HOSTNAME=https://twin-idp.up.railway.app
KC_PROXY_HEADERS=xforwarded
KC_HTTP_ENABLED=true
KC_BOOTSTRAP_ADMIN_USERNAME=<your admin>
KC_BOOTSTRAP_ADMIN_PASSWORD=<a strong password>

# Bound into the realm's redirect URIs at startup. Without it Keycloak refuses the
# browser sign-in with "Invalid parameter: redirect_uri" and nothing else.
WEB_ORIGIN=https://<your web domain>
```

The healthcheck is `/realms/oneai` rather than `/health`: Keycloak 26 serves health on a
separate management port that Railway cannot reach, and the realm endpoint proves more
anyway — that the realm actually imported.

**3. First login.** Sign in to `https://twin-idp.up.railway.app/admin` with the bootstrap
credentials. The realm ships two users, `pilot.admin` and `pilot.planner`, with temporary
passwords that must be changed on first use. Set each user's `tenant_id` and
`organization_id` attributes to the values that deployment uses — the realm's defaults are
`demo-tenant` / `demo-org`.

**4. Point the twin at it** (`api` service):

```bash
AUTH_MODE=oidc
OIDC_ISSUER=https://twin-idp.up.railway.app/realms/oneai
OIDC_AUDIENCE=construction-twin-api
OIDC_CLIENT_ID=construction-twin-web
```

The web application needs no rebuild: it reads all of this from `/api/v1/auth/config` at
runtime, and the sign-in page changes from a token box to "Sign in with your organization
account" on its own.

**5. Verify before locking the door.**

```bash
curl https://<api-domain>/api/v1/auth/config     # oidc.discovered must be true
```

Then sign in through the web application and confirm the identity chip shows the expected
role and organization. Only then:

```bash
APP_ENV=production
ALLOW_DEV_HEADER_AUTH=false
```

Production also requires `FORCE_HTTPS=true`, `DEMO_ENDPOINTS_ENABLED=false`, a real
`JWT_SECRET`, non-wildcard CORS and real object-store credentials. The process refuses to
start otherwise, which is the intended behaviour.

## Adding real users

Each user needs `tenant_id` and `organization_id` attributes and one realm role. A user
without the tenant attributes is refused by the API with a message naming exactly which
claims are missing — the twin will not guess a tenant, because guessing one would put a
person inside another customer's data.

For a single-tenant deployment the attributes can be skipped entirely by setting
`OIDC_DEFAULT_TENANT` and `OIDC_DEFAULT_ORGANIZATION` on the API instead.

## What this is not

A production identity deployment needs more than this file: password policy, brute-force
detection, session limits, email for password reset, a backup of the Keycloak database,
and either an HA setup or an accepted single point of failure. This gets sign-in working
correctly; it does not make Keycloak an operated service.
