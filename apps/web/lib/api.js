export const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export function authHeaders() {
  const headers = {};
  // A real session always wins. Only when there is none do we fall back to the
  // development identity headers, which the API accepts solely outside production.
  const token = typeof window !== "undefined" ? window.sessionStorage.getItem("oneai_access_token") : null;
  if (token) {
    headers.Authorization = `Bearer ${token}`;
    return headers;
  }
  headers["X-Tenant-ID"] = process.env.NEXT_PUBLIC_TENANT_ID || "demo-tenant";
  headers["X-Organization-ID"] = process.env.NEXT_PUBLIC_ORGANIZATION_ID || "demo-org";
  headers["X-User-ID"] = process.env.NEXT_PUBLIC_USER_ID || "demo-user";
  headers["X-Role"] = process.env.NEXT_PUBLIC_ROLE || "platform_admin";
  return headers;
}

/** Called when the API rejects the session and a refresh cannot save it. */
let onSessionExpired = () => {};
export function setSessionExpiredHandler(handler) {
  onSessionExpired = handler || (() => {});
}

export async function api(path, options={}, { allowRetry = true } = {}) {
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
  if (res.status === 401 && allowRetry && typeof window !== "undefined") {
    // An expired access token is an ordinary event, not an error to show the user:
    // try the refresh token once, and only surface a failure if that cannot recover.
    const { refreshSession } = await import("./auth");
    if (await refreshSession()) return api(path, options, { allowRetry: false });
    onSessionExpired();
    throw new Error("Your session has expired. Sign in again to continue.");
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

/**
 * Download an authenticated file.
 *
 * A plain <a href> cannot carry the Authorization header, so the bytes are fetched,
 * turned into a blob and handed to the browser. The filename comes from the server's
 * Content-Disposition, so exports are named consistently wherever they are triggered.
 */
export async function download(path) {
  const response = await fetch(`${API}${path}`, { headers: authHeaders(), cache: "no-store" });
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = match ? match[1] : path.split("/").pop();
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  return anchor.download;
}
