# OneAI Construction Twin v0.7.0 Release Notes

## Edition
Enterprise Pilot Edition

## Upgrade model
v0.7 is a cumulative release built directly on the full v0.6 codebase. No v0.6 digital-twin, IFC, 4D, Cesium or distributed-pipeline capability was intentionally removed.

## Enterprise additions
- Alembic migration baseline and migration readiness check
- JWT, API key and OIDC-ready authentication
- RBAC and tenant/organization/project isolation
- File upload validation and SHA256 provenance
- Security headers, request IDs and rate limits
- Live, ready and metrics endpoints
- Worker heartbeat and readiness integration
- Backup, checksum verification, restore and retention tooling
- Structured logging, Prometheus and optional OpenTelemetry
- Pilot status, pilot checklist and enterprise E2E script
- Production-oriented Docker and Kubernetes reference manifests
- Enterprise documentation and explicit limitations

## Compatibility
- Existing v0.6 API groups are preserved under `/api/v1`.
- The current Alembic baseline is designed to stamp an existing compatible v0.6 database without dropping tables.
- Operators must back up data before applying migrations.

## Release boundary
This release is intended for controlled enterprise pilots. General availability requires evidence from a real external customer deployment, sustained operation, measured performance, verified recovery and customer-specific security approval.
