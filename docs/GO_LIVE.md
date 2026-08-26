# Going live with the first real use case

Order matters here. Each step proves the one before it, and the last step is the
first time a real person receives a real message.

Never paste a password into a chat, a ticket, or a commit. Secrets belong in the
`.env` file on the host, and nowhere else.

---

## Step 1 — Put the SMTP credentials on the host

Edit `oneclaw-v5-phase4/.env` (never `.env.example`, which is committed):

```
ONECLAW_SMTP_HOST=smtp.gmail.com
ONECLAW_SMTP_PORT=587
ONECLAW_SMTP_USER=notifications@yourcompany.com
ONECLAW_SMTP_PASSWORD=<the 16-character app password, on the host only>
ONECLAW_SMTP_FROM="Construction Twin <notifications@yourcompany.com>"
ONECLAW_SMTP_RECIPIENT_ALLOWLIST=@yourcompany.com
ONECLAW_EMAIL_LIVE=false
```

Leave `ONECLAW_EMAIL_LIVE=false` for now. Step 2 does not need it and you do not
want a half-configured connector able to send.

### Google Workspace specifics

The domain's mail is hosted by Google Workspace, so its SPF record already
authorises Gmail to send for it. No DNS change is needed.

1. **Use a dedicated mailbox**, not a person's. Subcontractors reply to whatever
   is in `From`, and those replies should land somewhere a person is expected to
   read, not in a general company inbox.
2. **Turn on 2-Step Verification** for that account. Google does not offer app
   passwords without it.
3. **Generate an app password** at `myaccount.google.com/apppasswords`. It is 16
   letters. The account login password will fail authentication no matter what
   else is correct.
4. **`ONECLAW_SMTP_FROM` must match `ONECLAW_SMTP_USER`** (or an alias configured
   under "Send mail as" for that account). Gmail rewrites a `From` it does not
   recognise, so a mismatch silently changes the sender the site team sees.
5. **Sending limits.** A Workspace account sends to roughly 2,000 external
   recipients a day. That is ample for approved actions and nowhere near enough
   for bulk mail — which this connector should never be used for anyway. If it
   is ever hit, move to Workspace SMTP relay (`smtp-relay.gmail.com`, admin
   configuration required) rather than raising the limit on a person's mailbox.

### The two settings that most often go wrong

- **Port.** Use 587 and leave `ONECLAW_SMTP_SECURE` unset — it defaults to
  implicit TLS only on port 465. Forcing `true` on 587 hangs until the timeout.
- **Recipient allowlist.** An empty allowlist means *any* address a task supplies
  can be mailed. Set it before the first live send, and keep it to the domains
  this project actually writes to. Add a subcontractor's domain only when you
  are ready for them to receive real notifications.

---

## Step 2 — Verify the connection, without sending

```bash
cd oneclaw-v5-phase4 && npm run verify:smtp
```

It prints the configuration with the password redacted, then opens a real
connection and authenticates. A `FAIL` here is a credential or host problem and
nothing has been sent.

---

## Step 3 — Send one real message to yourself

```bash
cd oneclaw-v5-phase4 && ONECLAW_EMAIL_LIVE=true npm run verify:smtp -- --to you@yourcompany.com
```

Setting the variable inline keeps the connector off in the stored config until
you have seen the message arrive. **Open the mailbox and confirm it.** A `250 Ok`
from the server means accepted for delivery, not delivered — spam filters and
forwarding rules act after that point.

Once it arrives, set `ONECLAW_EMAIL_LIVE=true` in `.env` and restart OneClaw.

---

## Step 4 — Wire the two systems together

`oneclaw-v5-phase4/.env`:

```
ONECLAW_INTERNAL_TOKEN=<a long random secret>
ONECLAW_TWIN_URL=https://twin.yourcompany.com
ONECLAW_TWIN_API_KEY=<the executor key from step 5>
ONECLAW_TWIN_LIVE=true
```

`oneai-construction-twin 2` environment:

```
ONECLAW_URL=https://oneclaw.yourcompany.com
ONECLAW_API_KEY=<the same ONECLAW_INTERNAL_TOKEN>
ONECLAW_EXECUTION_ENABLED=true
```

---

## Step 5 — Create the executor credential in the twin

The executor gets its own key with the `service_executor` role: it can report and
file evidence, but cannot approve and cannot propose. A stolen executor key must
not be able to manufacture the approval that is the only thing authorising it to
act.

Generate the key and its record on the twin host:

```bash
python3 - <<'PY'
import hashlib, json, secrets
key = secrets.token_urlsafe(32)
print("ONECLAW_TWIN_API_KEY =", key)          # goes in OneClaw's .env
print("API_KEY_RECORDS_JSON entry:")
print(json.dumps({hashlib.sha256(key.encode()).hexdigest(): {
    "role": "service_executor",
    "tenant_id": "<your tenant>",
    "organization_id": "<your org>",
    "user_id": "oneclaw-executor",
}}, indent=2))
PY
```

The twin stores only the SHA-256 digest, so the key itself exists in exactly one
place: OneClaw's `.env`.

---

## Step 6 — Confirm both connectors probe green

```bash
curl -H "Authorization: Bearer $ONECLAW_INTERNAL_TOKEN" \
  https://oneclaw.yourcompany.com/v1/connectors/smtp/test
curl -H "Authorization: Bearer $ONECLAW_INTERNAL_TOKEN" \
  https://oneclaw.yourcompany.com/v1/connectors/construction_twin/test
```

Both must return `"probed": true` and `"ok": true`. `"probed": false` means the
result reflects configuration only and no connection was attempted.

Check the capability gates too — `twin.*` must read `live`, and `construction.*`
must still read `prepared`:

```bash
curl -H "Authorization: Bearer $ONECLAW_INTERNAL_TOKEN" \
  https://oneclaw.yourcompany.com/v1/capabilities
```

---

## Step 7 — Rehearse the first use case with a dry run

Send it to yourself, not to the subcontractor:

```bash
curl -X POST https://oneclaw.yourcompany.com/v1/actions/execute \
  -H "Authorization: Bearer $ONECLAW_INTERNAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action":"twin.notify.stakeholders","input":{
        "actionId":"rehearsal","approvedBy":"you",
        "subject":"Rehearsal","body":"Rehearsal",
        "recipients":[{"kind":"email","address":"you@yourcompany.com"}],
        "dryRun":true}}'
```

`dryRun` produces a `dry_run` receipt and sends nothing. Remove it to send the
same message for real, still to yourself.

---

## Step 8 — Run the first real action

In the twin, approve an action with the real distribution list:

```bash
curl -X POST https://twin.yourcompany.com/api/v1/actions/<action-id>/approve \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <the approver's own token>" \
  -d '{"recipients":[
        {"kind":"email","address":"site.manager@steelsub.com",
         "name":"Site Manager","role":"steel_subcontractor"},
        {"kind":"email","address":"pm@yourcompany.com",
         "name":"Project Manager","role":"project_manager"}]}'
```

The response is the action itself. Read three fields:

- `status` — `executed` means the executor confirmed delivery. `dispatched` means
  it left and has not reported yet. `dispatch_failed` means it never left, and
  `execution_error` says why. The approval stands in every case.
- `executor_task_id` — the OneClaw run, for `GET /v1/tasks/{id}`.
- `execution_error` — null when nothing went wrong.

Then confirm the record:

```bash
# Delivery receipts filed as evidence
curl .../api/v1/projects/<project-id>/evidence
# Audit chain, including the machine actor's report
curl .../api/v1/projects/<project-id>/audit
curl .../api/v1/admin/audit/verify
# Anything that left and never came back
curl .../api/v1/actions/unconfirmed
```

---

## After go-live

An action that was dispatched and never confirmed is invisible until something
looks for it. Run the reconciliation job on a schedule — it exits 1 when anything
is unconfirmed, so cron mail or a monitoring check notices without parsing output:

```cron
*/15 * * * * cd /path/to/oneai-construction-twin/apps/api && \
  .venv/bin/python scripts/reconcile_actions.py
```

`--json` emits the same result for a monitoring agent. The threshold comes from
`ONECLAW_DISPATCH_STALE_AFTER_SECONDS` (default 900s).

`GET /api/v1/actions/unconfirmed` gives the same list scoped to one tenant, for
someone looking at a single project.

### If the sender address needs to be an alias

Authenticating as one account and sending as another only works when the alias is
verified under Gmail's **Settings → Accounts → Send mail as**. Until it is, Gmail
silently rewrites `From` back to the authenticated account — so the address the
site team sees is not the one configured, and nothing reports an error.

## Rolling back

Set `ONECLAW_EMAIL_LIVE=false` and restart. `email.send` and
`twin.notify.stakeholders` then fail loudly and name the closed gate; nothing is
delivered, and no action is recorded as executed. Approvals continue to work and
are recorded as approved-but-not-dispatched.
