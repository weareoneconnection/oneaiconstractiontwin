# v0.7.0 Release Notes

## Edition

Enterprise Pilot Edition

## Inherits

All cumulative v0.1-v0.6 features: domain API, product UI, IFC semantics, schedule mapping, geometry, 4D, GLB/3D Tiles/LOD/Cesium and distributed asset processing.

## Adds

- Alembic baseline and migration head enforcement
- local JWT, OIDC-ready and API-key authentication
- enterprise roles, permissions and tenant isolation tests
- readiness checks for database, migrations, Redis, object storage, workers and OneAI Core
- worker heartbeat registry
- secure production configuration validation
- request IDs, rate limiting and HTTP security headers
- backup, verification and restore tools
- enterprise readiness UI
- Prometheus/Grafana references and optional OpenTelemetry
- Kubernetes migration job, probes, PDB, HPA and NetworkPolicy references
- enterprise pilot status/checklist APIs
- v0.7 E2E tests and operational documentation

## Validation result

Backend cumulative suite: 8 passed.
