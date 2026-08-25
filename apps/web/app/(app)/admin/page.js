"use client";
import { useEffect, useState } from "react";
import { API, api } from "../../../lib/api";
import { since } from "../../../lib/format";
import { useSession } from "../../../lib/session";
import { Badge, Card, EmptyState, Metric, Skeleton } from "../../../components/ui";

export default function AdminPage() {
  const { can, me } = useSession();
  const [report, setReport] = useState(null);
  const [workers, setWorkers] = useState(null);
  const [version, setVersion] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const load = async () => {
      try {
        const response = await fetch(`${API}/health/ready`, { cache: "no-store" });
        setReport(await response.json());
        setVersion(await fetch(`${API}/version`, { cache: "no-store" }).then(r => r.json()));
      } catch (e) { setError(e.message); }
      if (can("admin:read")) {
        api("/api/v1/admin/workers").then(setWorkers).catch(() => setWorkers([]));
      }
    };
    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, [can]);

  const checks = Object.entries(report?.checks || {});
  const failing = checks.filter(([, item]) => !item.ok);

  return (
    <div className="page">
      <div className="grid4">
        <Metric label="Platform status" value={(report?.status || "checking").replace("_", " ")} tone={report?.status === "ready" ? "good" : "warn"} sub={version ? `v${version.version}` : ""} />
        <Metric label="Environment" value={version?.environment || "—"} sub={`auth mode: ${version?.auth_mode || "—"}`} />
        <Metric label="Failing checks" value={failing.length} tone={failing.length ? "warn" : "good"} sub={failing.map(([name]) => name).join(", ") || "none"} />
        <Metric label="Asset workers" value={workers ? workers.length : (can("admin:read") ? "…" : "n/a")} sub={can("admin:read") ? "online heartbeats" : "requires admin:read"} />
      </div>

      <Card title="Readiness checks" meta="A required check that fails blocks readiness; optional ones do not">
        {error && <div className="result">{error}</div>}
        {!report && !error && <Skeleton lines={3} />}
        {checks.length > 0 && (
          <div className="readiness-grid">
            {checks.map(([name, item]) => (
              <div key={name} className={`readiness-row ${item.ok ? "" : "fail"}`}>
                <span>{name.replaceAll("_", " ")}</span>
                <b>{item.ok ? "PASS" : item.required === false ? "OPTIONAL" : "BLOCKED"}</b>
                {item.latency_ms != null && <small>{item.latency_ms} ms</small>}
                {item.detail && <small>{item.detail}</small>}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="Asset workers" meta="Convert IFC models into 3D Tiles; jobs stay queued without one">
        {!can("admin:read") && <EmptyState title="Not available for your role" description={`${me?.role || "This role"} does not have the admin:read permission.`} />}
        {can("admin:read") && !workers && <Skeleton lines={2} />}
        {can("admin:read") && workers?.length === 0 && (
          <EmptyState title="No worker online" description="Asset jobs will remain queued until a worker registers a heartbeat." />
        )}
        {workers?.length > 0 && (
          <div className="table">
            <div className="table-head"><span>Worker</span><span>Type</span><span>Status</span><span>Version</span><span>Storage</span><span>Last seen</span></div>
            {workers.map(worker => (
              <div key={worker.worker_id} className="table-row">
                <span data-label="Worker" className="mono">{worker.worker_id}</span>
                <span data-label="Type">{worker.worker_type}</span>
                <span data-label="Status"><Badge tone={worker.status === "online" ? "good" : "warn"}>{worker.status}</Badge></span>
                <span data-label="Version">{worker.version}</span>
                <span data-label="Storage">{worker.meta?.storage || "—"}</span>
                <span data-label="Last seen">{since(worker.last_seen_at)}</span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
