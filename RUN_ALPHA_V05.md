# OneAI Construction Twin Alpha v0.5

v0.5 fully contains v0.4, v0.3, v0.2 and the original M12 foundation.

## What v0.5 adds

- IFC geometry -> glTF 2.0 binary GLB asset pipeline
- 3D Tiles 1.1 tileset generation
- Three-level LOD hierarchy (LOD0 / LOD1 / LOD2)
- Per-entity spatial tiles and bounding volumes
- Static asset streaming endpoint
- Bounding-box spatial query API
- CesiumJS large-model viewer
- Configurable georeference origin
- Existing v0.4 4D timeline remains available

The generator works with exact IfcOpenShell geometry when available. When the source geometry is semantic-proxy, generated assets remain explicitly traceable to that source mode.

## Backend

```bash
cd apps/api
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-ifc.txt
python -m uvicorn app.main:app --reload
```

## Tests

From repository root:

```bash
python -m pytest -q
```

## Frontend

```bash
cd apps/web
npm install --registry=https://registry.npmjs.org
npm run dev
```

`npm install` runs a postinstall script that copies Cesium Workers / Assets / Widgets into `public/cesium` for local runtime use.

Open http://localhost:3000

## Product flow

1. Import `data/demo_minimal.ifc`
2. Import `data/demo_schedule.csv`
3. Auto Map BIM <-> Schedule
4. Build Streaming Assets
5. View 3D Tiles in Cesium
6. Use the existing 4D workspace to play schedule state over time

## v0.5 APIs

```text
POST /api/v1/projects/{project_id}/bim/models/{document_id}/assets/build
GET  /api/v1/projects/{project_id}/bim/models/{document_id}/assets
GET  /api/v1/projects/{project_id}/bim/models/{document_id}/spatial-stream
GET  /assets/{tenant}/{project}/{document}/tileset.json
```

## Production boundary

This is an enterprise-oriented alpha foundation, not a final city-scale preprocessing farm. GLB / 3D Tiles generation currently runs in-process. For very large railway / airport / city models, move conversion into asynchronous workers with object storage, distributed queues, content-addressed caching and optional Draco / Meshopt compression.
