# The execution chain: Construction Twin → OneClaw → back

The twin sees, reasons and proposes. A human approves. OneClaw acts, and then
tells the twin what happened. This document is the contract between them.

## The boundary

| | Construction Twin | OneClaw |
|---|---|---|
| Role | see, understand, propose, keep the record | execute |
| May act on its own | never | only against a human approval it did not grant |
| Source of truth | yes | no |

The executor holds no organisation chart and resolves no roles. The twin resolves
people to addresses before anything leaves it, so a misdirected notification is
traceable to one system rather than two.

## Status progression

```
pending_approval → approved → dispatched → executed
                            ↘ dispatch_failed
                            ↘ failed
```

`dispatched` is the state that earns its keep. It means the action left the twin
and has not been confirmed — an operational fact, not a synonym for success.
`GET /api/v1/actions/unconfirmed` lists actions stuck there past
`ONECLAW_DISPATCH_STALE_AFTER_SECONDS`.

A `dry_run` outcome never advances an action. A rehearsed chain must not leave a
record claiming the site was told.

## Sequence

```
POST /api/v1/actions/{id}/approve      (human, action:approve)
   └─ recipients present? → dispatch
        │
        ▼
POST {ONECLAW_URL}/v1/tasks/run
Authorization: Bearer <ONECLAW_INTERNAL_TOKEN>
Idempotency-Key: <action id>
        │
        ├─ twin.recovery_plan.publish   (optional) renders and archives the plan
        ├─ twin.notify.stakeholders     delivers by SMTP and/or Telegram
        └─ twin.action.report           writes the outcome back
                 │
                 ▼
POST {TWIN_URL}/api/v1/actions/{id}/execution
X-API-Key: <service_executor key>
        │
        ▼
status → executed · delivery receipts filed as Evidence · audit chain +1
```

Reverse direction, which changes nothing on the project:

```
twin.evidence.collect → GET <allowlisted host>
                      → POST {TWIN_URL}/api/v1/projects/{id}/evidence/ingest
```

## Capabilities

| Action | Risk | What it does |
|---|---|---|
| `twin.notify.stakeholders` | medium | Delivers an approved action by email or Telegram |
| `twin.action.report` | low | Reports outcome and receipts back to the twin |
| `twin.recovery_plan.publish` | medium | Renders an approved plan to a document, archives it |
| `twin.evidence.collect` | low | Reads an allowlisted source, files it as evidence |

`twin.*` is deliberately a separate namespace from `construction.*`. OneClaw
decides maturity by action prefix, so sharing the prefix would have promoted
eleven unimplemented Construction OS capabilities to live the moment this one
shipped.

## Roles

`service_executor` is the executor's credential in the twin:
`project:read`, `action:execute`, `evidence:write`. It cannot approve and cannot
propose, so a stolen executor key cannot manufacture the approval that is the
only thing authorising it to act.

## Configuration

Twin side:

```
ONECLAW_URL=                       # OneClaw base url
ONECLAW_API_KEY=                   # sent as Authorization: Bearer
ONECLAW_EXECUTION_ENABLED=false    # explicit opt-in; a URL is not enough
ONECLAW_DISPATCH_TIMEOUT_SECONDS=10
ONECLAW_DISPATCH_STALE_AFTER_SECONDS=900
```

OneClaw side: see `.env.example` for `ONECLAW_SMTP_*`, `ONECLAW_EMAIL_LIVE`, and
`ONECLAW_TWIN_*`. Every one of them fails closed.

## Four rules the code enforces

1. **No second approval.** The twin already has a human decision; OneClaw runs
   `approvalMode: auto` but refuses any `twin.notify.stakeholders` without
   `approvedBy`. Two approval queues is one unread approval queue.
2. **Prepared never returns success.** `email.send` and `twin.action.report`
   fail and name the closed gate rather than returning an `ok:true` that reads
   as delivered. An executor that pretends is worse than one that is broken.
3. **The idempotency key is the action id.** Re-approving cannot make a
   subcontractor receive the same incident twice.
4. **Unconfirmed is visible.** A dispatch with no report leaves the action in
   `dispatched` and on the reconciliation list. Nothing is quietly assumed done.
