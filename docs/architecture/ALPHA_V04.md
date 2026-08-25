# OneAI Construction Twin Alpha v0.4

## Scope

v0.4 extends the complete v0.3 codebase with the first real geometry + 4D execution loop.

### Geometry pipeline

`IFC -> semantic TwinEntity -> IfcOpenShell geometry (when available) -> triangulated mesh API -> Three.js viewer`

If native geometry is unavailable, the API returns explicitly labelled semantic proxy boxes. This preserves product operation without pretending proxy geometry is exact IFC geometry.

### 4D pipeline

`Schedule Activity -> BIM mapping -> timeline date -> entity construction state -> viewer color/state -> project summary`

States:
- Future
- Planned
- In Progress
- Delayed
- Completed

### New endpoints

- `GET /api/v1/projects/{project_id}/bim/models/{document_id}/geometry`
- `GET /api/v1/projects/{project_id}/timeline`
- `GET /api/v1/projects/{project_id}/timeline/state?at=YYYY-MM-DD`

### Frontend

- Exact/proxy geometry rendering with Three.js BufferGeometry
- OrbitControls
- Entity click selection
- 4D date slider
- Animated timeline playback
- State-based construction coloring
- Timeline summary

## Production boundary

v0.4 triangulates IFC geometry through IfcOpenShell when the native geometry dependency is available. It does not yet implement a production GLB/3D Tiles preprocessing farm, LOD hierarchy, spatial streaming, or Cesium tiling. Those are the v0.5 scale targets.
