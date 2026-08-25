# Run OneAI Construction Twin Alpha v0.6

## Local mode

Terminal 1 — API:

```bash
cd apps/api
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-ifc.txt   # optional exact geometry
python -m uvicorn app.main:app --reload
```

Terminal 2 — asset worker:

```bash
cd apps/api
source .venv/bin/activate
python -m app.workers.asset_worker
```

Terminal 3 — web:

```bash
cd apps/web
npm install --registry=https://registry.npmjs.org
npm run dev
```

Open http://localhost:3000.

## API-only demo

Seed project:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/demo/seed
```

Import IFC in Swagger or with curl, then create a job:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/projects/PROJECT_ID/bim/models/DOCUMENT_ID/asset-jobs \
  -H 'Content-Type: application/json' \
  -d '{"partition_max_entities":2,"compression":"none","force_rebuild":true}'
```

Inspect:

```bash
curl http://127.0.0.1:8000/api/v1/asset-jobs/JOB_ID
curl http://127.0.0.1:8000/api/v1/asset-jobs/JOB_ID/events
curl http://127.0.0.1:8000/api/v1/asset-jobs/JOB_ID/manifest
```

Cancel / resume:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/asset-jobs/JOB_ID/cancel
curl -X POST http://127.0.0.1:8000/api/v1/asset-jobs/JOB_ID/resume
```

## Docker / MinIO mode

```bash
docker compose up --build --scale asset-worker=3
```

The API uploads source IFC files to MinIO. Workers download/materialize them independently, generate partitioned assets and upload content-addressed output objects back to MinIO.

## Optional compression

Install a `gltf-transform` executable and set:

```bash
export GLTF_TRANSFORM_BIN=gltf-transform
```

Then select `auto`, `meshopt` or `draco` in the UI or API request. Without the optional executable, the build remains valid and the manifest records that no compression was applied.
