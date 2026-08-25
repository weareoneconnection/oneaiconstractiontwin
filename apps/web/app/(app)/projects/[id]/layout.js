"use client";
import { createContext, use, useCallback, useContext, useEffect, useState } from "react";
import { api } from "../../../../lib/api";
import { Card, ErrorBoundary, Skeleton } from "../../../../components/ui";

const ProjectContext = createContext({ project: null, entities: [], reload: () => {} });
export const useProject = () => useContext(ProjectContext);

export default function ProjectLayout({ children, params }) {
  const { id } = use(params);
  const [state, setState] = useState({ project: null, entities: [], loading: true, error: "" });

  const reload = useCallback(async () => {
    try {
      const [project, entities] = await Promise.all([
        api(`/api/v1/projects/${id}`),
        api(`/api/v1/projects/${id}/entities`),
      ]);
      setState({ project, entities, loading: false, error: "" });
    } catch (error) {
      setState({ project: null, entities: [], loading: false, error: error.message });
    }
  }, [id]);

  useEffect(() => { reload(); }, [reload]);

  if (state.loading) return <div className="page"><Card title="Loading project…"><Skeleton lines={5} /></Card></div>;
  if (state.error) {
    return (
      <div className="page">
        <Card title="Project unavailable" meta="A project outside your tenant returns 404 by design.">
          <div className="result">{state.error}</div>
        </Card>
      </div>
    );
  }

  return (
    <ProjectContext.Provider value={{ ...state, projectId: id, reload }}>
      <ErrorBoundary>{children}</ErrorBoundary>
    </ProjectContext.Provider>
  );
}
