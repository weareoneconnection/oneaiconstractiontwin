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

## Test coverage

31 automated tests (was 8), including regression tests for every defect above, plus
distributed-pipeline lease recovery and max-attempt failure. The suite runs against an
isolated database and storage roots. `scripts/e2e_pilot.py` gates on the security and
evidence-policy guarantees rather than only on HTTP status codes.

## Upgrade

`alembic` revision `20260824_0002` adds the audit chain columns. Existing audit rows are
preserved and reported as unchained. No other schema change.
