"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "../../../../lib/api";
import { percent } from "../../../../lib/format";
import { Card, Badge, EmptyState, Metric, Skeleton } from "../../../../components/ui";
import CommentThread from "../../../../components/CommentThread";
import { useProject } from "./layout";

export default function ProjectOverview() {
  const { project, entities, projectId } = useProject();
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api(`/api/v1/projects/${projectId}/pilot-status`).then(setStatus).catch(e => setError(e.message));
  }, [projectId]);

  const variance = project.actual_progress - project.planned_progress;

  return (
    <div className="page">
      <div className="grid4">
        <Metric label="Actual progress" value={percent(project.actual_progress)} sub={`${project.name} · ${project.code}`} />
        <Metric label="Plan variance" value={`${variance >= 0 ? "+" : ""}${variance.toFixed(1)}%`} sub={`Planned ${percent(project.planned_progress)}`} tone={variance < 0 ? "warn" : "good"} />
        <Metric label="Forecast delay" value={`${project.forecast_delay_days} d`} sub="Recorded project baseline" tone={project.forecast_delay_days > 0 ? "warn" : "good"} />
        <Metric label="Twin entities" value={entities.length} sub="Project World Model" />
      </div>

      <Card title="Pilot readiness" meta="What this project still needs before it can demonstrate the full chain">
        {!status && !error && <Skeleton lines={3} />}
        {error && <div className="result">{error}</div>}
        {status && (
          <>
            <div className="progress-row">
              <div className="progress-track"><div style={{ width: `${status.pilot_readiness_score}%` }} /></div>
              <b>{status.pilot_readiness_score}%</b>
            </div>
            <div className="checklist">
              {Object.entries(status.readiness).map(([name, ok]) => (
                <div key={name} className={`checklist-item ${ok ? "ok" : "todo"}`}>
                  <span>{ok ? "✓" : "○"}</span>
                  {name.replaceAll("_", " ")}
                </div>
              ))}
            </div>
            <div className="counts-row">
              {Object.entries(status.counts).map(([name, value]) => (
                <div key={name}><span>{name.replaceAll("_", " ")}</span><b>{value}</b></div>
              ))}
            </div>
            <div className="provenance">Scenario: {status.pilot} · evidence policy: {status.evidence_policy}</div>
          </>
        )}
      </Card>

      <div className="two-column">
        <Card title="Twin entities" meta={`${entities.length} in the Project World Model`}>
          {entities.length === 0 ? (
            <EmptyState
              title="No entities yet"
              description="Import an IFC model to create Twin Entities for this project."
              action={<Link className="btn primary" href={`/projects/${projectId}/model`}>Go to BIM & 3D</Link>}
            />
          ) : (
            <div className="entity-list tall">
              {entities.slice(0, 40).map(entity => (
                <div key={entity.id} className="entity">
                  <div className="entity-name">{entity.name}</div>
                  <div className="entity-meta">
                    {entity.entity_type} · {entity.spatial?.zone || "unzoned"}
                    {entity.intelligence?.healthScore != null && ` · health ${entity.intelligence.healthScore}`}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="Next steps" meta="Each step is a separate workspace">
          <div className="next-steps">
            <Link href={`/projects/${projectId}/model`} className="next-step">
              <b>Import the IFC model</b>
              <span>Creates Twin Entities and runs the distributed 3D Tiles pipeline.</span>
            </Link>
            <Link href={`/projects/${projectId}/schedule`} className="next-step">
              <b>Import the baseline schedule</b>
              <span>CSV from P6 or MS Project, then map activities to model elements.</span>
            </Link>
            <Link href={`/projects/${projectId}/intelligence`} className="next-step">
              <b>Ask the twin</b>
              <span>Evidence-first answers, risk, forecast and human-approved actions.</span>
            </Link>
            <Link href={`/projects/${projectId}/audit`} className="next-step">
              <b>Verify the audit trail</b>
              <span>Recompute the hash chain and detect any tampering.</span>
            </Link>
          </div>
          <div className="provenance">
            <Badge tone="warn">Uncalibrated models</Badge> Risk and forecast are heuristics until calibrated on project history.
          </div>
        </Card>
      </div>

      <Card title="Project discussion" meta="Judgement the data cannot hold — recorded, resolvable and audited">
        <CommentThread projectId={projectId} targetType="project" />
      </Card>
    </div>
  );
}
