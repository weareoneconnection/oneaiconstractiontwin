"use client";
import { use, useEffect, useState } from "react";
import { api, download } from "../../../../../lib/api";
import { date, dateTime, percent } from "../../../../../lib/format";
import { Card, Skeleton } from "../../../../../components/ui";
import { useToast } from "../../../../../components/ui/Toast";

const DATASETS = ["activities", "entities", "evidence", "risks", "comments", "audit"];

/**
 * A printable status report.
 *
 * Print to PDF rather than generating one server-side: the layout stays in one place,
 * the reader gets the same content they saw on screen, and no PDF toolchain has to be
 * carried in the API image. The disclosure block is part of the report, not a footnote.
 */
export default function ReportPage({ params }) {
  const { id } = use(params);
  const { notify } = useToast();
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api(`/api/v1/projects/${id}/report`).then(setReport).catch(e => setError(e.message));
  }, [id]);

  const exportCsv = async dataset => {
    try {
      const filename = await download(`/api/v1/projects/${id}/exports/${dataset}.csv`);
      notify(`Exported ${filename}`, "success");
    } catch (e) {
      notify(e.message, "error");
    }
  };

  if (error) return <div className="page"><Card title="Report unavailable"><div className="result">{error}</div></Card></div>;
  if (!report) return <div className="page"><Card title="Building report…"><Skeleton lines={6} /></Card></div>;

  const { project, schedule, counts, latest_risk: risk } = report;

  return (
    <div className="page">
      <div className="no-print">
        <Card title="Export" meta="CSV exports are audited: what left the system, and how many rows">
          <div className="actions">
            <button className="btn primary" onClick={() => window.print()}>Print / Save as PDF</button>
            {DATASETS.map(dataset => (
              <button key={dataset} className="btn" onClick={() => exportCsv(dataset)}>{dataset}.csv</button>
            ))}
          </div>
        </Card>
      </div>

      <article className="report-sheet">
        <header className="report-head">
          <div>
            <div className="brand-kicker">ONEAI CONSTRUCTION TWIN</div>
            <h1>{project.name}</h1>
            <div className="report-sub">{project.code} · status report</div>
          </div>
          <div className="report-stamp">
            <div>Generated {dateTime(report.generated_at)}</div>
            <div>By {report.generated_by.user_id} · {report.generated_by.role}</div>
            <div>v{report.app_version}</div>
          </div>
        </header>

        <section className="report-metrics">
          <div><span>Actual progress</span><b>{percent(project.actual_progress)}</b></div>
          <div><span>Planned</span><b>{percent(project.planned_progress)}</b></div>
          <div><span>Variance</span><b className={project.variance < 0 ? "warn" : "good"}>{project.variance > 0 ? "+" : ""}{project.variance}%</b></div>
          <div><span>Baseline delay</span><b>{project.forecast_delay_days} d</b></div>
        </section>

        <section>
          <h2>Scope in the twin</h2>
          <div className="report-metrics">
            {Object.entries(counts).map(([key, value]) => (
              <div key={key}><span>{key.replaceAll("_", " ")}</span><b>{value}</b></div>
            ))}
          </div>
        </section>

        <section>
          <h2>Schedule performance</h2>
          <p className="report-note">
            {schedule.measured} activities measured ({schedule.data_quality} for calibration) ·
            mean slip {schedule.mean_slip_days} d · critical-path mean slip {schedule.critical_mean_slip_days} d
          </p>
          {schedule.late.length === 0 ? (
            <p className="report-note">No activity is recorded as behind plan.</p>
          ) : (
            <table className="report-table">
              <thead><tr><th>Activity</th><th>Name</th><th>Slip</th><th>Float</th><th>State</th></tr></thead>
              <tbody>
                {schedule.late.map((item, index) => (
                  <tr key={`${item.external_id}-${index}`}>
                    <td>{item.external_id}{item.critical ? " ★" : ""}</td>
                    <td>{item.name}</td>
                    <td>{item.slip_days} d</td>
                    <td>{item.float_days} d</td>
                    <td>{item.state.replaceAll("_", " ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="report-note">★ marks activities on the critical path.</p>
        </section>

        {risk && (
          <section>
            <h2>Latest risk assessment</h2>
            <p className="report-note">
              <b>{risk.title}</b> · probability {(risk.probability * 100).toFixed(0)}% · impact {(risk.impact * 100).toFixed(0)}% ·
              exposure {risk.exposure} · assessed {date(risk.created_at)}
            </p>
            <ul className="report-list">
              {(risk.causes || []).map((cause, index) => <li key={index}>{cause}</li>)}
            </ul>
            <h3>Proposed mitigations</h3>
            <ul className="report-list">
              {(risk.mitigations || []).map((item, index) => (
                <li key={index}>{item.name} — expected recovery {item.expected_recovery_days} d <em>({item.basis})</em></li>
              ))}
            </ul>
          </section>
        )}

        {report.open_comments.length > 0 && (
          <section>
            <h2>Open discussion</h2>
            <ul className="report-list">
              {report.open_comments.map(comment => (
                <li key={comment.id}><b>{comment.author_id}</b> ({comment.author_role}) — {comment.body}</li>
              ))}
            </ul>
          </section>
        )}

        <footer className="report-disclosure">{report.disclosure}</footer>
      </article>
    </div>
  );
}
