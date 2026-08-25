# Deployment

> For a hosted deployment on Railway (four services, managed Postgres/Redis and an
> S3-compatible object store) follow `docs/DEPLOY_RAILWAY.md` instead of this document.

## Local
Use SQLite and local asset storage. Development header authentication is enabled only outside production. See `RUN_ENTERPRISE_V07.md`.

## Docker Pilot
The default Compose stack contains PostgreSQL, Redis, MinIO, API, scalable asset workers and Web. Prometheus/Grafana are optional via the `monitoring` profile.

## Kubernetes Pilot
Reference manifests are in `infra/k8s/` and include API, worker, HPA, migration job, PDB, service account and network policy. They are templates; replace images, storage classes, ingress, secrets, resource requests and identity-provider values for the target environment.

## Release sequence
1. Back up database and object storage.
2. Verify the backup checksum.
3. Build immutable API/Web images.
4. Run Alembic migration job.
5. Deploy API and workers.
6. Confirm `/health/ready` and worker heartbeat.
7. Run E2E pilot validation.
8. Enable customer traffic.

## Required production services
- PostgreSQL 16+
- Redis 7+
- S3-compatible object storage
- HTTPS ingress/load balancer
- OIDC identity provider
- Prometheus-compatible monitoring
- Central logs and incident alerting

## Production environment rules
- `APP_ENV=production`
- `ALLOW_DEV_HEADER_AUTH=false`
- `DEMO_ENDPOINTS_ENABLED=false`
- `FORCE_HTTPS=true`
- Real OIDC issuer/audience/JWKS
- Unique JWT and storage secrets
- Explicit CORS origins and trusted hosts
- `REQUIRE_ASSET_WORKER=true`
- Migration at head before readiness succeeds
