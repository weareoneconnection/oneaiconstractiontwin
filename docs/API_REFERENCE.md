# Primary API Reference

The authoritative interactive schema is available at `/docs` and `/openapi.json`.

## Health and operations
- `GET /health`
- `GET /health/live`
- `GET /health/ready`
- `GET /ready`
- `GET /metrics`
- `GET /api/v1/admin/readiness`
- `GET /api/v1/admin/workers`

## Authentication
- `POST /api/v1/auth/dev-token` - non-production only
- `GET /api/v1/auth/me`

## Projects and twins
- `GET/POST /api/v1/projects`
- `GET /api/v1/projects/{project_id}`
- `GET/POST /api/v1/projects/{project_id}/entities`
- `GET /api/v1/projects/{project_id}/entities/{entity_id}`
- `GET /api/v1/projects/{project_id}/activities`
- `GET /api/v1/projects/{project_id}/evidence`
- `GET /api/v1/projects/{project_id}/graph`

## BIM and 4D
- `POST /api/v1/projects/{project_id}/bim/import-ifc`
- `POST /api/v1/projects/{project_id}/schedules/import-csv`
- `POST /api/v1/projects/{project_id}/mappings/auto`
- `GET /api/v1/projects/{project_id}/timeline`
- `GET /api/v1/projects/{project_id}/timeline/state`

## Distributed assets
- `POST /api/v1/projects/{project_id}/bim/models/{document_id}/asset-jobs`
- `GET /api/v1/asset-jobs/{job_id}`
- `GET /api/v1/asset-jobs/{job_id}/events/stream`
- `POST /api/v1/asset-jobs/{job_id}/cancel`
- `POST /api/v1/asset-jobs/{job_id}/resume`
- `GET /api/v1/asset-jobs/{job_id}/manifest`

## Intelligence and action
- `POST /api/v1/projects/{project_id}/ask`
- `POST /api/v1/projects/{project_id}/risks/evaluate`
- `POST /api/v1/projects/{project_id}/forecast`
- `POST /api/v1/projects/{project_id}/simulations`
- `POST /api/v1/projects/{project_id}/agents/run`
- `POST /api/v1/actions/{action_id}/approve`
- `GET /api/v1/projects/{project_id}/audit`


## v0.7.1 additions

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/api/v1/generated-assets/{path}` | `twin:read` | Authenticated, tenant-scoped delivery of locally generated tilesets and GLB payloads. Replaces the removed `/assets` static mount. Returns 403 for a path outside the caller's tenant. |
| GET | `/api/v1/admin/audit/verify` | `audit:read` | Recomputes the tenant's audit hash chain. Returns `ok`, `entries`, `head_hash`, and on failure `broken_at` and `reason`. |

### Changed response shapes

`POST /api/v1/projects/{id}/ask` now returns, in addition to the previous fields:

- `provisional` - true when no project record matched the question
- `evidence_coverage` - share of claims backed by a retrieved record
- `evidence[].relevance` and `evidence[].matched_terms` - retrieval scores
- `claims[].supported`, `claims[].evidence_ids`, `claims[].basis`
- `reasoning` - `provider`, `model`, `mode`, `model_backed`, `retrieval`, `schedule_sample_size`

`POST /api/v1/projects/{id}/risks/evaluate` adds `model`, `calibrated`, `sample_size`,
`data_quality`, `late_activities`, `critical_late_activities`, `causes` and `evidence_ids`.

`POST /api/v1/projects/{id}/forecast` adds `model`, `calibrated`, `basis`, `sample` and
`warning`; `drivers` are now activity records rather than fixed strings.

`POST /api/v1/projects/{id}/simulations` adds `model`, `calibrated` and `assumptions`.

`GET /api/v1/projects/{id}/audit` adds `sequence`, `prev_hash` and `entry_hash`.


## v0.7.3 — collaboration, reporting and portfolio

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/api/v1/portfolio/summary` | `project:read` | Cross-project comparison, aggregated server-side in a fixed number of queries |
| GET | `/api/v1/projects/{id}/comments` | `project:read` | Comments on the project or on something inside it (`target_type`, `target_id`, `include_resolved`) |
| POST | `/api/v1/projects/{id}/comments` | `comment:write` | Post a comment or a reply (`parent_id`); threading is one level deep |
| POST | `/api/v1/projects/{id}/comments/{comment_id}/resolve` | `comment:write` | Resolve or reopen a thread; history is kept, never deleted |
| GET | `/api/v1/projects/{id}/report` | `project:read` | Structured content for the printable status report, including its disclosure text |
| GET | `/api/v1/projects/{id}/exports/{dataset}.csv` | `project:read` (+ `audit:read` for `audit`) | CSV export of `activities`, `entities`, `evidence`, `risks`, `comments`, `audit` |

Both comment mutations and every export write audit entries: `comment.create`,
`comment.resolve`, `comment.reopen`, `data.export` (with the dataset and row count) and
`report.generate`. Taking data out of the system is treated as a recorded event, not a
read.

The `risks` export carries an explicit `calibrated` column. A probability in a
spreadsheet with no indication that the model is uncalibrated invites exactly the
false confidence the rest of the product works to avoid.

`comment:write` is held by every role that can modify the twin (organization admin,
project director, project manager, planner, QA/QC, safety, contractor). `viewer` and
`ai_agent` may read discussion but not post: an agent proposes through
`agent_action`, which requires human approval.
