"use client";
import { useEffect, useRef } from "react";

const STATUS={future:0x52606d,planned:0x3d7eff,in_progress:0xffb343,delayed:0xff4d6d,completed:0x28d17c};

export default function RealTwinViewer({geometry,timelineState,selectedEntity,onSelect}){
  const host=useRef(null);
  useEffect(()=>{
    let cleanup=()=>{};
    (async()=>{
      const THREE=await import("three");
      const {OrbitControls}=await import("three/examples/jsm/controls/OrbitControls.js");
      if(!host.current)return;
      host.current.innerHTML="";
      const w=host.current.clientWidth||1000,h=host.current.clientHeight||600;
      const scene=new THREE.Scene(); scene.background=new THREE.Color(0x06111d);
      const camera=new THREE.PerspectiveCamera(45,w/h,0.01,100000); camera.position.set(14,10,16);
      const renderer=new THREE.WebGLRenderer({antialias:true}); renderer.setSize(w,h); renderer.setPixelRatio(Math.min(window.devicePixelRatio,2)); host.current.appendChild(renderer.domElement);
      renderer.outputColorSpace=THREE.SRGBColorSpace;
      scene.add(new THREE.HemisphereLight(0xbfe8ff,0x152334,1.7)); const sun=new THREE.DirectionalLight(0xffffff,2.4);sun.position.set(12,18,10);scene.add(sun);
      scene.add(new THREE.GridHelper(60,60,0x27527b,0x132a40));
      const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.dampingFactor=.08;
      const objects=[]; const stateMap=new Map((timelineState?.entities||[]).map(x=>[x.entity_id,x]));
      for(const mesh of geometry?.meshes||[]){
        let obj;
        if(mesh.vertices?.length&&mesh.indices?.length){
          const g=new THREE.BufferGeometry();g.setAttribute("position",new THREE.Float32BufferAttribute(mesh.vertices,3));g.setIndex(mesh.indices);g.computeVertexNormals();
          obj=new THREE.Mesh(g,new THREE.MeshStandardMaterial({color:STATUS[stateMap.get(mesh.entity_id)?.state]||0x36b8e7,metalness:.28,roughness:.62,side:THREE.DoubleSide}));
        }else{
          const s=mesh.transform?.scale||[1,1,1],p=mesh.transform?.position||[0,0,0];
          obj=new THREE.Mesh(new THREE.BoxGeometry(s[0],s[1],s[2]),new THREE.MeshStandardMaterial({color:STATUS[stateMap.get(mesh.entity_id)?.state]||0x36b8e7,metalness:.38,roughness:.55}));obj.position.set(...p);
        }
        obj.userData={entityId:mesh.entity_id,name:mesh.name};
        if(mesh.entity_id===selectedEntity?.id){obj.material.emissive=new THREE.Color(0x613500);obj.material.emissiveIntensity=.85;}
        scene.add(obj);objects.push(obj);
      }
      if(objects.length){
        const box=new THREE.Box3();objects.forEach(o=>box.expandByObject(o));const center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3());controls.target.copy(center);const max=Math.max(size.x,size.y,size.z,5);camera.position.set(center.x+max*.9,center.y+max*.65,center.z+max*.9);camera.near=Math.max(.01,max/10000);camera.far=Math.max(1000,max*100);camera.updateProjectionMatrix();controls.update();
      }
      const ray=new THREE.Raycaster(),mouse=new THREE.Vector2();
      const click=e=>{const r=renderer.domElement.getBoundingClientRect();mouse.x=((e.clientX-r.left)/r.width)*2-1;mouse.y=-((e.clientY-r.top)/r.height)*2+1;ray.setFromCamera(mouse,camera);const hit=ray.intersectObjects(objects,false)[0];if(hit?.object?.userData?.entityId)onSelect?.(hit.object.userData.entityId)};
      renderer.domElement.addEventListener("click",click);
      let frame;const loop=()=>{frame=requestAnimationFrame(loop);controls.update();renderer.render(scene,camera)};loop();
      const resize=()=>{if(!host.current)return;const nw=host.current.clientWidth,nh=host.current.clientHeight;camera.aspect=nw/nh;camera.updateProjectionMatrix();renderer.setSize(nw,nh)};window.addEventListener("resize",resize);
      cleanup=()=>{cancelAnimationFrame(frame);window.removeEventListener("resize",resize);renderer.domElement.removeEventListener("click",click);controls.dispose();renderer.dispose();objects.forEach(o=>{o.geometry?.dispose();o.material?.dispose()})};
    })();return()=>cleanup();
  },[geometry?.model_document_id, timelineState?.at, selectedEntity?.id]);
  return <div className="viewer viewer-v04" ref={host}><div className="viewer-overlay"><b>{geometry?.title||"Import IFC to start"}</b><br/><span>{geometry?`${geometry.mesh_count} meshes · ${geometry.geometry_mode}`:"Real IFC geometry + 4D schedule state"}</span></div></div>
}
