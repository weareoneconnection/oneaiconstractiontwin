# Validation Report - v0.7.1

Environment actually used for this run:

- macOS (darwin 25.5.0), Python 3.12.13 in `apps/api/.venv`, Node 20.19.6, npm 11.15.0
- SQLite database and local object storage, isolated per test run
- API, asset worker and web application all started and exercised together

## Automated tests

`PYTHONPATH=apps/api apps/api/.venv/bin/python -m pytest -q tests` - **31 passed**

| Suite | Tests | Covers |
|---|---|---|
| `test_api.py` | 2 | health, demo flow, Ask Twin |
| `test_v03.py` - `test_v05.py` | 3 | IFC semantics, 4D timeline, 3D Tiles/LOD |
| `test_v06.py` | 1 | distributed job, partitions, object storage, cache hit, cancel, resume |
| `test_v07.py` | 2 | auth modes, tenant isolation, readiness, backup/restore round trip |
| `test_v071_hardening.py` | 23 | the defects fixed in this release (below) |

The suite now runs against a temporary database and storage roots created per run
(`tests/conftest.py`). Before this release it wrote into the developer's own
`construction_twin.db`, so results depended on previous runs.

## Live end-to-end chain

`python scripts/e2e_pilot.py` against a running API + asset worker - **29 checks passed**,
pilot readiness score 100.0. The script now also gates on:

- an unmatched question being downgraded to provisional with no evidence
- forecast percentiles being ordered and derived from the schedule
- risk output declaring its model and sample
- every audit entry being hash-chained, and the chain verifying
- `/assets/...` returning 404 (no unauthenticated static mount)
- cross-tenant generated-asset access returning 403

## Web application

- `npm install` - 0 vulnerabilities (Next upgraded to 16.3.2; 15.x pins a postcss
  release with four open advisories)
- `npm run build` - **succeeds**. This had never completed before: Cesium 1.132 floats
  onto `@cesium/widgets` 13.2.1, which drags in a second incompatible `@cesium/engine`,
  and the two require different `@zip.js/zip.js` subpaths. Both are now pinned via
  `overrides`.
- Browser verification against the live API: dashboard renders, Ask Twin returns ranked
  evidence with provenance, the distributed asset build completes, and the Cesium
  viewer streams authenticated 3D Tiles.

## Defects found by review and fixed in v0.7.1

1. Generated assets were served by an unauthenticated `/assets` static mount, exposing
   every tenant's model geometry to anyone who could guess a path.
2. Cesium fetched tiles without credentials, so the authenticated object endpoint could
   never actually load in the browser.
3. Ask Twin attached the first five evidence rows of the project to every answer, and
   asserted one hard-coded claim; `ai_evidence_coverage` was therefore a constant.
4. The AI adapter returned one fixed sentence with a fixed 0.89 confidence, presented as
   a model result.
5. The forecast sampled a Gaussian unrelated to the schedule; the risk engine used two
   fixed linear formulas; the agent returned one constant recommendation.
6. The rate-limit key trusted `X-Forwarded-For` unconditionally, used the randomised
   built-in `hash()`, and included the request path, multiplying the effective quota by
   the number of endpoints.
7. Audit records were described as immutable but were ordinary mutable rows.
8. Partition planning loaded every entity of a model into memory.
9. `scripts/migrate.py`, `backup.py` and `restore.py` failed with `ModuleNotFoundError`
   when run as documented.
10. `demo/seed` created a duplicate project on every call, and the dashboard opened an
    arbitrary one.
11. `APP_VERSION` was duplicated across five config files and drifted from the code.
12. `viewer.zoomTo(tileset)` framed the model half out of view.

## Not covered by this run

- PostgreSQL, MinIO/S3 and Redis-backed deployments (SQLite and local storage were used)
- Docker image build and Kubernetes manifests (Docker daemon unavailable on this host)
- OIDC against a real identity provider
- Load, soak and availability testing; the pilot SLO figures remain untested targets
- Real customer IFC models and large-model performance
