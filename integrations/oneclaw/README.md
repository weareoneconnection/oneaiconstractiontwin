# OneClaw integration

The twin sees, reasons and proposes; a human approves; **OneClaw acts**. This directory
holds the OneClaw-side worker, because the executor lives in the OneClaw repository, not
this one.

## Why a new worker

OneClaw already ships a `construction_worker`. It belongs to **Construction OS**, a
different product, and it is a planning shell — `maturity: planned`, `liveMode:
prepared` — that normalises an action and returns without calling anything.

The twin needs an executor that actually talks back to it, in both directions:

```
twin ──dispatch──▶ OneClaw ──┬─ read project context from the twin
                             ├─ carry the action out
                             └─ report the outcome back to the twin
```

That return path is why this is a worker rather than an outbound HTTP call from the twin.

## Installing

1. Copy `construction-twin-worker.ts` into the OneClaw repository at
   `src/workers/construction-twin/construction-twin-worker.ts`.
2. Register the worker and its capabilities in `src/bootstrap.ts`:

```ts
import { ConstructionTwinWorker } from "./workers/construction-twin/construction-twin-worker.js";

workerRegistry.register(new ConstructionTwinWorker());

// …alongside the other capability registrations:
{
  action: "construction_twin.notify",
  workerName: "construction_twin_worker",
  risk: "medium",
  description: "Send an approved schedule recovery action to the responsible parties and file the receipt back into the twin",
  approvalRequired: true,
  inputSchema: { required: ["projectId", "actionId", "approvedBy", "recipients"] },
},
{
  action: "construction_twin.evidence.record",
  workerName: "construction_twin_worker",
  risk: "low",
  description: "File an external observation into the twin as retrievable evidence",
  inputSchema: { required: ["projectId", "content"] },
},
{
  action: "construction_twin.context.read",
  workerName: "construction_twin_worker",
  risk: "low",
  description: "Read project state from the twin before acting",
  inputSchema: { required: ["projectId"] },
},
```

3. Configure the OneClaw deployment:

```bash
CONSTRUCTION_TWIN_URL=https://twin-api.example.com
CONSTRUCTION_TWIN_API_KEY=<an API key issued by the twin>
CONSTRUCTION_TWIN_NOTIFY_WEBHOOK=<your email or messaging endpoint>
```

The API key is minted on the twin side with `apps/api/scripts/generate_api_key.py`; give
it a role with `twin:write` so it can file evidence, and nothing more.

## The two invariants

**Nothing runs without a human approval.** The dispatched action carries `approvedBy`.
Without it the worker refuses rather than acting — and the twin will not dispatch an
unapproved action in the first place, so both ends enforce it.

**The twin is told what actually happened, including failure.** The twin records
`dispatched` and `executed` as separate states so that "we sent it and never heard back"
is visible rather than indistinguishable from success. If delivery succeeds but the
report back fails, the worker returns an error saying exactly that, and the action stays
`dispatched` for an operator to reconcile.

## What is deliberately not here

No delivery transport is bundled. Which channel a site uses — an email connector, a
messaging worker, an internal API — is a deployment decision, and a worker that
"succeeds" without sending anything would be the worst possible outcome. With no
`CONSTRUCTION_TWIN_NOTIFY_WEBHOOK` configured, the worker fails and says so.
