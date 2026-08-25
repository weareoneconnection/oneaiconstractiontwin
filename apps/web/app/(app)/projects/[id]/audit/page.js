"use client";
import { useEffect, useState } from "react";
import { api } from "../../../../../lib/api";
import { dateTime, shortId } from "../../../../../lib/format";
import { useSession } from "../../../../../lib/session";
import { Badge, Card, EmptyState, PermissionButton, Skeleton } from "../../../../../components/ui";
import { useToast } from "../../../../../components/ui/Toast";
import { useProject } from "../layout";

export default function AuditPage() {
  const { projectId } = useProject();
  const { can } = useSession();
  const { notify } = useToast();
  const [entries, setEntries] = useState(null);
  const [verification, setVerification] = useState(null);
  const [verifying, setVerifying] = useState(false);
  const [expanded, setExpanded] = useState(null);

  useEffect(() => {
    api(`/api/v1/projects/${projectId}/audit`).then(setEntries).catch(error => notify(error.message, "error"));
  }, [projectId]);

  const verify = async () => {
    setVerifying(true);
    try {
      const result = await api("/api/v1/admin/audit/verify");
      setVerification(result);
      notify(result.ok ? `Chain verified across ${result.entries} entries` : `Chain broken: ${result.reason}`, result.ok ? "success" : "error");
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setVerifying(false);
    }
  };

  return (
    <div className="page">
      <Card
        title="Audit trail"
        meta="Append-only and hash-chained per tenant: editing or deleting an entry breaks the chain"
        actions={
          <PermissionButton allowed={can("audit:read")} permission="audit:read" className="btn primary" onClick={verify} disabled={verifying}>
            {verifying ? "Recomputing…" : "Verify chain"}
          </PermissionButton>
        }
      >
        {verification && (
          <div className={`verification ${verification.ok ? "ok" : "broken"}`}>
            <b>{verification.ok ? "Chain intact" : "Chain broken"}</b>
            <span>
              {verification.ok
                ? `${verification.entries} entries · head ${verification.head_hash?.slice(0, 16)}…`
                : `${verification.reason} at sequence ${verification.broken_at?.sequence}`}
            </span>
            {verification.legacy_unchained_entries > 0 && (
              <small>{verification.legacy_unchained_entries} entries predate the chain and are reported separately.</small>
            )}
          </div>
        )}

        {!entries && <Skeleton lines={5} />}
        {entries && entries.length === 0 && (
          <EmptyState title="No audit entries" description="Actions on this project will appear here as they happen." />
        )}
        {entries && entries.length > 0 && (
          <div className="table audit-table">
            <div className="table-head">
              <span>#</span><span>Action</span><span>Actor</span><span>Resource</span><span>When</span><span>Hash</span>
            </div>
            {entries.map(entry => (
              <div key={entry.id}>
                <div className="table-row" onClick={() => setExpanded(expanded === entry.id ? null : entry.id)}>
                  <span>{entry.sequence}</span>
                  <span><b>{entry.action}</b></span>
                  <span>{entry.actor_id}<Badge tone={entry.actor_type === "agent" ? "warn" : "neutral"}>{entry.actor_type}</Badge></span>
                  <span>{entry.resource_type} {shortId(entry.resource_id)}</span>
                  <span>{dateTime(entry.created_at)}</span>
                  <span className="mono">{entry.entry_hash?.slice(0, 10)}…</span>
                </div>
                {expanded === entry.id && (
                  <pre className="audit-detail">
{JSON.stringify({ before: entry.before, after: entry.after, meta: entry.meta, prev_hash: entry.prev_hash }, null, 2)}
                  </pre>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
