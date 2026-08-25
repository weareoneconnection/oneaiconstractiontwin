"use client";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";

/** Lets the operator move between projects without returning to the portfolio. */
export default function ProjectSwitcher({ currentId }) {
  const [projects, setProjects] = useState([]);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    api("/api/v1/projects").then(setProjects).catch(() => setProjects([]));
  }, []);

  if (!currentId) {
    // The bar titles whatever the route is actually showing, not always the portfolio.
    const title = pathname.startsWith("/admin") ? "Platform" : "Projects";
    const subtitle = pathname.startsWith("/admin")
      ? "Readiness, workers and deployment state"
      : projects.length
        ? `${projects.length} in this organization`
        : "Portfolio";
    return (
      <div className="workspace-title">
        <h1>{title}</h1>
        <span>{subtitle}</span>
      </div>
    );
  }

  const current = projects.find(project => project.id === currentId);
  return (
    <div className="workspace-title">
      <h1>{current?.name || "Project"}</h1>
      <div className="switcher-row">
        <span>{current?.code || currentId.slice(0, 8)}</span>
        {projects.length > 1 && (
          <select
            aria-label="Switch project"
            value={currentId}
            onChange={event => router.push(`/projects/${event.target.value}`)}
          >
            {projects.map(project => (
              <option key={project.id} value={project.id}>{project.name} · {project.code}</option>
            ))}
          </select>
        )}
      </div>
    </div>
  );
}
