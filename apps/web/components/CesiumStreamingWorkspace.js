"use client";
import { useEffect, useRef, useState } from "react";
import { API, api, authorizedResource } from "../lib/api";

const terminal = new Set(["completed", "failed", "cancelled"]);

export default function CesiumStreamingWorkspace({project}){
  const host=useRef(null), viewerRef=useRef(null), pollRef=useRef(null);
  const [models,setModels]=useState([]),[model,setModel]=useState(null),[manifest,setManifest]=useState(null);
  const [job,setJob]=useState(null),[events,setEvents]=useState([]),[notice,setNotice]=useState("");
  const [compression,setCompression]=useState("none");

  useEffect(()=>{
    if(!project)return;
    api(`/api/v1/projects/${project.id}/bim/models`).then(x=>{setModels(x);setModel(x[0]||null)}).catch(e=>setNotice(e.message));
  },[project?.id]);

  async function refreshJob(id){
    const detail=await api(`/api/v1/asset-jobs/${id}`);
    setJob(detail);
    try{setEvents(await api(`/api/v1/asset-jobs/${id}/events`))}catch{}
    if(detail.status==="completed"){
      const m=await api(`/api/v1/asset-jobs/${id}/manifest`);
      setManifest(m);
      setNotice(`${detail.cache_hit?"Cache hit":"Distributed build complete"} · ${m.partition_strategy?.partition_count||0} partitions · ${m.entity_count||0} entities`);
    }else if(detail.status==="failed") setNotice(detail.error||"Distributed build failed");
    else if(detail.status==="cancelled") setNotice("Distributed build cancelled at a safe checkpoint");
    return detail;
  }

  useEffect(()=>{
    if(pollRef.current)clearInterval(pollRef.current);
    if(!job?.id||terminal.has(job.status))return;
    pollRef.current=setInterval(()=>refreshJob(job.id).catch(e=>setNotice(e.message)),800);
    return()=>{if(pollRef.current)clearInterval(pollRef.current)};
  },[job?.id,job?.status]);

  useEffect(()=>{
    if(!project||!model)return;
    setManifest(null);setJob(null);setEvents([]);
    api(`/api/v1/projects/${project.id}/bim/models/${model.id}/asset-jobs?limit=10`).then(async rows=>{
      if(!rows.length)return;
      const latest=rows[0];setJob(latest);
      if(latest.status==="completed"){
        try{setManifest(await api(`/api/v1/asset-jobs/${latest.id}/manifest`))}catch{}
      }
    }).catch(()=>{});
  },[project?.id,model?.id]);

  async function build(){
    if(!project||!model)return;
    setNotice("Queueing distributed IFC conversion…");setManifest(null);
    try{
      const created=await api(`/api/v1/projects/${project.id}/bim/models/${model.id}/asset-jobs`,{
        method:"POST",
        body:JSON.stringify({compression,partition_max_entities:64,partition_max_triangles:1000000,max_triangles_per_entity:120000,force_rebuild:false})
      });
      setJob(created);
      setNotice(created.cache_hit?"Reused content-addressed cache":"Durable asset job queued");
      await refreshJob(created.id);
    }catch(e){setNotice(e.message)}
  }
  async function cancel(){if(!job)return;setJob(await api(`/api/v1/asset-jobs/${job.id}/cancel`,{method:"POST"}))}
  async function resume(){if(!job)return;const j=await api(`/api/v1/asset-jobs/${job.id}/resume`,{method:"POST"});setJob(j);setNotice("Job resumed from durable partition checkpoints")}

  useEffect(()=>{
    let disposed=false;
    async function mount(){
      if(!host.current||!manifest)return;
      globalThis.CESIUM_BASE_URL="/cesium";
      const Cesium=await import("cesium");
      if(disposed||!host.current)return;
      if(viewerRef.current&&!viewerRef.current.isDestroyed())viewerRef.current.destroy();
      host.current.innerHTML="";
      const viewer=new Cesium.Viewer(host.current,{animation:false,timeline:false,baseLayerPicker:false,geocoder:false,homeButton:false,sceneModePicker:false,navigationHelpButton:false,infoBox:false,selectionIndicator:false,fullscreenButton:false,baseLayer:false,globe:false});
      viewer.scene.backgroundColor=Cesium.Color.fromCssColorString("#06111d");
      // Child tile requests derive from this Resource and inherit its auth headers.
      const tilesetResource=await authorizedResource(Cesium,`${API}${manifest.tileset_url}`);
      const tileset=await Cesium.Cesium3DTileset.fromUrl(tilesetResource,{maximumScreenSpaceError:12,dynamicScreenSpaceError:true,skipLevelOfDetail:true,preferLeaves:true});
      const g=manifest.georeference||{};
      tileset.modelMatrix=Cesium.Transforms.eastNorthUpToFixedFrame(Cesium.Cartesian3.fromDegrees(g.longitude||0,g.latitude||0,g.height||0));
      viewer.scene.primitives.add(tileset);
      // A bare zoomTo() parks the camera exactly one bounding-sphere radius away and
      // level with the centre, which leaves a building-sized model half out of frame.
      // Frame it from an offset angle at a distance derived from its own extent.
      const sphere=tileset.boundingSphere;
      const range=Math.max(sphere.radius*3.2,25);
      await viewer.zoomTo(tileset,new Cesium.HeadingPitchRange(Cesium.Math.toRadians(35),Cesium.Math.toRadians(-28),range));
      viewerRef.current=viewer;
    }
    mount().catch(e=>setNotice(e.message));
    return()=>{disposed=true;if(viewerRef.current&&!viewerRef.current.isDestroyed()){viewerRef.current.destroy();viewerRef.current=null;}}
  },[manifest?.generated_at,manifest?.job_id]);

  const progress=Number(job?.progress||0);
  return <div className="card panel v07-workspace">
    <div className="panel-head"><div><div className="panel-title">Distributed Infrastructure Twin · v0.7</div><div className="panel-meta">Durable queue · partition workers · object storage · cache · resumable 3D Tiles</div></div><div className="actions">
      <select value={model?.id||""} onChange={e=>setModel(models.find(x=>x.id===e.target.value)||null)}>{models.map(m=><option key={m.id} value={m.id}>{m.title}</option>)}</select>
      <select value={compression} onChange={e=>setCompression(e.target.value)}><option value="none">No compression</option><option value="auto">Auto / Meshopt</option><option value="meshopt">Meshopt</option><option value="draco">Draco</option></select>
      <button className="btn primary" disabled={!model||(!!job&&!terminal.has(job.status))} onClick={build}>Build Distributed Assets</button>
      {job&&!terminal.has(job.status)&&<button className="btn" onClick={cancel}>Cancel</button>}
      {job&&["failed","cancelled"].includes(job.status)&&<button className="btn" onClick={resume}>Resume</button>}
    </div></div>
    {job&&<div className="job-card">
      <div className="job-line"><b>{job.status}</b><span>{job.phase}</span><span>{progress.toFixed(1)}%</span>{job.cache_hit&&<span className="cache-hit">CACHE HIT</span>}</div>
      <div className="job-progress"><div style={{width:`${progress}%`}}/></div>
      <div className="job-meta">Partitions {job.completed_partitions||0}/{job.total_partitions||0} · attempts {job.attempts||0} · storage {manifest?.storage_backend||"pending"}</div>
      {!!job.partitions?.length&&<div className="partition-strip">{job.partitions.map(p=><div key={p.id} title={`Partition ${p.partition_index} · ${p.status}`} className={`partition-dot ${p.status}`}>{p.partition_index+1}</div>)}</div>}
    </div>}
    {notice&&<div className="result compact">{notice}</div>}
    <div className="cesium-host" ref={host}>{!manifest&&<div className="empty-stream">Import IFC, then start the v0.7 distributed asset pipeline.</div>}</div>
    {manifest&&<div className="grid4 stream-stats"><div className="metric"><span>Entities</span><strong>{manifest.entity_count}</strong></div><div className="metric"><span>Partitions</span><strong>{manifest.partition_strategy?.partition_count||0}</strong></div><div className="metric"><span>Cache</span><strong>{job?.cache_hit?"HIT":"BUILT"}</strong></div><div className="metric"><span>Assets</span><strong>{((manifest.total_asset_bytes||0)/1024).toFixed(0)} KB</strong></div></div>}
    {manifest&&<div className="panel-meta" style={{marginTop:10}}>3D Tiles 1.1 · {manifest.storage_backend} object storage · compression {manifest.compression_requested} · resumable partitions enabled</div>}
    {!!events.length&&<details className="job-events"><summary>Pipeline events ({events.length})</summary>{events.slice(-12).reverse().map(ev=><div key={ev.id||ev.sequence}><span>{ev.sequence}</span><b>{ev.event_type}</b><small>{ev.message}</small></div>)}</details>}
  </div>
}
