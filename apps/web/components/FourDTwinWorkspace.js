"use client";
import { useEffect, useMemo, useState } from "react";
import RealTwinViewer from "./RealTwinViewer";
import { api } from "../lib/api";

function toDateRange(start,end){
  if(!start||!end) return [];
  const a=new Date(`${start}T00:00:00`), b=new Date(`${end}T00:00:00`), out=[];
  for(let d=new Date(a); d<=b; d.setDate(d.getDate()+1)) out.push(d.toISOString().slice(0,10));
  return out;
}

export default function FourDTwinWorkspace({project, entities, selectedEntity, onSelect}){
  const [models,setModels]=useState([]),[geometry,setGeometry]=useState(null),[bounds,setBounds]=useState(null),[state,setState]=useState(null),[idx,setIdx]=useState(0),[playing,setPlaying]=useState(false),[notice,setNotice]=useState("");
  const dates=useMemo(()=>bounds?toDateRange(bounds.start,bounds.end):[],[bounds]);
  const currentDate=dates[Math.min(idx,Math.max(0,dates.length-1))];
  async function load(){
    if(!project) return;
    const [m,b]=await Promise.all([api(`/api/v1/projects/${project.id}/bim/models`),api(`/api/v1/projects/${project.id}/timeline`)]);
    setModels(m); setBounds(b);
    if(m[0]) setGeometry(await api(`/api/v1/projects/${project.id}/bim/models/${m[0].id}/geometry`));
  }
  useEffect(()=>{load().catch(e=>setNotice(e.message))},[project?.id,entities.length]);
  useEffect(()=>{if(!project||!currentDate)return; api(`/api/v1/projects/${project.id}/timeline/state?at=${currentDate}`).then(setState).catch(e=>setNotice(e.message))},[project?.id,currentDate]);
  useEffect(()=>{if(!playing||dates.length<2)return;const id=setInterval(()=>setIdx(v=>v>=dates.length-1?0:v+1),650);return()=>clearInterval(id)},[playing,dates.length]);
  return <div className="card panel v04-workspace">
    <div className="panel-head"><div><div className="panel-title">4D Construction Twin · v0.4</div><div className="panel-meta">IFC geometry → Twin Entity identity → schedule state → time-based visualization</div></div><div className="geometry-status">{geometry?.geometry_mode||"waiting for IFC"}</div></div>
    {notice&&<div className="result compact">{notice}</div>}
    <RealTwinViewer geometry={geometry} timelineState={state} selectedEntity={selectedEntity} onSelect={onSelect}/>
    <div className="timeline-v04">
      <button className="btn" onClick={()=>setPlaying(v=>!v)} disabled={!dates.length}>{playing?"Pause":"Play 4D"}</button>
      <div className="timeline-date"><b>{currentDate||"No timeline"}</b><span>{bounds?`${bounds.start} → ${bounds.end}`:"Import schedule data"}</span></div>
      <input aria-label="4D timeline" type="range" min="0" max={Math.max(0,dates.length-1)} value={Math.min(idx,Math.max(0,dates.length-1))} onChange={e=>setIdx(Number(e.target.value))} disabled={!dates.length}/>
      <div className="state-legend"><span className="lg future">Future</span><span className="lg planned">Planned</span><span className="lg progress">In Progress</span><span className="lg delayed">Delayed</span><span className="lg complete">Completed</span></div>
    </div>
    {state&&<div className="grid5 state-summary">{Object.entries(state.summary||{}).map(([k,v])=><div className="metric" key={k}><span>{k.replaceAll("_"," ")}</span><strong>{v}</strong></div>)}</div>}
    {geometry?.disclaimer&&<div className="panel-meta" style={{marginTop:10}}>{geometry.disclaimer}</div>}
  </div>
}
