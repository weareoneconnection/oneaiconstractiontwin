# Construction Twin Alpha v0.2

## What is runnable now
- FastAPI project/twin/evidence/risk/forecast/simulation/agent APIs
- Complete read-model endpoints for project, entity, activities, evidence, risks, graph and actions
- BIM file upload adapter boundary (IFC/GLB/GLTF/JSON)
- Next.js Command Center UI
- Interactive Three.js steel-frame twin surface
- Entity intelligence panel
- Evidence-first Ask Twin
- Risk scan, probabilistic forecast, scenario simulation and project-director agent controls

## Deliberately isolated production adapters
The Alpha does not pretend to implement production IFC semantic extraction, Cesium 3D Tiles conversion, Primavera P6 native APIs, enterprise SSO, or production CV inference. Those are kept behind explicit adapter boundaries so they can be replaced without rewriting the domain model or UI.

## Next production adapters
1. IfcOpenShell service: IFC -> semantic TwinEntity + geometry manifest
2. Geometry pipeline: IFC -> GLB / 3D Tiles
3. P6 connector: XER/XML/API -> Activity + WBS + dependencies
4. OneField persistence: evidence/memory/proof API
5. OneForge: CV / forecast model release lifecycle
6. Enterprise OIDC + scoped project RBAC
