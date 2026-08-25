# Data Model

## Project World Model
The operational model links spatial assets, schedule, evidence, risk and action.

```text
Project
 |- TwinEntity
 |- Activity
 |- Document
 |- Evidence
 |- Risk
 |- GraphRelation
 |- AgentAction
 |- AuditLog
 |- AssetBuildJob / Partition / Event
```

## Core identity scope
- `tenant_id`: top-level customer isolation
- `organization_id`: legal/business organization
- `project_id`: project boundary

## Twin Entity
A Twin Entity normalizes IFC/GIS/asset records into:
- external identifiers
- spatial context
- lifecycle/4D status
- linked activities/documents/evidence
- intelligence attributes
- version history fields

## Evidence
Evidence stores source type, source ID, fragment, checksum, confidence and content. Production deployments should extend this with signed object metadata, legal retention class and document version.

## Graph
Graph relations use typed edges such as `PART_OF`, `LINKED_TO`, `EVIDENCED_BY`, `BUILT_BY`, `USES`, `AFFECTED_BY` and `MITIGATED_BY`. The current implementation uses relational storage; a dedicated graph engine remains an optional scale-out path.
