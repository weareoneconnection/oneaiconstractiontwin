export const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export function authHeaders() {
  const headers = {};
  const token = typeof window !== "undefined" ? window.localStorage.getItem("oneai_access_token") : null;
  if (token) {
    headers.Authorization = `Bearer ${token}`;
    return headers;
  }
  // Local-pilot defaults. Production browsers should use OIDC and never expose an API key.
  headers["X-Tenant-ID"] = process.env.NEXT_PUBLIC_TENANT_ID || "demo-tenant";
  headers["X-Organization-ID"] = process.env.NEXT_PUBLIC_ORGANIZATION_ID || "demo-org";
  headers["X-User-ID"] = process.env.NEXT_PUBLIC_USER_ID || "demo-user";
  headers["X-Role"] = process.env.NEXT_PUBLIC_ROLE || "platform_admin";
  return headers;
}

export async function api(path, options={}) {
  const requestId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  const res = await fetch(`${API}${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : {"Content-Type":"application/json"}),
      ...authHeaders(),
      "X-Request-ID": requestId,
      ...(options.headers||{}),
    },
    cache:"no-store",
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  const type = res.headers.get("content-type") || "";
  return type.includes("application/json") ? res.json() : res.text();
}

/**
 * Cesium fetches tileset.json and every child GLB itself. Those requests must carry
 * the same credentials as the rest of the app: generated assets are served from an
 * authenticated, tenant-scoped endpoint, never from a public static mount.
 */
export async function authorizedResource(Cesium, url) {
  return new Cesium.Resource({ url, headers: { ...authHeaders() } });
}
