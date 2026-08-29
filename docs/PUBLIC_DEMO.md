# Public Demo Endpoint

An unauthenticated, read-only surface that serves **one seeded project**, so the
marketing site can show real product output instead of static mock data.

It is off unless a deployment turns it on. A customer installation should never
enable it.

## Why it is shaped this way

Exposing anything without credentials on a system that holds customer project
records deserves a narrow, deliberate design. Five properties do the work:

**Off by default.** `PUBLIC_DEMO_ENABLED` defaults to `false`, and when it is
false every route under the prefix returns 404 rather than 403 — a disabled
demo should not advertise that a demo exists.

**The identity is constructed, never received.** The router builds its own
`RequestContext` from configuration: the `public_demo` role, the configured
demo tenant and organization. No header a caller sends can widen it, so the
ordinary tenant scoping in the service layer still does all the work it does
for an authenticated request.

**One project, and the id is not a parameter.** No route under the prefix takes
a path parameter. The project comes from `PUBLIC_DEMO_PROJECT_ID`, and starting
the service with the demo enabled but no project id configured is a
configuration error, not a permissive default.

**Least privilege.** The `public_demo` role grants exactly
`{project:read, twin:read, ai:run}`. It cannot write, approve, propose an
action, read the audit trail or manage users, so a bug in this router cannot
become a data-modifying one.

**The reasoner is reachable only through an allowlist.** An open text box on an
unauthenticated endpoint is both a model bill and a prompt-injection surface
aimed at a system that reads customer records. `/ask` compares the question
against `PUBLIC_DEMO_QUESTIONS` exactly and refuses anything else, returning the
permitted list so the caller learns the boundary and nothing about the project.

## Endpoints

All under `/api/v1/public/demo`.

| Method | Path | Returns |
|---|---|---|
| GET | `/meta` | What the demo is, the allowed questions, and the disclosure text |
| GET | `/project` | Name, planned and actual progress |
| GET | `/activities` | Activities with percent complete, float and criticality |
| GET | `/timeline` | Twin entity state at `now` |
| GET | `/s-curve` | Planned-versus-actual S-curve |
| GET | `/risks` | Evaluated risks with probability, impact and exposure |
| GET | `/forecast` | P10/P50/P90 with drivers and calibration state |
| POST | `/ask` | An answer to one allowlisted question, with evidence and provenance |

`/meta` carries the disclosure text so the marketing site can render it
verbatim rather than re-typing it into a template that will drift.

## Rate limits

Per client IP, in fixed windows, independent of the global limiter:

- 30 requests/minute across the read endpoints
- 6 requests/minute for `/ask`

Exceeding either returns 429 with `Retry-After`.

## Enabling it

```bash
# 1. Seed the demo project on the target deployment and note its id.
curl -X POST https://<api-host>/api/v1/demo/seed \
  -H 'Authorization: Bearer <admin-token>'

# 2. Configure and restart.
PUBLIC_DEMO_ENABLED=true
PUBLIC_DEMO_PROJECT_ID=<the id from step 1>
```

Add the marketing site's origin to `CORS_ORIGINS` so the browser can call it.

## What it deliberately does not expose

No audit, admin, asset, export, comment or action route. No mutations beyond
`/ask`, which reads. `tests/test_public_demo.py` asserts each of these, so
adding one is a decision someone has to make on purpose rather than a side
effect of a later change.

## A note on provenance

If the deployment has no `ONEAI_CORE_URL` configured, `/ask` answers are
composed by the local deterministic reasoner and report
`reasoning.model_backed: false` and `mode: "demonstrative-local"`. That is
correct, and the marketing site should render it as-is: a demo that claims
model-backed reasoning it did not use would undercut the evidence policy it
exists to demonstrate.
