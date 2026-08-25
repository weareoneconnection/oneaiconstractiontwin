"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

function Upload({accept,label,onUpload}){
  return <label className="btn upload-v03">{label}<input hidden type="file" accept={accept} onChange={e=>{const f=e.target.files?.[0]; if(f) onUpload(f); e.target.value="";}}/></label>
}

export default function BimScheduleWorkspace({project, entities, onRefresh}){
  const [models,setModels]=useState([]),[activities,setActivities]=useState([]),[mappings,setMappings]=useState([]),[busy,setBusy]=useState(false),[notice,setNotice]=useState("");
  async function refresh(){ if(!project) return; const [m,a,map]=await Promise.all([api(`/api/v1/projects/${project.id}/bim/models`),api(`/api/v1/projects/${project.id}/activities`),api(`/api/v1/projects/${project.id}/mappings`)]); setModels(m);setActivities(a);setMappings(map); }
  useEffect(()=>{refresh().catch(e=>setNotice(e.message))},[project?.id]);
  async function up(path,file){setBusy(true);setNotice("");try{const fd=new FormData();fd.append("file",file);const r=await api(path,{method:"POST",body:fd});setNotice(JSON.stringify(r));await refresh();await onRefresh?.();}catch(e){setNotice(e.message)}finally{setBusy(false)}}
  async function autoMap(){setBusy(true);setNotice("");try{const r=await api(`/api/v1/projects/${project.id}/mappings/auto?threshold=0.18`,{method:"POST"});setNotice(`Created ${r.mappings_created} mappings`);await refresh();await onRefresh?.();}catch(e){setNotice(e.message)}finally{setBusy(false)}}
  return <div className="card panel v03-workspace">
    <div className="panel-head"><div><div className="panel-title">BIM ↔ Schedule Workspace · v0.3</div><div className="panel-meta">IFC semantic ingestion → Twin Entities → Schedule import → confidence-scored mapping</div></div><div className="actions">
      <Upload accept=".ifc" label="Import IFC" onUpload={f=>up(`/api/v1/projects/${project.id}/bim/import-ifc`,f)}/>
      <Upload accept=".csv" label="Import Schedule CSV" onUpload={f=>up(`/api/v1/projects/${project.id}/schedules/import-csv`,f)}/>
      <button className="btn primary" disabled={busy||!activities.length||!entities.length} onClick={autoMap}>Auto Map</button>
    </div></div>
    <div className="grid4 v03-metrics"><div className="metric"><span>IFC Models</span><strong>{models.length}</strong></div><div className="metric"><span>Twin Entities</span><strong>{entities.length}</strong></div><div className="metric"><span>Activities</span><strong>{activities.length}</strong></div><div className="metric"><span>Mappings</span><strong>{mappings.length}</strong></div></div>
    {notice&&<div className="result compact">{notice}</div>}
    <div className="mapping-grid"><div><div className="panel-title small">Imported Models</div>{models.length?models.map(m=><div className="map-row" key={m.id}><b>{m.title}</b><span>{m.meta?.parser} · {m.meta?.element_count||0} entities</span></div>):<div className="panel-meta">Import an IFC model to create Twin Entities.</div>}</div>
    <div><div className="panel-title small">Schedule Activities</div>{activities.slice(0,8).map(a=><div className="map-row" key={a.id}><b>{a.external_id}</b><span>{a.name} · {a.percent_complete}%</span></div>)}</div>
    <div><div className="panel-title small">Mapping Confidence</div>{mappings.slice(0,8).map(m=><div className="map-row" key={m.id}><b>{m.source?.name||m.source?.entity_id}</b><span>→ {m.target?.name||m.target?.activity_id} · {(m.confidence*100).toFixed(0)}%</span></div>)}</div></div>
  </div>
}
