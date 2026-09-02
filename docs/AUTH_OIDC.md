# Authentication: OIDC sign-in

The API validates access tokens; the browser obtains them directly from the identity
provider using **Authorization Code with PKCE**. No client secret exists anywhere in
this system, and the application never handles a user's password.

```
browser ──1. /authorize (PKCE challenge)──▶ identity provider
browser ◀─2. redirect with code───────────  identity provider
browser ──3. /token (code + verifier)─────▶ identity provider
browser ◀─4. access + refresh token────────  identity provider
browser ──5. Authorization: Bearer ───────▶ construction-twin API
                                             └─ validates signature (JWKS),
                                                issuer, audience, expiry,
                                                then maps claims to tenant + role
```

## What the API needs from a token

| Requirement | Detail |
|---|---|
| Signature | RS256 (configurable via `OIDC_ALGORITHMS`), verified against the provider's JWKS |
| `iss` | Must equal `OIDC_ISSUER` |
| `aud` | Must contain `OIDC_AUDIENCE` |
| `exp`, `sub` | Required |
| Tenant scope | `OIDC_TENANT_CLAIM` and `OIDC_ORGANIZATION_CLAIM`, or the `OIDC_DEFAULT_*` fallbacks |
| Role | `role`, `roles`, or Keycloak's `realm_access.roles`; unrecognised roles fall back to `viewer` |

Roles must match the platform's own names, which are the RBAC vocabulary in
`app/core/security.py`:

```
platform_admin  organization_admin  project_director  project_manager
planner  qa_qc  safety  contractor  viewer  ai_agent
```

A token that carries no recognised role is not rejected - it is downgraded to `viewer`.
Failing closed is deliberate: an unfamiliar corporate group must never inherit write
access by accident.

## Keycloak on Railway

> A packaged, verified deployment lives in [`integrations/keycloak/`](../integrations/keycloak/):
> a Dockerfile with the realm baked in, a Railway config, and a README. The realm file
> already contains the audience mapper, the tenant/organization attribute mappers and
> realm roles matching this system's RBAC names — the three things that are easy to miss
> when clicking through the admin console, and that produce silent failures when missed.
> The steps below describe the same setup done by hand.

### 1. Deploy Keycloak

Add a service from the image `quay.io/keycloak/keycloak:26.0` with:

| Setting | Value |
|---|---|
| Start command | `start --hostname-strict=false --http-enabled=true --proxy-headers=xforwarded` |
| `KC_DB` | `postgres` |
| `KC_DB_URL` | `jdbc:postgresql://${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/keycloak` |
| `KC_DB_USERNAME` / `KC_DB_PASSWORD` | reference the Postgres service |
| `KC_BOOTSTRAP_ADMIN_USERNAME` / `KC_BOOTSTRAP_ADMIN_PASSWORD` | your initial admin |
| Public domain | generate one, e.g. `twin-idp.up.railway.app` |

Create the `keycloak` database in the existing Postgres instance first, or attach a
separate Postgres service. Keycloak must not share the application's database schema.

### 2. Realm, client and mappers

In the Keycloak admin console:

1. **Create a realm**, e.g. `oneai`.
2. **Create a client** `construction-twin-web`:
   - Client authentication: **off** (public client - a browser cannot hold a secret)
   - Standard flow: on. Direct access grants: off.
   - Valid redirect URIs: `https://<web-domain>/auth/callback`
   - Valid post logout redirect URIs: `https://<web-domain>`
   - Web origins: `https://<web-domain>`
3. **Audience mapper** (client scopes → `construction-twin-web-dedicated` → Add mapper →
   By configuration → Audience): included client audience `construction-twin-api`, add
   to access token. Without this the API rejects every token, because `aud` will not
   match `OIDC_AUDIENCE`.
4. **Tenant mappers** (same dedicated scope → Add mapper → User Attribute):
   - user attribute `tenant_id` → token claim `tenant_id`, add to access token
   - user attribute `organization_id` → token claim `organization_id`, add to access token

   Then set those attributes on each user. For a single-tenant pilot you can skip the
   mappers and set `OIDC_DEFAULT_TENANT` / `OIDC_DEFAULT_ORGANIZATION` on the API instead.
5. **Realm roles**: create the platform role names you intend to use (`project_manager`,
   `planner`, `viewer`, …) and assign them to users. They arrive in `realm_access.roles`.

### 3. Configure the API

On the `api` and `asset-worker` services:

```bash
AUTH_MODE=oidc
OIDC_ISSUER=https://twin-idp.up.railway.app/realms/oneai
OIDC_AUDIENCE=construction-twin-api
OIDC_CLIENT_ID=construction-twin-web
OIDC_SCOPES=openid profile email
# Only for a single-tenant deployment without the user-attribute mappers:
# OIDC_DEFAULT_TENANT=acme
# OIDC_DEFAULT_ORGANIZATION=acme-hq
```

The browser reads all of this from `GET /api/v1/auth/config`, which also performs OIDC
discovery. Nothing about the provider is hard-coded into the web build.

### 4. Verify before switching off header auth

```bash
curl https://<api-domain>/api/v1/auth/config          # discovered: true
```

Then sign in through the web application and confirm:

```bash
curl https://<api-domain>/api/v1/auth/me -H "Authorization: Bearer <access token>"
```

The response must show the expected `tenant_id`, `organization_id` and `role`. If the
role is `viewer` when you expected more, the realm role name does not match the platform
vocabulary above.

### 5. Switch to production mode

Only once step 4 passes:

```bash
APP_ENV=production
ALLOW_DEV_HEADER_AUTH=false
```

Production also enforces `FORCE_HTTPS=true`, `DEMO_ENDPOINTS_ENABLED=false`, a real
`JWT_SECRET`, non-wildcard CORS and real object-store credentials. The process refuses
to start otherwise - see `docs/DEPLOY_RAILWAY.md`.

## Signing in before an identity provider exists

A deployment running `AUTH_MODE=jwt` with no identity provider has no self-service login:
the sign-in page asks for a token, and `POST /api/v1/auth/dev-token` is disabled whenever
`ALLOW_DEV_HEADER_AUTH=false`. Tokens are therefore minted offline with the deployment's
own secret:

```bash
JWT_SECRET='<the deployment's JWT_SECRET>' python apps/api/scripts/issue_token.py \
  --user maqing --tenant demo-tenant --organization demo-org \
  --role platform_admin --minutes 120 \
  --verify https://<api-domain>
```

`--verify` calls `/auth/me` on that deployment before you paste anything, so a mismatched
secret is caught here rather than at the login screen. The script refuses to sign with the
built-in development secret, because such a token is rejected by every real deployment.

On Railway the secret is the `JWT_SECRET` variable on the `api` service. Treat the
resulting token as a bearer credential: anyone holding it has that role until it expires,
so keep the lifetime short and issue the narrowest role that does the job.

This is a stopgap, not a login system. It is what the deployment has until step 5 below.

## Other providers

Nothing in the API is Keycloak-specific; it uses OIDC discovery and JWKS.

| Provider | Notes |
|---|---|
| Microsoft Entra ID | `OIDC_ISSUER=https://login.microsoftonline.com/<tenant>/v2.0`; expose an API scope and use its application ID URI as `OIDC_AUDIENCE`; map roles via app roles (`roles` claim) |
| Auth0 | Add a rule/action emitting namespaced claims, then set `OIDC_TENANT_CLAIM=https://your-namespace/tenant_id` - namespaced claims containing dots are handled as literal claim names |
| Okta | Use a custom authorization server; `OIDC_AUDIENCE` is that server's audience |

## Session handling in the browser

- Tokens are held in `sessionStorage`: cleared when the tab closes, not shared across
  tabs or subdomains.
- An expired access token is refreshed transparently once per request; if the refresh
  fails the user is sent to `/login` with a return path.
- Sign-out clears local tokens and then calls the provider's `end_session_endpoint`, so
  the session ends at the identity provider too, not only in this application.

**Known limitation.** `sessionStorage` is readable by any script running on the page, so
a cross-site scripting flaw would expose the access token. The hardened alternative is a
backend-for-frontend that holds refresh tokens in `httpOnly` cookies and proxies API
calls. That is a larger architectural change and is not part of this release.

---

# Signed-token sign-in (`auth_mode=jwt`)

A deployment can run with `AUTH_MODE=jwt` and no identity provider. The API then
verifies bearer tokens signed with `JWT_SECRET` — there is no `/authorize` to redirect
to, so the browser cannot obtain a token by itself. `/login` handles this by asking for
one directly: paste a token, and it is checked against `/api/v1/auth/me` before the tab
keeps it.

**This is a pilot path, not a product.** Signing in means holding the deployment's
signing secret, so it works for operators and for nobody else. Anything with real users
needs OIDC, configured as described above.

## Minting a token

```bash
JWT_SECRET='<the deployment secret>' \
  python3 scripts/mint_token.py --role platform_admin --minutes 60
```

The script runs entirely offline: it signs the claims locally and contacts nothing, which
is why it works against a production API that exposes no token endpoint. `--issuer` and
`--audience` default to the API's own defaults; override them if the deployment sets
`JWT_ISSUER` or `JWT_AUDIENCE`, or every token will be rejected as `Invalid audience`.

Print it, paste it into the sign-in box, done. The token lives in `sessionStorage` for
that tab only, and is gone when the tab closes or `exp` passes.

## What this does not weaken

| Property | Why it still holds |
|---|---|
| The API's trust decision is unchanged | `/login` verifies nothing itself; it presents the token to `/auth/me` and believes the answer |
| A token cannot be forged in the browser | Signing needs `JWT_SECRET`, which the web app never receives |
| No anonymous access | `ALLOW_DEV_HEADER_AUTH` stays `false`; an unauthenticated request is still 401 |
| A stolen token expires | `--minutes` bounds it; keep it short |

That last row is the real cost of this path: a token is a bearer credential, so anyone
who reads it over your shoulder is signed in until it expires. Mint short, and do not
paste tokens into chat, tickets or screenshots.

## Why the escape hatch is not `/auth/dev-token`

`POST /api/v1/auth/dev-token` returns 404 whenever `ALLOW_DEV_HEADER_AUTH` is false or
the environment is production — deliberately, because a deployment that will hand a
`platform_admin` token to any anonymous caller is not secured. Re-enabling it to restore
sign-in would reopen exactly that hole. Mint locally instead.
