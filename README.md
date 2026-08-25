# OneAI Construction Twin v0.7.1
## Enterprise Pilot Edition

**AI-Native Digital Twin for Construction & Infrastructure**

> See the project. Understand the project. Predict what happens next. Act before problems happen.

This is the cumulative, runnable codebase for the OneAI Construction Twin Enterprise Pilot. It includes the complete v0.6 distributed digital-twin foundation and adds the enterprise controls required for a governed pilot: database migrations, multi-tenant authorization, OIDC/JWT readiness, audit, readiness checks, backup/restore, security defaults, operational monitoring and an end-to-end pilot runbook.

## What is included

### Digital-twin and project intelligence
- Project World Model and Twin Entities
- IFC semantic ingestion with IfcOpenShell support and a transparent STEP fallback parser
- IFC geometry, Three.js visualization and entity selection
- IFC to GLB and 3D Tiles 1.1 asset generation
- LOD0 / LOD1 / LOD2 and Cesium spatial streaming
- Distributed asset jobs, partitions, worker leases, cancel/resume and content-addressed cache
- Schedule CSV import and BIM-to-schedule mapping
- 4D baseline / actual / forecast timeline
- Evidence-first Ask Twin: BM25 retrieval over project records, derived claims, and an
  enforced provisional downgrade when nothing matches
- Risk evaluation and P10/P50/P90 forecast computed from measured activity slippage,
  each reporting its model, sample size and calibration state
- What-if simulation with its assumption set returned in full
- Agent recommendations grounded in the current schedule, human approval, and a
  hash-chained, verifiable audit trail

### Enterprise Pilot controls
- Alembic database migration baseline
- Tenant, organization and project data scoping
- Role-based access control for human and AI-agent identities
- Local JWT, API key and OIDC-ready authentication modes
- Upload type, size, filename and checksum validation
- Request IDs, security headers and rate limiting
- `/health`, `/health/ready`, `/ready`, `/metrics` and worker heartbeat state
- Local or S3/MinIO object storage
- PostgreSQL/SQLite and object-store backup, verification and restore utilities
- Structured logs, Prometheus metrics and optional OpenTelemetry export
- Docker Compose, Kubernetes, HPA, PDB and network-policy references
- Enterprise pilot status, checklist and E2E validation script

### Web application
- Routed workspace: portfolio, project overview, BIM & 3D, schedule & 4D, intelligence,
  audit trail, platform administration
- OIDC sign-in with PKCE, session refresh and provider sign-out
- Permission-aware controls driven by the API's own `/auth/me` response
- Loading, empty and error states throughout; provenance shown beside every AI-derived number

### Hardening added in v0.7.1
- Authenticated, tenant-scoped delivery of every generated asset (no static mount)
- Hash-chained audit records with a verification endpoint
- Rate limiting keyed on a stable credential fingerprint, per caller
- Explicit AI provenance on every response (`reasoning.model_backed`)
- 31 automated tests running against an isolated database

Read `RELEASE_NOTES_V071.md` for the full list.

## Version lineage

| Version | Cumulative capability |
|---|---|
| v0.1 | M12 backend and domain foundation |
| v0.2 | Product UI, Twin Viewer and complete read APIs |
| v0.3 | IFC semantics and BIM-to-schedule mapping |
| v0.4 | IFC geometry and 4D construction timeline |
| v0.5 | GLB, 3D Tiles, LOD and Cesium streaming |
| v0.6 | Durable distributed asset pipeline and object storage |
| v0.7 | Enterprise Pilot hardening, security, migrations, recovery and operations |
| **v0.7.1** | **Security, evidence-integrity and provenance fixes; verified build and test suite** |

## Quick start: local development

Requirements:
- Python 3.12 recommended
- Node.js 20.9+ (22 recommended)
- npm 10+

### 1. API

```bash
cd apps/api
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
# Optional: full IFC semantic/geometry support
python -m pip install -r requirements-ifc.txt
python -m uvicorn app.main:app --reload
```

API documentation: `http://127.0.0.1:8000/docs`

### 2. Asset worker

```bash
cd apps/api
source .venv/bin/activate
python -m app.workers.asset_worker
```

### 3. Web application

```bash
cd apps/web
cp .env.local.example .env.local
npm install --registry=https://registry.npmjs.org
npm run dev
```

Web application: `http://localhost:3000`

### 4. Test and demo flow

```bash
cd ../..
PYTHONPATH=apps/api python -m pytest -q

curl -X POST http://127.0.0.1:8000/api/v1/demo/seed \
  -H 'X-Tenant-ID: demo-tenant' \
  -H 'X-Organization-ID: demo-org' \
  -H 'X-User-ID: demo-user' \
  -H 'X-Role: platform_admin'
```

Run the live pilot chain after API and worker are online:

```bash
python scripts/e2e_pilot.py
```

## Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

Scale the conversion pipeline:

```bash
docker compose up --build --scale asset-worker=3
```

Enable monitoring:

```bash
docker compose --profile monitoring up --build
```

For the production-oriented override, read `RUN_ENTERPRISE_V07.md` and `docs/DEPLOYMENT.md` first. Production mode intentionally rejects insecure defaults.

## Initial pilot scope

The recommended first pilot is **Steel Structure Schedule Intelligence**:

```text
IFC + Baseline Schedule + Daily Reports + Photos + RFI/NCR + Inspections
  -> Actual vs Planned
  -> Delay Cause with Evidence
  -> Downstream Impact
  -> P10/P50/P90 Forecast
  -> Mitigation Scenarios
  -> Human-approved Actions
  -> Audit Trail
```

## Evidence policy

> **No AI conclusion without evidence.**

Ask Twin responses carry answer, confidence, claims, ranked evidence, recommended
actions and provenance. The policy is enforced in code, not only stated: when no project
record matches the question the response is returned with `provisional: true`, confidence
capped at 0.4, and text saying it must not be used for a contractual decision.

Every AI response also reports how it was produced. With no `ONEAI_CORE_URL` configured,
answers are composed by a local deterministic reasoner and are labelled
`reasoning.model_backed: false` / `mode: "demonstrative-local"` - in the payload, in the
answer text and in the dashboard. Risk and forecast results carry `calibrated: false`
together with the sample they were computed from.

## Documentation

- `RUN_ENTERPRISE_V07.md` - complete startup and validation procedure
- `docs/architecture/ENTERPRISE_PILOT_V07.md` - system architecture
- `docs/DEPLOYMENT.md` - local, Docker and Kubernetes deployment
- `docs/DEPLOY_RAILWAY.md` - hosted deployment on Railway (api, asset-worker, web, Postgres, Redis, S3)
- `docs/SECURITY.md` - authentication, authorization and production controls
- `docs/AUTH_OIDC.md` - browser sign-in, Keycloak setup and the switch to production mode
- `docs/BACKUP_RESTORE.md` - backup and restore operations
- `docs/PILOT_RUNBOOK.md` - first enterprise pilot workflow
- `docs/DATA_MODEL.md` - Project World Model and enterprise records
- `docs/API_REFERENCE.md` - primary API groups
- `docs/E2E_TEST_PLAN.md` - end-to-end release gate
- `docs/KNOWN_LIMITATIONS.md` - explicit product boundaries
- `RELEASE_NOTES_V071.md` - the v0.7.1 hardening pass
- `TEST_REPORT_V07.md` - what was actually validated, and what was not

## Release boundary

v0.7.1 is an **Enterprise Pilot baseline**, not a claim of general-availability production maturity. Before a live customer deployment, the operator must configure a real identity provider, production secrets, HTTPS, database/object-store backups, monitored workers, data residency, customer-specific access rules and a tested recovery procedure.

See `docs/KNOWN_LIMITATIONS.md` for the precise boundaries.
