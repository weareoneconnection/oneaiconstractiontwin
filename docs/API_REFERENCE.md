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


## v0.7.4 — analytics and live events

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/api/v1/projects/{id}/analytics/s-curve` | `project:read` | Planned vs actual cumulative completion, derived from activity dates |
| GET | `/api/v1/projects/{id}/analytics/slippage` | `project:read` | Cumulative finish-date slippage as it accrued |
| GET | `/api/v1/projects/{id}/analytics/activity` | `audit:read` | Audited events per day, split between human and agent actors |
| WS | `/api/v1/ws/projects/{id}` | `project:read` | Live project events: comments, agent recommendations, approvals, asset jobs |

### The S-curve is derived, not stored

This system holds no progress-history table, so a "progress over time" line could only be
invented. What is real is the schedule, so both curves are computed from activity dates:

- `planned` — the cumulative share of activities the baseline expected complete by each date
- `actual` — the cumulative share actually complete, **only up to today**; later points
  return `null` rather than projecting completion into dates that have not happened
- `weighting` — count-weighted, stated in every response: each activity counts once,
  because activity cost and resource loading are not held by this system. A count-weighted
  curve reads differently from the cost-loaded curve a planner expects.

A project without planned finish dates gets `available: false` and a reason, not an empty
chart that looks like zero progress.

### WebSocket authentication and delivery

A browser cannot set headers on a WebSocket handshake, so the access token is passed as
`?token=`. That is standard over TLS, but the token does appear in proxy access logs.
Development header auth (`?tenant_id=&organization_id=&role=`) is honoured only outside
production, exactly as for HTTP.

Events are published to Redis and relayed by every replica, so the channel works behind
more than one API instance. Without Redis it still works within a single process, and the
`connected` frame reports `cross_replica: false` rather than pretending otherwise.

**The socket is an accelerator, never the source of truth.** Clients keep their existing
polling; the socket only makes updates arrive sooner. A dropped connection degrades
latency, not correctness.


## v0.8 — evidence ingestion and critical path

### Evidence (H1)

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/api/v1/evidence/source-types` | any | Which record types this deployment ingests, and the column aliases it recognises |
| POST | `/api/v1/projects/{id}/evidence/import-csv?source_type=…` | `twin:write` | Import daily reports, RFIs, NCRs, inspections or delivery records |
| POST | `/api/v1/projects/{id}/evidence/photos` | `twin:write` | Register a site photograph (multipart) |
| GET | `/api/v1/projects/{id}/evidence` | `twin:read` | List evidence, filtered by `source_type` or `q` |
| GET | `/api/v1/projects/{id}/evidence/coverage` | `twin:read` | Which declared sources this project has, and which it lacks |
| GET | `/api/v1/projects/{id}/evidence/{evidence_id}/image` | `twin:read` | Tenant-scoped delivery of a photograph |

Three properties are worth knowing before wiring an integration:

- **Re-importing is safe.** Records are keyed by a content hash, so a site system that
  re-sends the same export daily produces no duplicates; the response reports how many
  rows it skipped.
- **Column names are matched by alias.** A `content` column under any of its usual names
  is required; `date`, `activity_id`, `ifc_guid`, `zone`, `status`, `author` are used when
  present. Reference columns are also recognised by shape (`report_no`, `ncr_number`, …).
- **Confidence differs by source.** A signed inspection (0.97) outranks a shift narrative
  (0.88), and retrieval weights evidence by it. A `confidence` column overrides the default.

Photographs are dated from their own EXIF `DateTimeOriginal` where present — a photo that
reaches the office three days later is evidence about the day it was taken — and the
response reports `taken_at_source` as `exif` or `upload-time` so the difference is never
silent.

### Critical path (H3)

`POST /api/v1/projects/{id}/forecast` now includes a `critical_path` block computed from
the schedule's own logic links, plus `network_impact_days` and `absorbed_by_float_days`.

Logic arrives with the schedule import: a `predecessors` column in P6/MS Project notation
(`A1023FS+2, A1030SS-1`). Activity ids containing hyphens are handled — `P-010` is an id,
not a ten-day negative lag, and a lag is only read where the schedule marks one.

The distinction the previous forecast could not make: slippage is carried along the logic
and absorbed by **free** float, so total measured slip is normally larger than the days
that actually reach the project finish. Each late activity reports
`project_impact_contribution_days` — how many of those days it is responsible for —
rather than a boolean that would call an absorbed delay "reaching the finish".

Where a schedule carries no logic, the response says so and explains what column to add,
instead of treating every activity as independent and calling that a critical path.
Activities with no links are excluded from the disagreement report, since the network
cannot judge them.

### Reconciliation

`GET /api/v1/actions/unconfirmed` (`action:approve`) lists approved actions that were
dispatched to an executor and never confirmed. The twin keeps `dispatched` and `executed`
apart so this list can exist; the platform page renders it.
