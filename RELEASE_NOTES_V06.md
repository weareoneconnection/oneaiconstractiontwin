# OneAI Construction Twin Alpha v0.6 Release Notes

## Added

- Durable `AssetBuildJob`, `AssetBuildPartition`, cache and event models
- Redis worker wake-up with database-backed source of truth
- Multi-process asset worker entrypoint
- Resumable partition planning, leases, cancellation and resume
- Local / S3 / MinIO object storage abstraction
- IFC source persistence to object storage
- Content-addressed output cache and active request de-duplication
- Async asset-job REST APIs and SSE events
- Optional Meshopt / Draco adapter via `gltf-transform`
- Distributed pipeline UI with progress, partitions, events and cache status
- Docker Compose asset worker and worker scaling
- Kubernetes worker deployment and HPA scaffold
- Prometheus asset pipeline metrics

## Preserved

All M12, v0.2, v0.3, v0.4 and v0.5 domain, API, IFC, schedule, evidence, intelligence, 4D, GLB, 3D Tiles and Cesium functionality remains included.

## Validation

- Python compile check passed
- OpenAPI generation passed (41 paths)
- Backend tests: 6 passed
- Docker Compose YAML parsed successfully

## Known production boundaries

See `README.md`, `README_CN.md` and `docs/architecture/ALPHA_V06.md` for required enterprise hardening.
