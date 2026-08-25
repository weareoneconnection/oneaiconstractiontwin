"use client";
import { useEffect, useState } from "react";
import { API } from "../lib/api";
import { currentIdentity, logout } from "../lib/auth";

export default function EnterpriseStatus(){
  const [health,setHealth]=useState(null),[report,setReport]=useState(null);
  useEffect(()=>{
    let active=true;
    const load=async()=>{
      // Liveness and readiness are reported independently: a service that is up but
      // not ready (503) must still show its version, and its failing checks must stay
      // visible. Treating the 503 as an error discarded both.
      try{
        const h=await fetch(`${API}/health`,{cache:"no-store"}).then(r=>r.json());
        if(active)setHealth(h);
      }catch(e){if(active)setHealth(null)}
      try{
        // /health/ready answers 503 with a full report body when a check fails.
        const response=await fetch(`${API}/health/ready`,{cache:"no-store"});
        const r=await response.json();
        if(active)setReport(r);
      }catch(e){if(active)setReport({status:"unreachable",error:e.message})}
    };
    load(); const timer=setInterval(load,10000);
    return()=>{active=false;clearInterval(timer)};
  },[]);
  const state=report?.status||"checking";
  const identity=currentIdentity();
  return <div className="status-cluster">
    <div className={`enterprise-status ${state}`} title={report?.error||"Enterprise readiness checks"}>
      <span className="status-dot"/>
      <div><b>{state.replace("_"," ").toUpperCase()}</b><small>{health?.version||"version unavailable"} · Enterprise Pilot</small></div>
    </div>
    {identity && <div className="identity-chip" title={`${identity.subject} · tenant ${identity.tenant||"unscoped"}`}>
      <div><b>{identity.name}</b><small>{identity.organization||identity.tenant||"signed in"}</small></div>
      <button className="btn ghost" onClick={()=>logout()}>Sign out</button>
    </div>}
  </div>
}

export function ReadinessPanel({report}){
  if(!report)return null;
  return <div className="card panel readiness-panel"><div className="panel-head"><div><div className="panel-title">Pilot Readiness</div><div className="panel-meta">Database · queue · storage · worker · OneAI Core</div></div><span className={`readiness-badge ${report.status}`}>{report.status}</span></div><div className="readiness-grid">{Object.entries(report.checks||{}).map(([name,item])=><div className={`readiness-row ${item.ok?"ok":"fail"}`} key={name}><span>{name.replaceAll("_"," ")}</span><b>{item.ok?"PASS":item.required?"BLOCKED":"OPTIONAL"}</b><small>{item.detail}</small></div>)}</div></div>
}
