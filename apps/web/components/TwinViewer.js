"use client";
import { useEffect, useRef } from "react";

export default function TwinViewer({ entity }) {
  const host = useRef(null);
  useEffect(() => {
    let cleanup = () => {};
    (async () => {
      const THREE = await import("three");
      if (!host.current) return;
      host.current.innerHTML = "";
      const w = host.current.clientWidth || 800, h = host.current.clientHeight || 520;
      const scene = new THREE.Scene(); scene.background = new THREE.Color(0x06111d);
      scene.fog = new THREE.Fog(0x06111d, 18, 48);
      const camera = new THREE.PerspectiveCamera(42,w/h,.1,100); camera.position.set(11,8,14); camera.lookAt(0,1.8,0);
      const renderer = new THREE.WebGLRenderer({antialias:true}); renderer.setSize(w,h); renderer.setPixelRatio(Math.min(window.devicePixelRatio,2)); host.current.appendChild(renderer.domElement);
      scene.add(new THREE.HemisphereLight(0x99ddff,0x112233,1.5));
      const key = new THREE.DirectionalLight(0xffffff,2.2); key.position.set(8,12,6); scene.add(key);
      const grid = new THREE.GridHelper(28,28,0x27527b,0x16324e); scene.add(grid);
      const steel = new THREE.MeshStandardMaterial({color:0x36b8e7,metalness:.65,roughness:.35});
      const dim = new THREE.MeshStandardMaterial({color:0x315674,metalness:.45,roughness:.55});
      const hot = new THREE.MeshStandardMaterial({color:0xffa43b,emissive:0x512400,metalness:.5,roughness:.32});
      const addBeam=(x,y,z,sx,sy,sz,mat=steel)=>{const m=new THREE.Mesh(new THREE.BoxGeometry(sx,sy,sz),mat);m.position.set(x,y,z);scene.add(m);return m};
      for(let x=-5;x<=5;x+=2.5){addBeam(x,2.2,-3,.18,4.4,.18,dim);addBeam(x,2.2,3,.18,4.4,.18,dim);addBeam(x,4.4,0,.18,.18,6.2,steel)}
      for(let z=-3;z<=3;z+=2){addBeam(0,4.4,z,10.2,.18,.18,steel)}
      const selected=addBeam(0,4.15,1,2.35,.34,.34,hot); selected.rotation.z=.025;
      const slab=new THREE.Mesh(new THREE.BoxGeometry(10.5,.12,6.5),new THREE.MeshStandardMaterial({color:0x10283a,transparent:true,opacity:.55,roughness:.85})); slab.position.y=.06;scene.add(slab);
      const group=new THREE.Group();scene.add(group);
      let mx=0,my=0,drag=false,lastX=0,lastY=0;
      const down=e=>{drag=true;lastX=e.clientX;lastY=e.clientY}; const up=()=>drag=false; const move=e=>{if(!drag)return;mx+=(e.clientX-lastX)*.006;my+=(e.clientY-lastY)*.004;lastX=e.clientX;lastY=e.clientY;camera.position.x=11*Math.cos(mx)+14*Math.sin(mx);camera.position.z=14*Math.cos(mx)-11*Math.sin(mx);camera.position.y=Math.max(4,8+my*6);camera.lookAt(0,2,0)};
      renderer.domElement.addEventListener("pointerdown",down); window.addEventListener("pointerup",up); window.addEventListener("pointermove",move);
      let id; const loop=()=>{id=requestAnimationFrame(loop);renderer.render(scene,camera)};loop();
      const resize=()=>{if(!host.current)return;const nw=host.current.clientWidth,nh=host.current.clientHeight;camera.aspect=nw/nh;camera.updateProjectionMatrix();renderer.setSize(nw,nh)};window.addEventListener("resize",resize);
      cleanup=()=>{cancelAnimationFrame(id);window.removeEventListener("resize",resize);window.removeEventListener("pointerup",up);window.removeEventListener("pointermove",move);renderer.dispose();renderer.domElement.removeEventListener("pointerdown",down);};
    })();
    return ()=>cleanup();
  },[entity?.id]);
  return <div className="viewer" ref={host}><div className="viewer-overlay"><b>{entity?.name || "3D Twin"}</b><br/>{entity?.spatial?.station || "Station 02"} · {entity?.spatial?.zone || "Roof Zone B"}<br/><span style={{color:"#76dfff"}}>Drag to orbit · selected beam highlighted</span></div><div className="viewer-legend"><span className="pill">Geometry</span><span className="pill">4D Ready</span><span className="pill">Evidence Linked</span></div></div>;
}
