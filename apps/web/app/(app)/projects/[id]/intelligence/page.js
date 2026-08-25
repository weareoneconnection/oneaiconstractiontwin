"use client";
import { useState } from "react";
import { api } from "../../../../../lib/api";
import { useSession } from "../../../../../lib/session";
import { Badge, Card, EmptyState, PermissionButton } from "../../../../../components/ui";
import { useToast } from "../../../../../components/ui/Toast";
import CommentThread from "../../../../../components/CommentThread";
import { useProject } from "../layout";

/** Every AI-derived number is shown with how it was produced. */
function Provenance({ children }) {
  return <div className="provenance">{children}</div>;
}

function AnswerPanel({ answer }) {
  if (!answer) return null;
  const reasoning = answer.reasoning || {};
  return (
    <div className="result answer">
      {answer.provisional && (
        <div className="provisional-badge">
          PROVISIONAL · no project record matched this question. Not a basis for a contractual decision.
        </div>
      )}
      <p className="answer-text">{answer.answer}</p>
      <Provenance>
        Confidence {(answer.confidence * 100).toFixed(0)}% · evidence coverage {(answer.evidence_coverage * 100).toFixed(0)}% ·{" "}
        {reasoning.model_backed ? `model ${reasoning.model}` : `no model: ${reasoning.model || "local reasoner"}`} · retrieval {reasoning.retrieval || "—"} ·{" "}
        {reasoning.schedule_sample_size ?? 0} activities measured
      </Provenance>

      {answer.claims?.length > 0 && (
        <div className="claims">
          {answer.claims.map((claim, index) => (
            <div key={index} className={`claim ${claim.supported ? "supported" : "unsupported"}`}>
              <span>{claim.supported ? "SUPPORTED" : "UNSUPPORTED"}</span>
              {claim.claim}
              <small> · {claim.basis}</small>
            </div>
          ))}
        </div>
      )}

      {answer.evidence?.length > 0 && (
        <div className="evidence-list">
          {answer.evidence.map(item => (
            <div key={item.id} className="evidence">
              <div className="evidence-head">
                <b>{item.source_type} · {item.source_id}</b>
                <span>relevance {item.relevance?.toFixed(2)} · confidence {(item.confidence * 100).toFixed(0)}%</span>
              </div>
              {item.content}
              {item.matched_terms?.length > 0 && <div className="matched">matched: {item.matched_terms.join(", ")}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function IntelligencePage() {
  const { projectId } = useProject();
  const { can } = useSession();
  const { notify } = useToast();
  const [question, setQuestion] = useState("Why is the roof steel work behind schedule?");
  const [answer, setAnswer] = useState(null);
  const [risk, setRisk] = useState(null);
  const [forecast, setForecast] = useState(null);
  const [simulation, setSimulation] = useState(null);
  const [action, setAction] = useState(null);
  const [busy, setBusy] = useState("");

  const run = async (label, work) => {
    setBusy(label);
    try { await work(); }
    catch (error) { notify(error.message, "error"); }
    finally { setBusy(""); }
  };

  const ask = () => run("ask", async () => {
    const result = await api(`/api/v1/projects/${projectId}/ask`, { method: "POST", body: JSON.stringify({ question }) });
    setAnswer(result);
    if (result.provisional) notify("No matching record — the answer is marked provisional", "warn");
  });

  const evaluateRisk = () => run("risk", async () => setRisk(await api(`/api/v1/projects/${projectId}/risks/evaluate`, { method: "POST" })));
  const runForecast = () => run("forecast", async () => setForecast(await api(`/api/v1/projects/${projectId}/forecast`, { method: "POST" })));
  const simulate = () => run("simulate", async () => setSimulation(await api(`/api/v1/projects/${projectId}/simulations`, {
    method: "POST",
    body: JSON.stringify({ scenario: "Crane unavailable for 7 days", delay_days: 7, cost_per_day: 60000, recovery_efficiency: 0.65 }),
  })));
  const runAgent = () => run("agent", async () => setAction(await api(`/api/v1/projects/${projectId}/agents/run`, {
    method: "POST",
    body: JSON.stringify({ agent: "project_director", task: "Propose a schedule recovery action" }),
  })));
  const approve = () => run("approve", async () => {
    const approved = await api(`/api/v1/actions/${action.id}/approve`, { method: "POST" });
    setAction(approved);
    notify("Action approved and recorded in the audit chain", "success");
  });

  const aiAllowed = can("ai:run");

  return (
    <div className="page">
      <Card title="Ask Twin" meta="Evidence-first reasoning over this project's own records">
        <textarea value={question} onChange={event => setQuestion(event.target.value)} rows={3} />
        <div className="actions">
          <PermissionButton allowed={aiAllowed} permission="ai:run" className="btn primary" onClick={ask} disabled={!!busy}>
            {busy === "ask" ? "Retrieving…" : "Ask Twin"}
          </PermissionButton>
          <PermissionButton allowed={aiAllowed} permission="ai:run" className="btn" onClick={evaluateRisk} disabled={!!busy}>Risk scan</PermissionButton>
          <PermissionButton allowed={aiAllowed} permission="ai:run" className="btn" onClick={runForecast} disabled={!!busy}>Forecast</PermissionButton>
          <PermissionButton allowed={aiAllowed} permission="ai:run" className="btn" onClick={simulate} disabled={!!busy}>Simulate</PermissionButton>
          <PermissionButton allowed={aiAllowed} permission="ai:run" className="btn" onClick={runAgent} disabled={!!busy}>Run agent</PermissionButton>
        </div>
        {!answer && !busy && <EmptyState title="No question asked yet" description="Answers cite the records they rest on. When nothing matches, the response is returned as provisional rather than guessed." />}
        <AnswerPanel answer={answer} />
      </Card>

      <div className="two-column">
        <Card title="Risk" meta="Computed from measured activity slippage">
          {!risk && <EmptyState title="Not evaluated" description="Run a risk scan to compute exposure from the current schedule." />}
          {risk && (
            <>
              <div className="signal-grid">
                <div className="signal card"><h4>Exposure</h4><strong className="warn">{risk.exposure.toFixed(3)}</strong></div>
                <div className="signal card"><h4>Probability</h4><strong>{(risk.probability * 100).toFixed(0)}%</strong></div>
                <div className="signal card"><h4>Impact</h4><strong>{(risk.impact * 100).toFixed(0)}%</strong></div>
              </div>
              <Provenance>
                {risk.model} · {risk.calibrated ? "calibrated" : "uncalibrated"} · {risk.sample_size} activities measured ({risk.data_quality})
              </Provenance>
              <div className="list-block">
                <b>Causes</b>
                {risk.causes?.map((cause, index) => <div key={index} className="list-item">{cause}</div>)}
              </div>
              <div className="list-block">
                <b>Mitigations</b>
                {risk.mitigations?.map((item, index) => (
                  <div key={index} className="list-item">{item.name} · recovers ~{item.expected_recovery_days} d <small>({item.basis})</small></div>
                ))}
              </div>
            </>
          )}
        </Card>

        <Card title="Forecast" meta="Bootstrap over this project's own activity variance">
          {!forecast && <EmptyState title="Not forecast yet" description="P10/P50/P90 are resampled from measured slippage, not from a fixed distribution." />}
          {forecast && (
            <>
              <div className="signal-grid">
                <div className="signal card"><h4>P10</h4><strong>{forecast.delay_days.p10} d</strong></div>
                <div className="signal card"><h4>P50</h4><strong className="warn">{forecast.delay_days.p50} d</strong></div>
                <div className="signal card"><h4>P90</h4><strong className="bad">{forecast.delay_days.p90} d</strong></div>
              </div>
              {forecast.warning && <div className="provisional-badge">{forecast.warning}</div>}
              <Provenance>
                {forecast.model} · {forecast.basis} · {forecast.sample.activities_measured}/{forecast.sample.activities_total} activities ·
                mean slip {forecast.sample.mean_slip_days} d · {forecast.iterations} iterations
              </Provenance>
              {forecast.drivers?.length > 0 && (
                <div className="list-block">
                  <b>Drivers</b>
                  {forecast.drivers.map((driver, index) => (
                    <div key={index} className="list-item">
                      {driver.activity} · {driver.name} · slipped {driver.slip_days} d {driver.critical && <Badge tone="warn">critical</Badge>}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </Card>
      </div>

      <div className="two-column">
        <Card title="Scenario simulation" meta="Planning assumptions, returned with the result">
          {!simulation && <EmptyState title="No scenario run" description="Runs a what-if against a stated assumption set." />}
          {simulation && (
            <>
              <div className="signal-grid">
                <div className="signal card"><h4>Schedule impact</h4><strong>{simulation.schedule_impact_days} d</strong></div>
                <div className="signal card"><h4>Cost impact</h4><strong>{simulation.cost_impact.toLocaleString()}</strong></div>
                <div className="signal card"><h4>Risk delta</h4><strong>{simulation.risk_delta}</strong></div>
              </div>
              <div className="table compact">
                <div className="table-head"><span>Option</span><span>Cost</span><span>Recovery</span></div>
                {simulation.options.map(option => (
                  <div key={option.name} className="table-row">
                    <span>{option.name}</span>
                    <span>{option.cost.toLocaleString()}</span>
                    <span>{option.recovery_days} d</span>
                  </div>
                ))}
              </div>
              <Provenance>{simulation.model} · {simulation.calibrated ? "calibrated" : "uncalibrated assumption set"}</Provenance>
            </>
          )}
        </Card>

        <Card title="Agent recommendation" meta="The agent proposes; a human approves. It never acts on its own.">
          {!action && <EmptyState title="No recommendation" description="Recommendations name the activity, slippage and float they are based on." />}
          {action && (
            <>
              <div className="agent-line">
                <b>{action.agent}</b>
                <Badge tone={action.status === "approved" ? "good" : "warn"}>{action.status}</Badge>
              </div>
              <p className="answer-text">{action.payload?.recommendation}</p>
              <Provenance>
                grounded in {action.payload?.grounded_in?.activities_measured ?? 0} activities ·
                {action.payload?.grounded_in?.late_activities ?? 0} late ·
                target {action.payload?.grounded_in?.target_activity || "none"}
              </Provenance>
              {action.status !== "approved" && (
                <PermissionButton allowed={can("action:approve")} permission="action:approve" className="btn primary" onClick={approve} disabled={!!busy}>
                  Approve this action
                </PermissionButton>
              )}
              {/* Approval is a decision; the reasoning behind it belongs next to it. */}
              <CommentThread projectId={projectId} targetType="agent_action" targetId={action.id} title="Review notes" compact />
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
