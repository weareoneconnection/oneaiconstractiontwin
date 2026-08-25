"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../../lib/api";
import { percent } from "../../../lib/format";
import { Badge, Card, EmptyState, Metric, Skeleton } from "../../../components/ui";

const COLUMNS = [
  { key: "name", label: "Project", sort: row => row.name },
  { key: "variance", label: "Variance", sort: row => row.variance },
  { key: "actual_progress", label: "Actual", sort: row => row.actual_progress },
  { key: "forecast_delay_days", label: "Baseline delay", sort: row => row.forecast_delay_days },
  { key: "late", label: "Late activities", sort: row => row.schedule.late },
  { key: "worst", label: "Worst slip", sort: row => row.schedule.worst_slip_days },
  { key: "evidence", label: "Evidence", sort: row => row.counts.evidence },
];

export default function ComparePage() {
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState("");
  const [sort, setSort] = useState({ key: "variance", direction: "asc" });

  useEffect(() => {
    api("/api/v1/portfolio/summary").then(setSummary).catch(e => setError(e.message));
  }, []);

  const rows = useMemo(() => {
    if (!summary) return [];
    const column = COLUMNS.find(item => item.key === sort.key) || COLUMNS[1];
    const sorted = [...summary.projects].sort((a, b) => {
      const left = column.sort(a);
      const right = column.sort(b);
      if (typeof left === "string") return left.localeCompare(right);
      return left - right;
    });
    return sort.direction === "asc" ? sorted : sorted.reverse();
  }, [summary, sort]);

  // Bars are scaled against the worst case in view, so a portfolio of small variances
  // is not drawn as if it were in crisis.
  const worstVariance = Math.max(1, ...rows.map(row => Math.abs(row.variance)));
  const worstSlip = Math.max(1, ...rows.map(row => row.schedule.worst_slip_days));

  const toggle = key => setSort(current => ({
    key,
    direction: current.key === key && current.direction === "asc" ? "desc" : "asc",
  }));

  return (
    <div className="page">
      {error && <Card title="Comparison unavailable"><div className="result">{error}</div></Card>}
      {!summary && !error && <Card title="Comparing projects…"><Skeleton lines={5} /></Card>}

      {summary && (
        <>
          <div className="grid4">
            <Metric label="Projects" value={summary.project_count} sub="In this organization" />
            <Metric label="Behind baseline" value={summary.totals.behind_baseline} tone={summary.totals.behind_baseline ? "warn" : "good"} sub={`Worst variance ${summary.worst_variance}%`} />
            <Metric label="Late activities" value={summary.totals.late_activities} tone={summary.totals.late_activities ? "warn" : "good"} sub="Across all schedules" />
            <Metric label="Evidence records" value={summary.totals.evidence} sub="Available to Ask Twin" />
          </div>

          <Card title="Project comparison" meta="Sortable. Schedule metrics are measured, not estimated.">
            {rows.length === 0 && <EmptyState title="No projects to compare" description="Create a second project to see them side by side." />}
            {rows.length > 0 && (
              <div className="table compare-table">
                <div className="table-head">
                  {COLUMNS.map(column => (
                    <span key={column.key} className="sortable" onClick={() => toggle(column.key)}>
                      {column.label}{sort.key === column.key ? (sort.direction === "asc" ? " ↑" : " ↓") : ""}
                    </span>
                  ))}
                </div>
                {rows.map(row => (
                  <Link key={row.id} href={`/projects/${row.id}`} className="table-row">
                    <span data-label="Project">
                      <b>{row.name}</b>
                      <small className="muted-inline">{row.code}</small>
                    </span>
                    <span data-label="Variance">
                      <div className="bar-cell">
                        <div className={`bar ${row.variance < 0 ? "bad" : "good"}`} style={{ width: `${(Math.abs(row.variance) / worstVariance) * 100}%` }} />
                        <b className={row.variance < 0 ? "warn" : "good"}>{row.variance > 0 ? "+" : ""}{row.variance}%</b>
                      </div>
                    </span>
                    <span data-label="Actual">{percent(row.actual_progress)}</span>
                    <span data-label="Baseline delay">{row.forecast_delay_days} d</span>
                    <span data-label="Late activities">
                      {row.schedule.late}
                      {row.schedule.critical_late > 0 && <Badge tone="warn">{row.schedule.critical_late} critical</Badge>}
                    </span>
                    <span data-label="Worst slip">
                      <div className="bar-cell">
                        <div className="bar warn" style={{ width: `${(row.schedule.worst_slip_days / worstSlip) * 100}%` }} />
                        <b>{row.schedule.worst_slip_days} d</b>
                      </div>
                    </span>
                    <span data-label="Evidence">
                      {row.counts.evidence}
                      {row.schedule.data_quality === "insufficient" && <Badge tone="warn">thin data</Badge>}
                    </span>
                  </Link>
                ))}
              </div>
            )}
            <div className="provenance">{summary.note}</div>
          </Card>

          <Card title="Data coverage" meta="A project cannot be compared on evidence it does not have">
            <div className="coverage-grid">
              {rows.map(row => (
                <div key={row.id} className="coverage-row">
                  <b>{row.code}</b>
                  {["twin_entities", "activities", "evidence", "risks", "asset_jobs"].map(key => (
                    <div key={key} className={`coverage-cell ${row.counts[key] ? "has" : "none"}`}>
                      <span>{key.replaceAll("_", " ")}</span>
                      <b>{row.counts[key]}</b>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
