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
  let res;
  try {
    res = await fetch(`${API}${path}`, {
      ...options,
      headers: {
        ...(options.body instanceof FormData ? {} : {"Content-Type":"application/json"}),
        ...authHeaders(),
        "X-Request-ID": requestId,
        ...(options.headers||{}),
      },
      cache:"no-store",
    });
  } catch (cause) {
    // fetch() rejects without status for DNS failures, blocked mixed content and
    // CORS rejections alike, so name the target explicitly.
    throw new Error(
      `Cannot reach the API at ${API} (requested ${path}). ` +
      `Check NEXT_PUBLIC_API_URL was set as a build argument, and that this origin ` +
      `(${typeof window !== "undefined" ? window.location.origin : "the web app"}) ` +
      `is listed in the API's CORS_ORIGINS. Underlying error: ${cause.message}`
    );
  }
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
