"use client";
import { useEffect, useMemo, useState } from "react";
import TwinViewer from "./TwinViewer";
import FourDTwinWorkspace from "./FourDTwinWorkspace";
import BimScheduleWorkspace from "./BimScheduleWorkspace";
import CesiumStreamingWorkspace from "./CesiumStreamingWorkspace";
import { API, api } from "../lib/api";
import EnterpriseStatus, { ReadinessPanel } from "./EnterpriseStatus";

const pct = n => `${Number(n||0).toFixed(1)}%`;
function Metric({label,value,sub}){return <div className="card metric"><div className="metric-label">{label}</div><div className="metric-value">{value}</div><div className="metric-sub">{sub}</div></div>}

export default function Dashboard(){
  const [projects,setProjects]=useState([]),[project,setProject]=useState(null),[entities,setEntities]=useState([]),[entity,setEntity]=useState(null);
  const [question,setQuestion]=useState("Why was Beam B-023 installed late?"),[answer,setAnswer]=useState(null),[busy,setBusy]=useState(false);
  const [risk,setRisk]=useState(null),[forecast,setForecast]=useState(null),[sim,setSim]=useState(null),[action,setAction]=useState(null),[notice,setNotice]=useState(""),[readiness,setReadiness]=useState(null);
  const load=async()=>{try{const rr=await fetch(`${API}/health/ready`,{cache:'no-store'});setReadiness(await rr.json())}catch{}let ps=await api('/api/v1/projects');if(!ps.length){try{await api('/api/v1/demo/seed',{method:'POST'});ps=await api('/api/v1/projects')}catch{setNotice('No project is available. Create or import an enterprise pilot project.')}}setProjects(ps);const p=ps[0]||null;setProject(p);if(p){const es=await api(`/api/v1/projects/${p.id}/entities`);setEntities(es);setEntity(es[0]||null)}};
  useEffect(()=>{load().catch(e=>setNotice(e.message))},[]);
  const variance=useMemo(()=>project?project.actual_progress-project.planned_progress:0,[project]);
  const run=async(fn)=>{setBusy(true);setNotice("");try{await fn()}catch(e){setNotice(e.message)}finally{setBusy(false)}};
  const ask=()=>run(async()=>setAnswer(await api(`/api/v1/projects/${project.id}/ask`,{method:'POST',body:JSON.stringify({question})})));
  const assess=()=>run(async()=>setRisk(await api(`/api/v1/projects/${project.id}/risks/evaluate`,{method:'POST'})));
  const doForecast=()=>run(async()=>setForecast(await api(`/api/v1/projects/${project.id}/forecast`,{method:'POST'})));
  const simulate=()=>run(async()=>setSim(await api(`/api/v1/projects/${project.id}/simulations`,{method:'POST',body:JSON.stringify({scenario:'Crane C02 unavailable for 7 days',delay_days:7,cost_per_day:60000,recovery_efficiency:.65})})));
  const agent=()=>run(async()=>setAction(await api(`/api/v1/projects/${project.id}/agents/run`,{method:'POST',body:JSON.stringify({agent:'project_director',task:'Review current project status and propose mitigation'})})));
  const upload=async e=>{const f=e.target.files?.[0];if(!f||!project)return;const fd=new FormData();fd.append('file',f);await run(async()=>{const r=await api(`/api/v1/projects/${project.id}/bim/upload`,{method:'POST',body:fd});setNotice(`Uploaded ${r.filename} · ${r.bytes} bytes · ${r.adapter_status}`)})};
  const refreshTwin=async()=>{ if(!project)return; const es=await api(`/api/v1/projects/${project.id}/entities`); setEntities(es); if(es.length && !es.find(x=>x.id===entity?.id)) setEntity(es[0]); };
  if(!project) return <div className="shell"><div className="topbar"><div><div className="brand-kicker">ONEAI LABS · PHYSICAL INTELLIGENCE</div><h1 className="title">Construction Twin v0.7 Enterprise Pilot</h1></div><EnterpriseStatus/></div><div className="card panel"><div className="panel-title">No project loaded</div><div className="result">{notice||'Create a project through the API or enable the local demo seed endpoint.'}</div><a className="btn" href={`${API}/docs`} target="_blank">Open API Docs ↗</a></div></div>;
  const lc=entity?.lifecycle||{}, intel=entity?.intelligence||{};
  return <div className="shell">
    <div className="topbar"><div><div className="brand-kicker">ONEAI LABS · PHYSICAL INTELLIGENCE</div><h1 className="title">Construction Twin v0.7 Enterprise Pilot</h1><div className="subtitle">AI-Native Digital Twin for Construction & Infrastructure · Evidence-first project intelligence</div></div><EnterpriseStatus/></div>
    <div className="grid4"><Metric label="Actual Progress" value={pct(project.actual_progress)} sub={`${project.name} · ${project.code}`}/><Metric label="Plan Variance" value={`${variance.toFixed(1)}%`} sub={`Planned ${pct(project.planned_progress)}`}/><Metric label="Forecast Delay" value={`${project.forecast_delay_days} d`} sub="Current project baseline"/><Metric label="Twin Entities" value={entities.length} sub="Project World Model"/></div>
    <div className="main-grid">
      <div className="card panel"><div className="panel-head"><div><div className="panel-title">3D Twin Viewer</div><div className="panel-meta">Interactive Three.js demonstration surface · IFC ingestion adapter included</div></div><div className="upload"><input id="bim-file" type="file" accept=".ifc,.glb,.gltf,.json" onChange={upload}/><label className="btn" htmlFor="bim-file">Upload BIM</label></div></div><TwinViewer entity={entity}/><div className="timeline"><div style={{width:`${project.actual_progress}%`}}/></div></div>
      <div className="side-stack">
        <div className="card panel"><div className="panel-head"><div className="panel-title">Twin Entities</div><div className="panel-meta">Click to inspect</div></div><div className="entity-list">{entities.map(e=><div key={e.id} className={`entity ${entity?.id===e.id?'active':''}`} onClick={()=>setEntity(e)}><div className="entity-name">{e.name}</div><div className="entity-meta">{e.entity_type} · {e.spatial?.zone||'Unzoned'} · Health {e.intelligence?.healthScore??'--'}</div></div>)}</div></div>
        <div className="card panel"><div className="panel-title">Intelligence Panel</div><div className="info-grid" style={{marginTop:10}}><div className="info-cell"><span>Status</span><b>{lc.actualStatus||'--'}</b></div><div className="info-cell"><span>Progress</span><b>{lc.progress??0}%</b></div><div className="info-cell"><span>Delay</span><b className={(lc.delayDays||0)>0?'warn':'good'}>{lc.delayDays??0} d</b></div><div className="info-cell"><span>Risk</span><b>{intel.riskScore??'--'}</b></div></div><div className="result" style={{marginTop:10}}>{intel.aiSummary||'No AI summary yet.'}</div></div>
      </div>
    </div>
    <ReadinessPanel report={readiness}/><BimScheduleWorkspace project={project} entities={entities} onRefresh={refreshTwin}/><CesiumStreamingWorkspace project={project}/><FourDTwinWorkspace project={project} entities={entities} selectedEntity={entity} onSelect={(id)=>{const found=entities.find(e=>e.id===id);if(found)setEntity(found)}}/><div className="copilot">
      <div className="card panel askbox"><div className="panel-head"><div><div className="panel-title">Ask Twin</div><div className="panel-meta">Evidence-first reasoning over the project world model</div></div><a className="panel-meta" href={`${API}/docs`} target="_blank">API Docs ↗</a></div><textarea value={question} onChange={e=>setQuestion(e.target.value)}/><div className="actions"><button className="btn primary" disabled={busy} onClick={ask}>Ask Twin</button><button className="btn" disabled={busy} onClick={assess}>Risk Scan</button><button className="btn" disabled={busy} onClick={doForecast}>Forecast</button><button className="btn" disabled={busy} onClick={simulate}>Simulate</button><button className="btn" disabled={busy} onClick={agent}>Run Agent</button></div>{notice&&<div className="result">{notice}</div>}{answer&&<div className="result">
        {answer.provisional&&<div className="provisional-badge">PROVISIONAL · no project record matched this question</div>}
        <b>{answer.answer}</b>
        <div className="provenance">Confidence {(answer.confidence*100).toFixed(0)}% · evidence coverage {(answer.evidence_coverage*100).toFixed(0)}% · {answer.reasoning?.model_backed?`model ${answer.reasoning?.model}`:`no model: ${answer.reasoning?.model||'local reasoner'}`} · retrieval {answer.reasoning?.retrieval||'—'}</div>
        {!!answer.claims?.length&&<div className="claims">{answer.claims.map((c,i)=><div key={i} className={c.supported?'claim supported':'claim unsupported'}><span>{c.supported?'SUPPORTED':'UNSUPPORTED'}</span>{c.claim}</div>)}</div>}
        {answer.evidence?.map(ev=><div className="evidence" key={ev.id}><b>{ev.source_type} · {ev.source_id}</b> <small>relevance {ev.relevance?.toFixed(2)} · matched {ev.matched_terms?.join(', ')||'—'}</small><br/>{ev.content}<br/>confidence {(ev.confidence*100).toFixed(0)}%</div>)}
      </div>}</div>
      <div className="side-stack">
        <div className="card panel"><div className="panel-title">Project Intelligence</div><div className="signal-grid"><div className="signal"><h4>Risk Exposure</h4><strong className="warn">{risk?risk.exposure.toFixed(3):'—'}</strong></div><div className="signal"><h4>P50 Delay</h4><strong>{forecast?`${forecast.delay_days.p50}d`:'—'}</strong></div><div className="signal"><h4>Simulation</h4><strong>{sim?`${sim.schedule_impact_days}d`:'—'}</strong></div></div>{risk&&<div className="result"><b>{risk.title}</b><br/>Probability {(risk.probability*100).toFixed(0)}% · Impact {(risk.impact*100).toFixed(0)}%<div className="provenance">{risk.model} · uncalibrated · {risk.sample_size} activities measured ({risk.data_quality})</div></div>}{forecast&&<div className="result">P10 {forecast.delay_days.p10}d · P50 {forecast.delay_days.p50}d · P90 {forecast.delay_days.p90}d<div className="provenance">{forecast.model} · {forecast.basis} · {forecast.sample?.activities_measured} activities</div>{forecast.warning&&<div className="provisional-badge">{forecast.warning}</div>}</div>}{action&&<div className="result"><b>Agent action</b><br/>{action.agent} · {action.status}<br/>{action.payload?.recommendation}</div>}</div>
      </div>
    </div>
    <div className="footer"><span>v0.7 Enterprise Pilot · OneAI Core · OneForge · OneField · TheOne/OneClaw boundaries preserved</span><span>No AI conclusion without evidence.</span></div>
  </div>
}
