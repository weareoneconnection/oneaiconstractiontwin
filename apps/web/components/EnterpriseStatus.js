"use client";
import { useEffect, useState } from "react";
import { API, api } from "../lib/api";

export default function EnterpriseStatus(){
  const [health,setHealth]=useState(null),[report,setReport]=useState(null);
  useEffect(()=>{
    let active=true;
    const load=async()=>{
      try{
        const h=await fetch(`${API}/health`,{cache:"no-store"}).then(r=>r.json());
        const r=await api("/health/ready");
        if(active){setHealth(h);setReport(r)}
      }catch(e){if(active)setReport({status:"not_ready",error:e.message})}
    };
    load(); const timer=setInterval(load,10000);
    return()=>{active=false;clearInterval(timer)};
  },[]);
  const state=report?.status||"checking";
  return <div className={`enterprise-status ${state}`} title={report?.error||"Enterprise readiness checks"}>
    <span className="status-dot"/>
    <div><b>{state.replace("_"," ").toUpperCase()}</b><small>{health?.version||"version unavailable"} · Enterprise Pilot</small></div>
  </div>
}

export function ReadinessPanel({report}){
  if(!report)return null;
  return <div className="card panel readiness-panel"><div className="panel-head"><div><div className="panel-title">Pilot Readiness</div><div className="panel-meta">Database · queue · storage · worker · OneAI Core</div></div><span className={`readiness-badge ${report.status}`}>{report.status}</span></div><div className="readiness-grid">{Object.entries(report.checks||{}).map(([name,item])=><div className={`readiness-row ${item.ok?"ok":"fail"}`} key={name}><span>{name.replaceAll("_"," ")}</span><b>{item.ok?"PASS":item.required?"BLOCKED":"OPTIONAL"}</b><small>{item.detail}</small></div>)}</div></div>
}
