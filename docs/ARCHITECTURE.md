# Architecture

## System layers

```text
Physical Project
  -> IFC / BIM / schedule / documents / photos / evidence
  -> Ingestion and normalization
  -> Project World Model / Twin Entity / Twin Graph
  -> Geometry and distributed asset pipeline
  -> GLB / 3D Tiles / LOD / Cesium / 4D timeline
  -> Evidence-first intelligence
  -> Risk / Forecast / Simulation / Agent recommendation
  -> Human approval / Action / Audit / Memory
```

## Runtime components

- **Web**: Next.js, Three.js and Cesium user experience.
- **API control plane**: FastAPI, domain services, auth, RBAC, readiness and audit.
- **PostgreSQL/SQLite**: authoritative transactional and job state.
- **Redis**: low-latency worker signalling and distributed rate limiting. The database remains the durable queue.
- **Object storage**: IFC sources and generated GLB/3D Tiles in local storage, S3 or MinIO.
- **Asset Worker**: partition planning, conversion, compression, finalization and lease recovery.
- **OneAI boundaries**: OneAI Core, OneForge, OneField and OneClaw adapters remain explicit integration points.

## Architectural invariants

1. Every meaningful project object is represented as a Twin Entity or domain entity.
2. Important state changes emit events and enter the audit trail.
3. AI claims must be linked to evidence.
4. Agent actions are permissioned and human-governed.
5. Generated geometry is reproducible; domain data remains authoritative.
6. Tenant, organization and project scopes are enforced at service/query boundaries.
7. Long-running asset work is durable, resumable and content-addressed.

## v0.7 scope

v0.7 freezes the cumulative v0.6 architecture and adds enterprise-pilot controls. Future feature work should not bypass these invariants or create a second data model.
