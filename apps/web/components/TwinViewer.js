"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { fitDistance, mergeExact, mergeProxies, splitMeshes } from "../lib/ifcMesh";

// This viewer used to draw a hardcoded steel frame and take the entity only to print a
// name over it, while its heading claimed to show the imported model. Someone importing
// their own building saw a fictional one and had no way to tell. It now renders the
// geometry the API actually returns, and draws proxy boxes in a different colour so an
// approximation never passes for the real element.

const EXACT_COLOR = 0x36b8e7;
const PROXY_COLOR = 0xffa43b;

export default function TwinViewer({ projectId, model }) {
  const host = useRef(null);
  const [state, setState] = useState({ status: "idle" });

  useEffect(() => {
    if (!projectId || !model?.id) { setState({ status: "idle" }); return undefined; }
    let cancelled = false;
    let cleanup = () => {};
    setState({ status: "loading" });

    (async () => {
      let payload;
      try {
        payload = await api(`/api/v1/projects/${projectId}/bim/models/${model.id}/geometry`);
      } catch (error) {
        if (!cancelled) setState({ status: "error", message: error.message });
        return;
      }
      if (cancelled || !host.current) return;

      const THREE = await import("three");
      if (cancelled || !host.current) return;

      const { exact: exactMeshes, proxy: proxyMeshes, triangles } = splitMeshes(payload.meshes || []);

      host.current.innerHTML = "";
      const w = host.current.clientWidth || 800;
      const h = host.current.clientHeight || 520;
      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x06111d);
      const camera = new THREE.PerspectiveCamera(45, w / h, 0.05, 1e6);
      const renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setSize(w, h);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      host.current.appendChild(renderer.domElement);
      scene.add(new THREE.HemisphereLight(0x99ddff, 0x112233, 1.9));
      const key = new THREE.DirectionalLight(0xffffff, 2.1);
      key.position.set(1, 2, 1.4);
      scene.add(key);

      const group = new THREE.Group();
      const exactGeometry = mergeExact(THREE, exactMeshes);
      if (exactGeometry) {
        group.add(new THREE.Mesh(exactGeometry, new THREE.MeshStandardMaterial({
          color: EXACT_COLOR, metalness: 0.35, roughness: 0.55, side: THREE.DoubleSide,
        })));
      }
      const proxyGeometry = mergeProxies(THREE, proxyMeshes);
      if (proxyGeometry) {
        group.add(new THREE.Mesh(proxyGeometry, new THREE.MeshStandardMaterial({
          color: PROXY_COLOR, metalness: 0.2, roughness: 0.7,
          transparent: true, opacity: 0.55, side: THREE.DoubleSide,
        })));
      }
      scene.add(group);

      // IFC world coordinates are neither centred nor in any predictable unit, so the
      // camera is fitted to the model's own bounds rather than to fixed numbers.
      const box = new THREE.Box3().setFromObject(group);
      const size = box.getSize(new THREE.Vector3());
      const centre = box.getCenter(new THREE.Vector3());
      const span = Math.max(size.x, size.y, size.z) || 1;
      group.position.sub(centre);

      const grid = new THREE.GridHelper(span * 2.2, 24, 0x27527b, 0x16324e);
      grid.position.y = -size.y / 2;
      scene.add(grid);

      const radius = box.getBoundingSphere(new THREE.Sphere()).radius || span / 2;
      let azimuth = 0.9;
      let elevation = 0.55;
      let distance = fitDistance(radius, camera.fov, camera.aspect);
      const applyCamera = () => {
        elevation = Math.max(0.05, Math.min(Math.PI / 2 - 0.05, elevation));
        distance = Math.max(radius * 0.15, Math.min(radius * 20, distance));
        camera.position.set(
          distance * Math.cos(elevation) * Math.sin(azimuth),
          distance * Math.sin(elevation),
          distance * Math.cos(elevation) * Math.cos(azimuth),
        );
        camera.lookAt(0, 0, 0);
      };
      applyCamera();

      let dragging = false, lastX = 0, lastY = 0;
      const down = e => { dragging = true; lastX = e.clientX; lastY = e.clientY; };
      const up = () => { dragging = false; };
      const move = e => {
        if (!dragging) return;
        azimuth -= (e.clientX - lastX) * 0.006;
        elevation += (e.clientY - lastY) * 0.004;
        lastX = e.clientX; lastY = e.clientY;
        applyCamera();
      };
      const wheel = e => { e.preventDefault(); distance *= e.deltaY > 0 ? 1.1 : 0.9; applyCamera(); };
      renderer.domElement.addEventListener("pointerdown", down);
      renderer.domElement.addEventListener("wheel", wheel, { passive: false });
      window.addEventListener("pointerup", up);
      window.addEventListener("pointermove", move);

      let frame;
      const loop = () => { frame = requestAnimationFrame(loop); renderer.render(scene, camera); };
      loop();

      const resize = () => {
        if (!host.current) return;
        const nw = host.current.clientWidth, nh = host.current.clientHeight;
        camera.aspect = nw / nh;
        camera.updateProjectionMatrix();
        renderer.setSize(nw, nh);
      };
      window.addEventListener("resize", resize);

      setState({
        status: "ready",
        mode: payload.geometry_mode,
        exact: payload.exact_meshes,
        elementProxies: payload.element_proxies,
        spatialProxies: payload.spatial_proxies,
        triangles,
        disclaimer: payload.disclaimer,
      });

      cleanup = () => {
        cancelAnimationFrame(frame);
        window.removeEventListener("resize", resize);
        window.removeEventListener("pointerup", up);
        window.removeEventListener("pointermove", move);
        renderer.domElement.removeEventListener("pointerdown", down);
        renderer.domElement.removeEventListener("wheel", wheel);
        exactGeometry?.dispose();
        proxyGeometry?.dispose();
        renderer.dispose();
      };
    })();

    return () => { cancelled = true; cleanup(); };
  }, [projectId, model?.id]);

  return (
    <div className="viewer" ref={host}>
      <div className="viewer-overlay">
        <b>{model?.title || "No model selected"}</b><br />
        {state.status === "loading" && "Loading geometry…"}
        {state.status === "error" && <span className="bad">{state.message}</span>}
        {state.status === "idle" && "Import an IFC model to see it here."}
        {state.status === "ready" && (
          <>
            {state.exact} exact · {state.elementProxies} proxy element(s)<br />
            {state.triangles.toLocaleString()} triangles · mode {state.mode}<br />
            {state.disclaimer
              ? <span className="warn">{state.disclaimer}</span>
              : <span style={{ color: "#76dfff" }}>Drag to orbit · scroll to zoom</span>}
          </>
        )}
      </div>
      {state.status === "ready" && state.elementProxies > 0 && (
        <div className="viewer-legend">
          <span className="pill">Exact IFC geometry</span>
          <span className="pill" style={{ color: "#ffa43b" }}>Proxy box (approximate)</span>
        </div>
      )}
    </div>
  );
}
