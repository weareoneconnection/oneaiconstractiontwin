"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { percent } from "../../lib/format";
import { useSession } from "../../lib/session";
import { Card, EmptyState, Metric, PermissionButton, Skeleton } from "../../components/ui";
import { useToast } from "../../components/ui/Toast";

export default function PortfolioPage() {
  const { can } = useSession();
  const { notify } = useToast();
  const [projects, setProjects] = useState(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({ name: "", code: "", description: "" });

  const load = () => api("/api/v1/projects").then(setProjects).catch(e => setError(e.message));
  useEffect(() => { load(); }, []);

  const create = async event => {
    event.preventDefault();
    setCreating(true);
    try {
      const created = await api("/api/v1/projects", { method: "POST", body: JSON.stringify(draft) });
      notify(`Project ${created.code} created`, "success");
      setDraft({ name: "", code: "", description: "" });
      await load();
    } catch (e) {
      notify(e.message, "error");
    } finally {
      setCreating(false);
    }
  };

  const visible = (projects || []).filter(project =>
    `${project.name} ${project.code} ${project.description}`.toLowerCase().includes(query.toLowerCase())
  );

  const behind = (projects || []).filter(p => p.actual_progress < p.planned_progress).length;
  const delayed = (projects || []).reduce((total, p) => total + (p.forecast_delay_days > 0 ? 1 : 0), 0);

  return (
    <div className="page">
      {projects && projects.length > 0 && (
        <div className="grid4">
          <Metric label="Projects" value={projects.length} sub="In this organization" />
          <Metric label="Behind baseline" value={behind} sub={`${projects.length - behind} on or ahead of plan`} tone={behind ? "warn" : "good"} />
          <Metric label="With forecast delay" value={delayed} sub="Recorded baseline delay > 0" tone={delayed ? "warn" : "good"} />
          <Metric label="Evidence policy" value="Enforced" sub="No AI conclusion without evidence" tone="good" />
        </div>
      )}

      <Card
        title="Projects"
        meta="Every project is scoped to your tenant and organization"
        actions={
          <input
            className="search-input"
            placeholder="Filter by name or code"
            value={query}
            onChange={event => setQuery(event.target.value)}
          />
        }
      >
        {error && <div className="result">{error}</div>}
        {!projects && !error && <Skeleton lines={4} />}
        {projects && visible.length === 0 && (
          <EmptyState
            title={query ? "No project matches that filter" : "No projects yet"}
            description={
              query
                ? "Clear the filter to see everything in this organization."
                : "Create a project to start importing an IFC model and a baseline schedule."
            }
          />
        )}
        {visible.length > 0 && (
          <div className="project-grid">
            {visible.map(project => {
              const variance = project.actual_progress - project.planned_progress;
              return (
                <Link key={project.id} href={`/projects/${project.id}`} className="project-card">
                  <div className="project-card-head">
                    <b>{project.name}</b>
                    <span className="ui-badge neutral">{project.code}</span>
                  </div>
                  <p>{project.description || "No description"}</p>
                  <div className="project-card-metrics">
                    <div><span>Actual</span><b>{percent(project.actual_progress)}</b></div>
                    <div><span>Planned</span><b>{percent(project.planned_progress)}</b></div>
                    <div>
                      <span>Variance</span>
                      <b className={variance < 0 ? "warn" : "good"}>{variance >= 0 ? "+" : ""}{variance.toFixed(1)}%</b>
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </Card>

      <Card title="New project" meta="Requires the project:write permission">
        <form className="form-row" onSubmit={create}>
          <input required placeholder="Project name" value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} />
          <input required placeholder="Code (e.g. STN02)" value={draft.code} onChange={e => setDraft({ ...draft, code: e.target.value })} />
          <input placeholder="Description" value={draft.description} onChange={e => setDraft({ ...draft, description: e.target.value })} />
          <PermissionButton allowed={can("project:write")} permission="project:write" className="btn primary" type="submit" disabled={creating}>
            {creating ? "Creating…" : "Create project"}
          </PermissionButton>
        </form>
      </Card>
    </div>
  );
}
