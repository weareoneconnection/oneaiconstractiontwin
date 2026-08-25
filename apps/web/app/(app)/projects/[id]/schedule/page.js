"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "../../../../../lib/api";
import { date } from "../../../../../lib/format";
import { useSession } from "../../../../../lib/session";
import { Card, Badge, EmptyState, Metric, PermissionButton, Skeleton } from "../../../../../components/ui";
import { useToast } from "../../../../../components/ui/Toast";
import FourDTwinWorkspace from "../../../../../components/FourDTwinWorkspace";
import { useProject } from "../layout";

export default function SchedulePage() {
  const { project, entities, projectId, reload } = useProject();
  const { can } = useSession();
  const { notify } = useToast();
  const [activities, setActivities] = useState(null);
  const [mappings, setMappings] = useState([]);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState(null);
  const fileInput = useRef(null);

  const load = async () => {
    const [rows, maps] = await Promise.all([
      api(`/api/v1/projects/${projectId}/activities`),
      api(`/api/v1/projects/${projectId}/mappings`),
    ]);
    setActivities(rows);
    setMappings(maps);
  };
  useEffect(() => { load().catch(e => notify(e.message, "error")); }, [projectId]);

  const importCsv = async file => {
    if (!file) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const result = await api(`/api/v1/projects/${projectId}/schedules/import-csv`, { method: "POST", body: form });
      notify(`Imported ${result.activities_created ?? result.imported ?? "?"} activities`, "success");
      await load();
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const autoMap = async () => {
    setBusy(true);
    try {
      const result = await api(`/api/v1/projects/${projectId}/mappings/auto?threshold=0.18`, { method: "POST" });
      notify(`Created ${result.mappings_created} confidence-scored mappings`, "success");
      await Promise.all([load(), reload()]);
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const late = (activities || []).filter(a => a.actual_finish && a.planned_finish && new Date(a.actual_finish) > new Date(a.planned_finish));
  const critical = (activities || []).filter(a => a.critical);

  return (
    <div className="page">
      <div className="grid4">
        <Metric label="Activities" value={activities?.length ?? "—"} sub="Imported from the baseline schedule" />
        <Metric label="Critical path" value={critical.length} sub="Activities flagged critical" />
        <Metric label="Finished late" value={late.length} sub="Actual finish after planned finish" tone={late.length ? "warn" : "good"} />
        <Metric label="Mappings" value={mappings.length} sub="BIM element ↔ activity" />
      </div>

      <Card
        title="Baseline schedule"
        meta="CSV exported from P6, MS Project or an equivalent planning tool"
        actions={
          <>
            <input ref={fileInput} type="file" accept=".csv" hidden onChange={e => importCsv(e.target.files?.[0])} />
            <PermissionButton allowed={can("project:write")} permission="project:write" className="btn" onClick={() => fileInput.current?.click()} disabled={busy}>
              Import schedule CSV
            </PermissionButton>
            <PermissionButton
              allowed={can("twin:write")}
              permission="twin:write"
              className="btn primary"
              onClick={autoMap}
              disabled={busy || !activities?.length || !entities.length}
            >
              Auto-map to model
            </PermissionButton>
          </>
        }
      >
        {!activities && <Skeleton lines={4} />}
        {activities && activities.length === 0 && (
          <EmptyState title="No schedule imported" description="Without activities the risk and forecast engines report insufficient history rather than producing a number." />
        )}
        {activities && activities.length > 0 && (
          <div className="table">
            <div className="table-head">
              <span>ID</span><span>Activity</span><span>Planned finish</span><span>Actual finish</span><span>Progress</span><span>Float</span>
            </div>
            {activities.map(activity => {
              const isLate = activity.actual_finish && activity.planned_finish && new Date(activity.actual_finish) > new Date(activity.planned_finish);
              return (
                <div key={activity.id} className={`table-row ${selected === activity.id ? "selected" : ""}`} onClick={() => setSelected(activity.id)}>
                  <span data-label="ID"><b>{activity.external_id}</b>{activity.critical && <Badge tone="warn">critical</Badge>}</span>
                  <span data-label="Activity">{activity.name}</span>
                  <span data-label="Planned finish">{date(activity.planned_finish)}</span>
                  <span data-label="Actual finish" className={isLate ? "warn" : ""}>{date(activity.actual_finish)}</span>
                  <span data-label="Progress">{activity.percent_complete}%</span>
                  <span data-label="Float">{activity.total_float_days} d</span>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {mappings.length > 0 && (
        <Card title="BIM ↔ schedule mapping" meta="Each mapping carries the confidence it was created with">
          <div className="table">
            <div className="table-head"><span>Model element</span><span>Activity</span><span>Strategy</span><span>Confidence</span></div>
            {mappings.slice(0, 25).map(mapping => (
              <div key={mapping.id} className="table-row">
                <span>{mapping.source?.name || mapping.source?.entity_id}</span>
                <span>{mapping.target?.name || mapping.target?.activity_id}</span>
                <span>{mapping.strategy}</span>
                <span className={mapping.confidence > 0.6 ? "good" : "warn"}>{(mapping.confidence * 100).toFixed(0)}%</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      <FourDTwinWorkspace project={project} entities={entities} selectedEntity={null} onSelect={() => {}} />
    </div>
  );
}
