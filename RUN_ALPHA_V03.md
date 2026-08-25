# OneAI Construction Twin Alpha v0.3 — Run

v0.3 includes the complete v0.2 codebase plus IFC semantic ingestion, Twin Entity auto-generation, schedule CSV import, and BIM↔Schedule auto-mapping.

## Backend
```bash
cd apps/api
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
# Optional full IFC parser (recommended):
python -m pip install -r requirements-ifc.txt
python -m uvicorn app.main:app --reload
```

## Tests
From repository root with the API venv activated:
```bash
python -m pytest -q
```

## Frontend
```bash
cd apps/web
npm install --registry=https://registry.npmjs.org
npm run dev
```
Open http://localhost:3000

## Demo v0.3
1. `POST /api/v1/demo/seed`
2. Import `data/demo_minimal.ifc` in the v0.3 workspace.
3. Import `data/demo_schedule.csv`.
4. Click **Auto Map**.

## IFC modes
- With `ifcopenshell`: semantic parsing, product types, property sets, building-storey containment where available.
- Without `ifcopenshell`: safe STEP-text fallback that creates Twin Entities from common IFC product records. This is intentionally a fallback, not a production geometry converter.

## Geometry boundary
v0.3 implements IFC semantic ingestion and the BIM↔Schedule intelligence layer. Production tessellation to glTF/3D Tiles remains an adapter boundary for IfcOpenShell geometry / IfcConvert / That Open Engine pipelines; the viewer continues to render an interactive entity-based twin surface until a geometry asset is attached.
