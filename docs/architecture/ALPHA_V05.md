# Alpha v0.5 Architecture — Large Model Streaming

```text
IFC / BIM
   |
   v
v0.3 Semantic Ingestion ----> Twin Entity / World Model
   |
   v
v0.4 Geometry Extraction
   |
   v
v0.5 Asset Pipeline
   |-- GLB LOD0 (full)
   |-- GLB LOD1 (~50% triangles)
   |-- GLB LOD2 (~25% triangles)
   `-- 3D Tiles 1.1 Tileset
          |
          v
     /assets static streaming
          |
          v
       CesiumJS
          |
          +--> screen-space LOD selection
          +--> spatial streaming
          `--> future GIS / infrastructure context

The v0.4 Three.js + 4D Timeline workspace remains the detailed element/time inspection surface. Cesium v0.5 is the scale-oriented infrastructure viewer.
```

## Architectural rule

Do not replace the Project World Model with 3D Tiles. Tiles are a delivery/rendering representation. Twin Entity IDs, schedules, evidence, risks and actions remain authoritative domain objects.
