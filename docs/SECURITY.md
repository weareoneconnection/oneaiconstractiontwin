# Security Model

## Identity
Supported modes:
- Local JWT for development and controlled pilot utilities
- API key records stored as SHA256 key hashes
- OIDC discovery/JWKS validation for enterprise identity providers
- Hybrid mode for development migration only

Production should use OIDC, disable development header authentication and rotate all secrets.

## Authorization
RBAC roles include platform admin, organization admin, project director, project manager, planner, QA/QC, safety, contractor, viewer and AI agent. API services enforce tenant and organization scope in database queries.

## Data boundaries
- Every project-domain record carries tenant and organization scope.
- Asset objects use a tenant-prefixed key.
- Cross-tenant project and asset access is rejected.
- Upload paths use safe filenames and tenant/project directories.

### Generated asset delivery
Generated tilesets and GLB payloads are served **only** through authenticated,
tenant-scoped endpoints:

- `GET /api/v1/asset-objects/{key}` - object-store payloads
- `GET /api/v1/generated-assets/{path}` - local pipeline output

Both require `twin:read` and reject any key whose first segment is not the caller's
tenant. There is no static file mount for generated assets. A browser client that
renders the tileset (Cesium) must attach the same credentials to its own tile
requests; the reference implementation does this with a `Cesium.Resource`.

## Audit integrity
Audit entries are append-only and hash-chained per tenant: each record stores the
SHA-256 hash of the previous entry, and `GET /api/v1/admin/audit/verify` recomputes
the chain and reports the first break. Editing or deleting a record is therefore
detectable. This is integrity evidence, not prevention: an operator with direct
database access can still rewrite history, but no longer silently. Entries written
before v0.7.1 are reported separately as `legacy_unchained_entries`.

## Rate limiting
The quota is keyed on the caller's credential (SHA-256 fingerprint) or client
address, across all endpoints. `X-Forwarded-For` is honoured only when
`TRUST_FORWARDED_FOR=true`, which must be set only when the API genuinely runs
behind a trusted proxy - otherwise any client can rotate the header to reset its
own quota.

## HTTP controls
- Trusted hosts
- Explicit CORS
- HTTPS redirect in production
- Request ID
- Security response headers
- Rate limiting
- Upload allowlist and maximum size

## Pilot operator responsibilities
- Confirm data classification and residency.
- Configure retention and deletion policies.
- Restrict project roles to least privilege.
- Validate subcontractor access.
- Keep secrets in Vault/KMS or the cloud secret manager.
- Run dependency, container and infrastructure scans.
- Obtain customer approval before processing personal or sensitive project data.

## Current limitation
This package is OIDC-ready but does not include a hosted identity provider. Keycloak, Microsoft Entra ID, Auth0 or another customer-approved provider must be configured by the operator.
