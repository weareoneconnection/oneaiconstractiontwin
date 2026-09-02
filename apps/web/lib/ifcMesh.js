// Turning an API geometry payload into renderable buffers, kept out of the React
// component so it can be exercised directly against a real model's response.

export function mergeExact(THREE, meshes) {
  let vertexCount = 0;
  let indexCount = 0;
  for (const m of meshes) { vertexCount += m.vertices.length; indexCount += m.indices.length; }
  if (!indexCount) return null;
  const positions = new Float32Array(vertexCount);
  const indices = new Uint32Array(indexCount);
  let vOffset = 0, iOffset = 0, base = 0;
  for (const m of meshes) {
    positions.set(m.vertices, vOffset);
    for (let i = 0; i < m.indices.length; i += 1) indices[iOffset + i] = m.indices[i] + base;
    base += m.vertices.length / 3;
    vOffset += m.vertices.length;
    iOffset += m.indices.length;
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setIndex(new THREE.BufferAttribute(indices, 1));
  geometry.computeVertexNormals();
  return geometry;
}

export function mergeProxies(THREE, meshes) {
  if (!meshes.length) return null;
  const parts = [];
  for (const m of meshes) {
    const [sx, sy, sz] = m.transform?.scale || [1, 1, 1];
    const [px, py, pz] = m.transform?.position || [0, 0, 0];
    const box = new THREE.BoxGeometry(sx, sy, sz);
    box.translate(px, py, pz);
    parts.push(box.index ? box.toNonIndexed() : box);
  }
  let floatCount = 0;
  for (const p of parts) floatCount += p.attributes.position.array.length;
  const positions = new Float32Array(floatCount);
  const normals = new Float32Array(floatCount);
  let offset = 0;
  for (const p of parts) {
    positions.set(p.attributes.position.array, offset);
    normals.set(p.attributes.normal.array, offset);
    offset += p.attributes.position.array.length;
    p.dispose();
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("normal", new THREE.BufferAttribute(normals, 3));
  return geometry;
}

export function splitMeshes(meshes) {
  const exact = meshes.filter(m => m.mode === "ifc-exact" && m.indices?.length);
  const proxy = meshes.filter(m => m.mode !== "ifc-exact" || !m.indices?.length);
  return { exact, proxy, triangles: exact.reduce((sum, m) => sum + m.indices.length / 3, 0) };
}

// A fixed multiple of the model's span crops wide models in tall viewports and vice
// versa, so the distance is derived from the bounding sphere and whichever field of
// view - vertical or horizontal - is the tighter of the two.
export function fitDistance(radius, fovDegrees, aspect, margin = 1.2) {
  const vFov = (fovDegrees * Math.PI) / 180;
  const hFov = 2 * Math.atan(Math.tan(vFov / 2) * aspect);
  return (radius / Math.sin(Math.min(vFov, hFov) / 2)) * margin;
}
