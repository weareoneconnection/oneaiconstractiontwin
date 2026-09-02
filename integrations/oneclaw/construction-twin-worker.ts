import type {
  ExecutionContext,
  Worker,
  WorkerExecutionResult,
} from "../../types/capability.js";
import type { Json } from "../../types/task.js";

/**
 * OneClaw worker for the OneAI Construction Twin.
 *
 * This is deliberately not the existing `construction_worker`, which serves Construction
 * OS and is a planning shell: it normalises an action and returns, without calling
 * anything. This worker actually talks to a Construction Twin deployment, in both
 * directions:
 *
 *   twin ──dispatch──▶ OneClaw ──┐
 *                                ├─ read project context from the twin
 *                                ├─ carry the action out
 *                                └─ report the outcome back to the twin
 *
 * Two invariants are inherited from the twin and must not be relaxed here:
 *
 *   1. Nothing is carried out that a human has not approved. The dispatched action
 *      carries `approvedBy`; without it this worker refuses.
 *   2. The twin is told what actually happened, including failure. It records
 *      `dispatched` and `executed` as separate states precisely so that "we sent it and
 *      never heard back" is visible rather than indistinguishable from success.
 *
 * Configuration (environment):
 *   CONSTRUCTION_TWIN_URL      https://twin-api.example.com
 *   CONSTRUCTION_TWIN_API_KEY  an API key issued by the twin
 */

type TwinConfig = {
  baseUrl: string;
  apiKey: string;
};

function readConfig(): TwinConfig | null {
  const baseUrl = String(process.env.CONSTRUCTION_TWIN_URL ?? "").replace(/\/+$/, "");
  const apiKey = String(process.env.CONSTRUCTION_TWIN_API_KEY ?? "");
  if (!baseUrl || !apiKey) return null;
  return { baseUrl, apiKey };
}

async function twinRequest(
  config: TwinConfig,
  path: string,
  init: RequestInit = {},
): Promise<{ ok: boolean; status: number; body: any }> {
  const response = await fetch(`${config.baseUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": config.apiKey,
      ...(init.headers ?? {}),
    },
  });
  let body: any = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  return { ok: response.ok, status: response.status, body };
}

function asString(value: Json | undefined): string {
  return String(value ?? "").trim();
}

function asRecord(value: Json | undefined): Record<string, Json> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return value as Record<string, Json>;
}

/** Recipients are validated here so a typo does not become a silent non-delivery. */
function parseRecipients(input: Record<string, Json>): string[] {
  const raw = input.recipients ?? input.to ?? "";
  const list = Array.isArray(raw) ? raw.map(String) : String(raw).split(/[;,]/);
  return list.map((value) => value.trim()).filter((value) => value.includes("@"));
}

export class ConstructionTwinWorker implements Worker {
  readonly name = "construction_twin_worker";

  async execute(
    input: Record<string, Json>,
    context: ExecutionContext,
  ): Promise<WorkerExecutionResult> {
    const config = readConfig();
    if (!config) {
      return {
        ok: false,
        error:
          "Construction Twin is not configured for this OneClaw deployment. " +
          "Set CONSTRUCTION_TWIN_URL and CONSTRUCTION_TWIN_API_KEY.",
      };
    }

    const projectId = asString(input.projectId);
    const actionId = asString(input.actionId);
    const approvedBy = asString(input.approvedBy);

    if (!projectId) return { ok: false, error: "input.projectId is required" };

    switch (context.action) {
      case "construction_twin.notify":
        return this.notify(config, input, context, { projectId, actionId, approvedBy });
      case "construction_twin.evidence.record":
        return this.recordEvidence(config, input, context, projectId);
      case "construction_twin.context.read":
        return this.readContext(config, context, projectId);
      default:
        return { ok: false, error: `Unsupported action ${context.action}` };
    }
  }

  /**
   * Send an approved mitigation to the people who have to act on it, then file the
   * delivery receipt back into the twin as evidence.
   *
   * The receipt matters as much as the message: it turns "we told the subcontractor"
   * from a claim into a record the twin can cite later.
   */
  private async notify(
    config: TwinConfig,
    input: Record<string, Json>,
    context: ExecutionContext,
    ids: { projectId: string; actionId: string; approvedBy: string },
  ): Promise<WorkerExecutionResult> {
    if (!ids.actionId) return { ok: false, error: "input.actionId is required for a notification" };
    if (!ids.approvedBy) {
      // The twin only dispatches approved actions; if this is missing, something has
      // bypassed that path and the safe response is to stop.
      return { ok: false, error: "Refusing to notify: the action carries no human approval." };
    }

    const recipients = parseRecipients(input);
    if (recipients.length === 0) {
      return { ok: false, error: "No valid recipient address was supplied in input.recipients" };
    }

    // Pull the current state rather than trusting what was dispatched: an action may
    // have sat in a queue while the project moved on.
    const project = await twinRequest(config, `/api/v1/projects/${ids.projectId}`);
    if (!project.ok) {
      return { ok: false, error: `Could not read the project from the twin: ${project.status}` };
    }

    const subject =
      asString(input.subject) ||
      `[${project.body?.code ?? "Project"}] Approved schedule recovery action`;
    const body =
      asString(input.body) ||
      [
        `Project: ${project.body?.name ?? ids.projectId}`,
        `Approved by: ${ids.approvedBy}`,
        "",
        asString(input.recommendation) || "An approved mitigation requires your action.",
        "",
        `Reference: action ${ids.actionId}`,
      ].join("\n");

    await context.log(`Notifying ${recipients.length} recipient(s) for action ${ids.actionId}`);

    // Delegate the actual send to whichever messaging capability the deployment has
    // configured; this worker owns the twin contract, not the transport.
    const delivery = await this.deliver(recipients, subject, body, context);

    // The delivery receipt travels inside the execution report: the twin turns the
    // `evidence` block into a retrievable record on its side, so there is no second
    // round trip to keep consistent.
    // The twin's ExecutionReportIn contract. `dry_run` is a first-class outcome there
    // and never advances the action, which is why a rehearsal must send it rather than
    // reporting a success it did not perform.
    const report = await twinRequest(config, `/api/v1/actions/${ids.actionId}/execution`, {
      method: "POST",
      body: JSON.stringify({
        outcome: delivery.ok ? "executed" : "failed",
        oneclaw_task_id: context.taskId,
        summary: delivery.ok
          ? `Notification delivered to ${recipients.length} recipient(s).`
          : `Notification not delivered: ${delivery.detail}`,
        receipts: { recipients, subject, delivered_at: new Date().toISOString(), detail: delivery.detail },
        error: delivery.ok ? null : delivery.detail,
        evidence: [
          {
            source_type: "oneclaw_execution",
            source_id: `OC-${context.taskId.slice(0, 12)}`,
            content:
              `Approved action ${ids.actionId} was ${delivery.ok ? "sent" : "not sent"} to ${recipients.join(", ")}. ` +
              `Subject: ${subject}. Approved by ${ids.approvedBy}.`,
            captured_at: new Date().toISOString(),
            metadata: { task_id: context.taskId, recipients, delivered: delivery.ok },
          },
        ],
      }),
    });

    if (!report.ok) {
      // The work happened but the twin does not know. Surfacing this is the whole point
      // of the dispatched/executed split: an operator can reconcile it.
      return {
        ok: false,
        error: `Notification ${delivery.ok ? "sent" : "failed"}, but reporting back to the twin failed with ${report.status}. The action will show as dispatched and unconfirmed.`,
        output: { delivered: delivery.ok, recipients, reportStatus: report.status },
      };
    }

    return {
      ok: delivery.ok,
      output: {
        delivered: delivery.ok,
        recipients,
        subject,
        actionId: ids.actionId,
        twinConfirmed: true,
        detail: delivery.detail,
      },
    };
  }

  /** Push an external observation into the twin as evidence it can retrieve and cite. */
  private async recordEvidence(
    config: TwinConfig,
    input: Record<string, Json>,
    context: ExecutionContext,
    projectId: string,
  ): Promise<WorkerExecutionResult> {
    const content = asString(input.content) || asString(input.summary);
    if (!content) return { ok: false, error: "input.content is required" };

    const rows = [
      "source_id,date,content,activity_id,author",
      [
        asString(input.sourceId) || `OC-${context.taskId.slice(0, 8)}`,
        asString(input.date) || new Date().toISOString().slice(0, 10),
        `"${content.replace(/"/g, '""')}"`,
        asString(input.activityId),
        asString(input.author) || "oneclaw",
      ].join(","),
    ].join("\n");

    const form = new FormData();
    form.append("file", new Blob([rows], { type: "text/csv" }), "oneclaw-evidence.csv");

    const response = await fetch(
      `${config.baseUrl}/api/v1/projects/${projectId}/evidence/import-csv?source_type=${encodeURIComponent(asString(input.sourceType) || "note")}`,
      { method: "POST", headers: { "X-API-Key": config.apiKey }, body: form },
    );
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      return { ok: false, error: `The twin rejected the evidence: ${response.status} ${JSON.stringify(body)}` };
    }
    await context.log(`Filed ${body?.created ?? 0} evidence record(s) into project ${projectId}`);
    return { ok: true, output: { created: body?.created ?? 0, duplicates: body?.duplicates_skipped ?? 0 } };
  }

  /** Read-only project context, for a task that needs to know before it acts. */
  private async readContext(
    config: TwinConfig,
    context: ExecutionContext,
    projectId: string,
  ): Promise<WorkerExecutionResult> {
    const [project, status] = await Promise.all([
      twinRequest(config, `/api/v1/projects/${projectId}`),
      twinRequest(config, `/api/v1/projects/${projectId}/pilot-status`),
    ]);
    if (!project.ok) return { ok: false, error: `Could not read project ${projectId}: ${project.status}` };
    await context.log(`Read context for ${project.body?.code ?? projectId}`);
    return {
      ok: true,
      output: {
        project: project.body,
        counts: status.body?.counts ?? null,
        readiness: status.body?.readiness ?? null,
      },
    };
  }

  /**
   * Transport seam.
   *
   * Left explicit rather than hidden behind a default: which channel a site actually
   * uses (email connector, messaging worker, an internal API) is a deployment decision,
   * and silently "succeeding" without sending anything would be the worst outcome here.
   */
  private async deliver(
    recipients: string[],
    subject: string,
    body: string,
    context: ExecutionContext,
  ): Promise<{ ok: boolean; detail: string }> {
    const webhook = String(process.env.CONSTRUCTION_TWIN_NOTIFY_WEBHOOK ?? "");
    if (!webhook) {
      return {
        ok: false,
        detail:
          "No delivery channel is configured. Set CONSTRUCTION_TWIN_NOTIFY_WEBHOOK, or route this action to the deployment's email/messaging worker.",
      };
    }
    try {
      const response = await fetch(webhook, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recipients, subject, body, taskId: context.taskId }),
      });
      return {
        ok: response.ok,
        detail: response.ok ? `Delivered via webhook (${response.status})` : `Webhook returned ${response.status}`,
      };
    } catch (error) {
      return { ok: false, detail: `Webhook failed: ${error instanceof Error ? error.message : String(error)}` };
    }
  }
}
