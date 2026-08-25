"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "../../../../../lib/api";
import { bytes, dateTime } from "../../../../../lib/format";
import { useSession } from "../../../../../lib/session";
import { Card, EmptyState, PermissionButton, Skeleton } from "../../../../../components/ui";
import { useToast } from "../../../../../components/ui/Toast";
import CesiumStreamingWorkspace from "../../../../../components/CesiumStreamingWorkspace";
import TwinViewer from "../../../../../components/TwinViewer";
import { useProject } from "../layout";

export default function ModelPage() {
  const { project, entities, projectId, reload } = useProject();
  const { can } = useSession();
  const { notify } = useToast();
  const [models, setModels] = useState(null);
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef(null);

  const loadModels = () => api(`/api/v1/projects/${projectId}/bim/models`).then(setModels).catch(() => setModels([]));
  useEffect(() => { loadModels(); }, [projectId]);

  const importIfc = async file => {
    if (!file) return;
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const result = await api(`/api/v1/projects/${projectId}/bim/import-ifc`, { method: "POST", body: form });
      notify(`Imported ${result.element_count ?? "?"} elements with the ${result.parser} parser`, "success");
      await Promise.all([loadModels(), reload()]);
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  return (
    <div className="page">
      <Card
        title="IFC models"
        meta="Semantic ingestion creates Twin Entities; geometry feeds the 3D Tiles pipeline"
        actions={
          <>
            <input ref={fileInput} id="ifc-input" type="file" accept=".ifc" hidden onChange={e => importIfc(e.target.files?.[0])} />
            <PermissionButton allowed={can("twin:write")} permission="twin:write" className="btn primary" onClick={() => fileInput.current?.click()} disabled={uploading}>
              {uploading ? "Importing…" : "Import IFC"}
            </PermissionButton>
          </>
        }
      >
        {!models && <Skeleton lines={2} />}
        {models && models.length === 0 && (
          <EmptyState title="No model imported" description="Import an IFC file to populate the Project World Model. A transparent STEP fallback parser is used when IfcOpenShell is unavailable." />
        )}
        {models && models.length > 0 && (
          <div className="table">
            <div className="table-head">
              <span>Model</span><span>Parser</span><span>Elements</span><span>Storage</span><span>Imported</span>
            </div>
            {models.map(model => (
              <div key={model.id} className="table-row">
                <span><b>{model.title}</b></span>
                <span>{model.meta?.parser || "—"}</span>
                <span>{model.meta?.element_count ?? 0}</span>
                <span>{model.meta?.storage_backend || "—"}</span>
                <span>{dateTime(model.created_at)}</span>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="Twin viewer" meta="Interactive demonstration surface over the imported entities">
        {entities.length === 0
          ? <EmptyState title="Nothing to display yet" description="Import an IFC model first." />
          : <TwinViewer entity={entities[0]} />}
      </Card>

      <CesiumStreamingWorkspace project={project} />
    </div>
  );
}
