# Run Construction Twin Alpha v0.4

v0.4 contains all v0.1, v0.2 and v0.3 capabilities plus IFC geometry and the 4D construction timeline.

## 1. Backend

```bash
cd apps/api
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Recommended for exact IFC geometry:

```bash
python -m pip install -r requirements-ifc.txt
```

Start:

```bash
python -m uvicorn app.main:app --reload
```

## 2. Tests

From repository root with the API venv active:

```bash
python -m pytest -q
```

## 3. Frontend

```bash
cd apps/web
npm install --registry=https://registry.npmjs.org
npm run dev
```

Open `http://localhost:3000`.

## 4. Demo flow

1. Seed the demo project or let the UI do it automatically.
2. Import `data/demo_minimal.ifc` in the BIM/Schedule Workspace.
3. Import `data/demo_schedule.csv`.
4. Click **Auto Map**.
5. The v0.4 workspace loads the IFC model geometry.
6. Drag the 4D date slider or press **Play 4D**.
7. Click geometry to select the linked Twin Entity.

## Geometry modes

- `ifc-exact`: all returned meshes were triangulated from IFC geometry.
- `hybrid`: some IFC objects were triangulated and some use proxy geometry.
- `semantic-proxy`: native IFC geometry is unavailable; entity-linked deterministic boxes are shown and explicitly labelled as proxy geometry.

For enterprise pilots, install IfcOpenShell geometry support and move large models to the future GLB/3D Tiles preprocessing pipeline.
