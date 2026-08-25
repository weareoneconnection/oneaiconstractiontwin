# Alpha v0.3 Architecture

## Scope added over v0.2
- IFC upload with semantic parsing (IfcOpenShell when installed; STEP fallback otherwise)
- Automatic generation of normalized TwinEntity records
- IFC model registry via Document records + SHA-256 provenance
- Schedule CSV ingestion into Activity domain model
- Confidence-scored BIM↔Schedule mapping
- GraphRelation `LINKED_TO` edges + MappingRule audit records
- Web BIM↔Schedule workspace
- Demo IFC and schedule fixtures

## Data flow
IFC → validation/parser → normalized product records → TwinEntity → Graph

Schedule CSV → normalized Activity → mapping scorer → MappingRule + `LINKED_TO` → TwinEntity.links.activities

## Non-goals in v0.3
- Production-grade IFC geometry tessellation / coordinate normalization
- Native Primavera P6 XER/XML parser
- Revit plugin
- 4D animation by geometry state
These remain explicit next adapters rather than mocked capabilities.
