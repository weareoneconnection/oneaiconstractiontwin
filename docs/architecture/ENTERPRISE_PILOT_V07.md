# v0.7 Enterprise Pilot Architecture

```text
Users / Enterprise IdP / API Clients
                 |
          JWT / OIDC / API Key
                 |
        FastAPI Enterprise Control Plane
                 |
   +-------------+-------------+
   |             |             |
Project World   AI & Evidence  Distributed Assets
Model           Services       Pipeline
   |             |             |
PostgreSQL      OneAI adapter  Job / Partition / Lease
PostGIS-ready   OneField edge  Redis wake-up
pgvector-ready  Human approval Object storage / Cache
   |             |             |
   +-------------+-------------+
                 |
       GLB / 3D Tiles / Cesium / 4D
                 |
        Project Command Center
```

## Architectural invariants
1. Every business record is scoped to tenant, organization and project where applicable.
2. IFC is an input; Twin Entity is the normalized operational representation.
3. Generated GLB/3D Tiles are rebuildable assets, not the system of record.
4. Important state changes emit events and create audit records.
5. AI claims carry evidence and confidence.
6. Agent recommendations cannot become approved actions without policy and human authority.
7. Database job state is authoritative; Redis is an acceleration channel.
8. Object keys are tenant-scoped.
9. Production startup fails on insecure configuration.
10. Backup validity is established by checksum verification and restore testing.

## Deployment modes
- Local SQLite + local assets for development
- Docker PostgreSQL + Redis + MinIO for team/pilot testing
- Kubernetes + managed PostgreSQL/object storage/Redis for controlled enterprise deployment
