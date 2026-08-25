# Release Notes - v0.7.1 (Hardening)

v0.7.1 changes no product scope. It fixes defects found by a full review of v0.7.0 and
makes the product's own claims verifiable.

## Security

- **Removed the unauthenticated `/assets` static mount.** Generated tilesets and GLB
  payloads are served only by `GET /api/v1/generated-assets/{path}`, which requires
  `twin:read` and rejects any path outside the caller's tenant prefix. Path traversal is
  rejected by two independent guards.
- **The Cesium client now authenticates its own tile requests** via `Cesium.Resource`,
  so child tile fetches inherit the caller's credentials.
- **Rate limiting is no longer trivially bypassed.** The key is derived from a stable
  SHA-256 credential fingerprint (not the randomised built-in `hash()`), ignores
  `X-Forwarded-For` unless `TRUST_FORWARDED_FOR=true`, and applies per caller rather
  than per caller-and-path.

## Evidence and audit integrity

- **Audit entries are hash-chained per tenant.** `GET /api/v1/admin/audit/verify`
  recomputes the chain and reports the first break. Entries written by earlier versions
  are reported as `legacy_unchained_entries` rather than back-dated into the chain.
- **Ask Twin performs real retrieval** (BM25 over the project's evidence, plus a small
  explicit construction synonym list). Different questions return different evidence,
  each with a relevance score and the terms it matched.
- **Claims are derived, not hard-coded**, and each carries the records supporting it. A
  record supports a claim about an activity only if it cites the activity id or shares at
  least two non-generic terms with its name.
- **The evidence policy is enforced in code**: with no matching record the answer is
  marked `provisional: true`, confidence is capped at 0.4, and the text says it must not
  be used for a contractual decision.

## Honest provenance

- Every AI response reports `reasoning.provider`, `reasoning.model`, `reasoning.mode` and
  `reasoning.model_backed`. With no gateway configured, answers are labelled
  `demonstrative-local` in the payload, in the answer text and in the dashboard.
- `OneAICoreAdapter` now actually calls `ONEAI_CORE_URL` when configured, and falls back
  to the local reasoner with `mode: "degraded-local-fallback"` on error.
- The OneField, OneForge and OneClaw adapters report `configured: false` instead of
  returning fabricated success payloads.

## Risk, forecast and agents

- Risk is computed from measured activity slippage (share of slipping activities,
  critical-path weighting, measured critical slip) and returns its model name, sample
  size and data-quality grade with `calibrated: false`.
- The forecast is a bootstrap over the project's own activity variance. Below three
  measured activities it falls back to the recorded baseline delay and returns an
  explicit warning rather than a confident-looking distribution.
- Scenario simulation returns the assumption set it used.
- Agent recommendations name the specific activity, slippage and float they are based on,
  and remain `pending_approval` until a human with `action:approve` accepts them.

## Reliability and packaging

- Partition planning streams entities in batches instead of loading a whole model into
  memory.
- `scripts/migrate.py`, `backup.py` and `restore.py` run as documented.
- `demo/seed` is idempotent per tenant and seeds a small but real schedule; project lists
  return newest first.
- The version lives only in `app/core/version.py`; it was previously duplicated in five
  config files.
- Web dependencies: Next 16.3.2 (0 npm advisories), with `@cesium/widgets` and
  `@zip.js/zip.js` pinned so `npm run build` completes. Node requirement corrected to
  `>=20.9`.

## Web application (v0.7.2)

The dashboard was a single dense page with no routing, no permission awareness and no
loading or empty states. It is now a navigable workspace:

| Route | Purpose |
|---|---|
| `/` | Portfolio: project list, filter, create |
| `/projects/{id}` | Overview: progress, pilot readiness checklist, next steps |
| `/projects/{id}/model` | IFC import, model inventory, 3D viewer, distributed 3D Tiles pipeline |
| `/projects/{id}/schedule` | Baseline schedule table, BIM↔schedule mapping, 4D timeline |
| `/projects/{id}/intelligence` | Ask Twin, risk, forecast, simulation, agent approval |
| `/projects/{id}/audit` | Hash-chained audit trail with one-click chain verification |
| `/admin` | Readiness checks and asset-worker heartbeats |
| `/login`, `/auth/callback` | OIDC sign-in |

Beyond the routing:

- **Permission-aware controls.** Actions the caller's role cannot perform are shown
  disabled with the permission they require, rather than hidden (which hides whether the
  feature exists) or left enabled (which produces a 403 after the click).
- **Real states.** Loading skeletons, empty states that explain what to do next, toasts
  for every mutation, and an error boundary per project route.
- **Provenance carried through.** Confidence, evidence coverage, retrieval method, model
  name, calibration state, sample size, per-claim support and per-evidence relevance are
  all surfaced next to the numbers they qualify.

## Collaboration, reporting and comparison (v0.7.3)

- **Portfolio comparison** (`/compare`): sortable comparison of every project in scope -
  variance, baseline delay, late and critical-late activities, worst slip, evidence
  coverage - aggregated by a single server-side endpoint rather than one request per
  project per metric. Projects without a schedule report zero rather than an estimate,
  and thin data is labelled as such.
- **Comments** on a project or on anything inside it (an agent recommendation, an
  activity, a risk), threaded one level deep and resolvable. Resolving keeps the
  history. Creating and resolving both write audit entries, because "who signed off on
  this recommendation" is a question pilot reviews actually ask.
- **Reporting**: a printable status report (`/projects/{id}/report`) with print styles
  that drop the application chrome, plus CSV exports of activities, entities, evidence,
  risks, comments and the audit trail. Exports are audited by dataset and row count, and
  the audit export additionally requires `audit:read`.
- **Mobile**: an off-canvas navigation drawer, larger touch targets, and tables that
  become labelled cards instead of a six-column grid squeezed onto a phone.

## Charts, live collaboration and offline (v0.7.4)

- **Trend charts** drawn as inline SVG (no charting dependency): the planned-vs-actual
  S-curve with a today marker, cumulative slippage, and audited activity per day split
  by human and agent actor. Every chart states its method and refuses to render a series
  it cannot derive.
- **Live events** over a WebSocket per project: comments, agent recommendations,
  approvals and asset-job state arrive without a refresh. Events fan out through Redis so
  the channel survives multiple API replicas, and the client keeps polling underneath —
  the socket is an accelerator, not the source of truth.
- **Offline support for site use**: a service worker caches the application shell, GET
  responses are cached read-through with the time they were fetched, and comments written
  without a connection are queued locally and flushed on reconnect. Only comments are
  queued — replaying an approval or an import after an unknown delay could act on a state
  that no longer exists.
- A connection indicator shows Live / Online / Reconnecting / Offline and how many writes
  are waiting to be sent.

## Test coverage

31 automated tests (was 8), including regression tests for every defect above, plus
distributed-pipeline lease recovery and max-attempt failure. The suite runs against an
isolated database and storage roots. `scripts/e2e_pilot.py` gates on the security and
evidence-policy guarantees rather than only on HTTP status codes.

## Managed-platform deployment

- The API image is the repository root `Dockerfile` and builds from the repository root,
  so a monorepo service on Railway/Render needs no build configuration.
- `DATABASE_URL` values of the form `postgresql://` or `postgres://` are rewritten to
  `postgresql+psycopg://`. Every managed platform hands out the former, and SQLAlchemy
  maps it to psycopg2, which this project does not ship - the process died at startup.
  `pg_dump`/`pg_restore` keep receiving a plain libpq URL.
- `docs/DEPLOY_RAILWAY.md` and `.env.railway.example` describe the four-service topology.

## Upgrade

`alembic` revision `20260824_0002` adds the audit chain columns. Existing audit rows are
preserved and reported as unchained. No other schema change.
