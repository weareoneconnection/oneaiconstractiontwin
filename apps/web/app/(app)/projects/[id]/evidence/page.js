"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "../../../../../lib/api";
import { dateTime } from "../../../../../lib/format";
import { useSession } from "../../../../../lib/session";
import { Badge, Card, EmptyState, Metric, PermissionButton, Skeleton } from "../../../../../components/ui";
import { useToast } from "../../../../../components/ui/Toast";
import AuthenticatedImage from "../../../../../components/AuthenticatedImage";
import { useProject } from "../layout";

/** The five sources the pilot scenario declares. Order matches how a site produces them. */
const SOURCES = [
  { key: "daily_report", label: "Daily reports", hint: "Shift narrative — what happened and why" },
  { key: "photo", label: "Photos", hint: "Dated by the image's own metadata" },
  { key: "rfi", label: "RFI", hint: "Requests for information" },
  { key: "ncr", label: "NCR", hint: "Non-conformance records" },
  { key: "inspection", label: "Inspections", hint: "Signed acceptance records" },
  { key: "punch_list", label: "Punch lists", hint: "Outstanding work per station or zone" },
];

const CSV_SOURCES = SOURCES.filter(source => source.key !== "photo");

export default function EvidencePage() {
  const { projectId } = useProject();
  const { can } = useSession();
  const { notify } = useToast();

  const [rows, setRows] = useState(null);
  const [cover, setCover] = useState(null);
  const [filter, setFilter] = useState("");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState("");
  const [lastImport, setLastImport] = useState(null);
  const [photoForm, setPhotoForm] = useState({ caption: "", activity_id: "", entity_guid: "" });
  const csvInput = useRef(null);
  const photoInput = useRef(null);
  const pendingSource = useRef("daily_report");

  const load = async () => {
    const params = new URLSearchParams();
    if (filter) params.set("source_type", filter);
    if (query) params.set("q", query);
    const [list, coverage] = await Promise.all([
      api(`/api/v1/projects/${projectId}/evidence?${params}`),
      api(`/api/v1/projects/${projectId}/evidence/coverage`),
    ]);
    setRows(list);
    setCover(coverage);
  };

  useEffect(() => { load().catch(error => notify(error.message, "error")); }, [projectId, filter, query]);

  const importCsv = async file => {
    if (!file) return;
    setBusy("csv");
    try {
      const form = new FormData();
      form.append("file", file);
      const result = await api(
        `/api/v1/projects/${projectId}/evidence/import-csv?source_type=${pendingSource.current}`,
        { method: "POST", body: form }
      );
      setLastImport(result);
      notify(
        `${result.created} new · ${result.duplicates_skipped} already present${result.unusable_rows ? ` · ${result.unusable_rows} unusable` : ""}`,
        result.created ? "success" : "warn"
      );
      await load();
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setBusy("");
      if (csvInput.current) csvInput.current.value = "";
    }
  };

  const uploadPhoto = async file => {
    if (!file) return;
    setBusy("photo");
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("caption", photoForm.caption);
      form.append("activity_id", photoForm.activity_id);
      form.append("entity_guid", photoForm.entity_guid);
      const result = await api(`/api/v1/projects/${projectId}/evidence/photos`, { method: "POST", body: form });
      notify(
        result.duplicate
          ? "This photograph is already on file"
          : `Photo filed${result.exif_found ? ` · taken ${result.taken_at.slice(0, 10)} (from image metadata)` : ""}`,
        result.duplicate ? "warn" : "success"
      );
      setPhotoForm({ caption: "", activity_id: "", entity_guid: "" });
      await load();
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setBusy("");
      if (photoInput.current) photoInput.current.value = "";
    }
  };

  const writable = can("twin:write");

  return (
    <div className="page">
      <div className="grid4">
        <Metric label="Evidence records" value={cover ? cover.total : "—"} sub="Retrievable by Ask Twin" />
        <Metric
          label="Source coverage"
          value={cover ? `${cover.sources_present.length} / ${cover.declared_sources.length}` : "—"}
          tone={cover && cover.coverage_ratio === 1 ? "good" : "warn"}
          sub={cover?.sources_missing.length ? `Missing: ${cover.sources_missing.join(", ")}` : "All declared sources present"}
        />
        <Metric
          label="Linked to records"
          value={cover ? cover.linked_to_project_records : "—"}
          sub="Reference an activity or element"
        />
        <Metric label="Photos" value={cover ? cover.by_source_type?.photo || 0 : "—"} sub="Dated from image metadata" />
      </div>

      {cover?.sources_missing?.length > 0 && (
        <Card title="What this twin cannot answer yet" meta="A missing source is a class of question the twin will correctly refuse">
          <p className="answer-text">
            No <b>{cover.sources_missing.join(", ")}</b> records have been imported for this project.
            Questions that depend on them return as provisional rather than guessed — which is correct,
            but it is a gap in the data, not in the reasoning.
          </p>
        </Card>
      )}

      <Card
        title="Import site records"
        meta="Re-importing the same export is safe: records are matched by content, not by upload"
      >
        <input
          ref={csvInput}
          type="file"
          accept=".csv"
          hidden
          onChange={event => importCsv(event.target.files?.[0])}
        />
        <div className="source-grid">
          {CSV_SOURCES.map(source => (
            <div key={source.key} className="source-card">
              <div>
                <b>{source.label}</b>
                <span>{source.hint}</span>
              </div>
              <div className="source-foot">
                <Badge tone={cover?.by_source_type?.[source.key] ? "good" : "neutral"}>
                  {cover?.by_source_type?.[source.key] || 0}
                </Badge>
                <PermissionButton
                  allowed={writable}
                  permission="twin:write"
                  className="btn"
                  disabled={busy === "csv"}
                  onClick={() => { pendingSource.current = source.key; csvInput.current?.click(); }}
                >
                  {busy === "csv" ? "Importing…" : "Import CSV"}
                </PermissionButton>
              </div>
            </div>
          ))}
        </div>

        <div className="provenance">
          Any column layout is accepted. A content column is required (<code>content</code>, <code>description</code>,
          <code> narrative</code>…); <code>date</code>, <code>activity_id</code>, <code>ifc_guid</code>, <code>zone</code>,
          <code> status</code> and <code>author</code> are used when present.
        </div>

        {lastImport && (
          <div className="import-result">
            <div>
              <b>{lastImport.created}</b> imported · <b>{lastImport.duplicates_skipped}</b> already present ·{" "}
              <b>{lastImport.linked_to_project_records}</b> linked to an activity or element
            </div>
            <small>Columns detected: {(lastImport.detected_columns || []).join(", ")}</small>
            {lastImport.problems?.length > 0 && (
              <ul className="import-problems">
                {lastImport.problems.slice(0, 5).map((problem, index) => <li key={index}>{problem}</li>)}
              </ul>
            )}
          </div>
        )}
      </Card>

      <Card title="Add a photograph" meta="Capture time and position are read from the image itself">
        <input ref={photoInput} type="file" accept="image/*" hidden onChange={event => uploadPhoto(event.target.files?.[0])} />
        <div className="form-row">
          <input
            placeholder="What does this photo show?"
            value={photoForm.caption}
            onChange={event => setPhotoForm({ ...photoForm, caption: event.target.value })}
          />
          <input
            placeholder="Activity id (optional)"
            value={photoForm.activity_id}
            onChange={event => setPhotoForm({ ...photoForm, activity_id: event.target.value })}
          />
          <input
            placeholder="IFC GUID (optional)"
            value={photoForm.entity_guid}
            onChange={event => setPhotoForm({ ...photoForm, entity_guid: event.target.value })}
          />
          <PermissionButton
            allowed={writable}
            permission="twin:write"
            className="btn primary"
            disabled={busy === "photo"}
            onClick={() => photoInput.current?.click()}
          >
            {busy === "photo" ? "Uploading…" : "Choose photo"}
          </PermissionButton>
        </div>
        <div className="provenance">
          A caption is what retrieval can match on — an unlabelled photo is stored, but the twin cannot cite it for anything.
        </div>
      </Card>

      <Card
        title="Evidence"
        meta="Everything Ask Twin can retrieve for this project"
        actions={
          <>
            <select value={filter} onChange={event => setFilter(event.target.value)} aria-label="Filter by source">
              <option value="">All sources</option>
              {SOURCES.map(source => <option key={source.key} value={source.key}>{source.label}</option>)}
            </select>
            <input
              className="search-input"
              placeholder="Search content"
              value={query}
              onChange={event => setQuery(event.target.value)}
            />
          </>
        }
      >
        {!rows && <Skeleton lines={4} />}
        {rows?.length === 0 && (
          <EmptyState
            title={query || filter ? "Nothing matches that filter" : "No evidence yet"}
            description="Import daily reports, RFIs, NCRs or inspection records above. Until then, most questions will correctly come back as provisional."
          />
        )}
        {rows?.length > 0 && (
          <div className="evidence-index">
            {rows.map(row => {
              const links = row.fragment?.links || {};
              return (
                <article key={row.id} className="evidence-row">
                  <header>
                    <b>{row.source_id}</b>
                    <Badge tone="neutral">{row.source_type.replaceAll("_", " ")}</Badge>
                    <span className="confidence" title="Source reliability used to weight retrieval">
                      {(row.confidence * 100).toFixed(0)}%
                    </span>
                    <span className="evidence-date">
                      {row.fragment?.recorded_at ? row.fragment.recorded_at.slice(0, 10)
                        : row.fragment?.taken_at ? row.fragment.taken_at.slice(0, 10)
                        : dateTime(row.created_at)}
                    </span>
                  </header>
                  {row.fragment?.object_key && (
                    <AuthenticatedImage
                      className="evidence-photo"
                      alt={row.content}
                      path={`/api/v1/projects/${projectId}/evidence/${row.id}/image`}
                    />
                  )}
                  <p>{row.content}</p>
                  <footer>
                    {links.activity_ref && (
                      <Badge tone={links.activity_id ? "good" : "warn"}>
                        {links.activity_ref}{links.activity_id ? "" : " · unresolved"}
                      </Badge>
                    )}
                    {links.entity_name && <Badge tone="good">{links.entity_name}</Badge>}
                    {row.fragment?.author && <span>by {row.fragment.author}</span>}
                    {row.fragment?.gps && (
                      <span>{row.fragment.gps.latitude}, {row.fragment.gps.longitude}</span>
                    )}
                    {row.fragment?.taken_at_source === "exif" && <span>capture time from image</span>}
                  </footer>
                </article>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}
