"use client";

/**
 * Browser-side OpenID Connect: Authorization Code with PKCE.
 *
 * A single-page application cannot keep a client secret, so it uses PKCE and a public
 * client. The application never sees a password and never handles a client secret; it
 * only ever holds the access token the provider issues.
 *
 * Tokens live in sessionStorage: cleared when the tab closes, and not shared with other
 * tabs or subdomains. This is not immune to XSS - the fully hardened alternative is a
 * backend-for-frontend holding httpOnly cookies, which is a larger change and is noted
 * in docs/AUTH_OIDC.md as the next step for a production deployment.
 */

import { API } from "./api";

const TOKEN_KEY = "oneai_access_token";
const REFRESH_KEY = "oneai_refresh_token";
const ID_TOKEN_KEY = "oneai_id_token";
const EXPIRY_KEY = "oneai_token_expires_at";
const VERIFIER_KEY = "oneai_pkce_verifier";
const STATE_KEY = "oneai_oauth_state";
const RETURN_KEY = "oneai_return_to";

const store = () => (typeof window === "undefined" ? null : window.sessionStorage);

let configPromise = null;

export function authConfig({ refresh = false } = {}) {
  if (refresh || !configPromise) {
    configPromise = fetch(`${API}/api/v1/auth/config`, { cache: "no-store" })
      .then(r => r.json())
      .catch(error => ({ auth_mode: "unknown", oidc: null, error: error.message }));
  }
  return configPromise;
}

export function accessToken() {
  const s = store();
  if (!s) return null;
  const token = s.getItem(TOKEN_KEY);
  if (!token) return null;
  const expiresAt = Number(s.getItem(EXPIRY_KEY) || 0);
  // Treat a token expiring within 30s as already gone, so a request cannot fail
  // mid-flight on an expiry the client could see coming.
  if (expiresAt && Date.now() > expiresAt - 30_000) return null;
  return token;
}

export function isAuthenticated() {
  return Boolean(accessToken());
}

export function currentIdentity() {
  const token = accessToken();
  if (!token) return null;
  try {
    const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    return {
      subject: payload.sub,
      email: payload.email || payload.preferred_username || null,
      name: payload.name || payload.preferred_username || payload.email || payload.sub,
      tenant: payload.tenant_id || null,
      organization: payload.organization_id || null,
      expiresAt: payload.exp ? payload.exp * 1000 : null,
    };
  } catch {
    return null;
  }
}

function storeTokens(payload) {
  const s = store();
  if (!s) return;
  if (payload.access_token) s.setItem(TOKEN_KEY, payload.access_token);
  if (payload.refresh_token) s.setItem(REFRESH_KEY, payload.refresh_token);
  if (payload.id_token) s.setItem(ID_TOKEN_KEY, payload.id_token);
  const lifetime = Number(payload.expires_in || 0);
  s.setItem(EXPIRY_KEY, String(lifetime ? Date.now() + lifetime * 1000 : 0));
}

export function clearTokens() {
  const s = store();
  if (!s) return;
  [TOKEN_KEY, REFRESH_KEY, ID_TOKEN_KEY, EXPIRY_KEY, VERIFIER_KEY, STATE_KEY].forEach(key => s.removeItem(key));
}

function randomString(bytes = 32) {
  const buffer = new Uint8Array(bytes);
  crypto.getRandomValues(buffer);
  return base64Url(buffer);
}

function base64Url(bytes) {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

async function pkceChallenge(verifier) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64Url(digest);
}

export function redirectUri() {
  return `${window.location.origin}/auth/callback`;
}

/** Send the browser to the identity provider. */
export async function beginLogin(returnTo = "/") {
  const config = await authConfig();
  const oidc = config.oidc;
  if (!oidc?.authorization_endpoint) {
    throw new Error(
      oidc?.error
        ? `The identity provider is not reachable: ${oidc.error}`
        : "This deployment has no identity provider configured (auth_mode is not oidc/hybrid)."
    );
  }
  const verifier = randomString(48);
  const state = randomString(16);
  const s = store();
  s.setItem(VERIFIER_KEY, verifier);
  s.setItem(STATE_KEY, state);
  s.setItem(RETURN_KEY, returnTo);

  const params = new URLSearchParams({
    response_type: "code",
    client_id: oidc.client_id,
    redirect_uri: redirectUri(),
    scope: oidc.scopes || "openid profile email",
    state,
    code_challenge: await pkceChallenge(verifier),
    code_challenge_method: "S256",
  });
  window.location.assign(`${oidc.authorization_endpoint}?${params.toString()}`);
}

/** Handle the provider's redirect back to /auth/callback. */
export async function completeLogin(searchParams) {
  const s = store();
  const error = searchParams.get("error");
  if (error) {
    throw new Error(`${error}: ${searchParams.get("error_description") || "the identity provider rejected the sign-in"}`);
  }
  const code = searchParams.get("code");
  const state = searchParams.get("state");
  if (!code) throw new Error("The provider did not return an authorization code.");
  // State binds this response to the request this browser actually started.
  if (!state || state !== s.getItem(STATE_KEY)) {
    throw new Error("Sign-in state did not match. Start the sign-in again from this device.");
  }
  const verifier = s.getItem(VERIFIER_KEY);
  if (!verifier) throw new Error("The sign-in verifier is missing. Start the sign-in again.");

  const config = await authConfig();
  const response = await fetch(config.oidc.token_endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code,
      redirect_uri: redirectUri(),
      client_id: config.oidc.client_id,
      code_verifier: verifier,
    }),
  });
  if (!response.ok) {
    throw new Error(`Token exchange failed: ${response.status} ${await response.text()}`);
  }
  storeTokens(await response.json());
  s.removeItem(VERIFIER_KEY);
  s.removeItem(STATE_KEY);
  const returnTo = s.getItem(RETURN_KEY) || "/";
  s.removeItem(RETURN_KEY);
  return returnTo;
}

/** Exchange the refresh token. Returns true when a fresh access token is in place. */
export async function refreshSession() {
  const s = store();
  const refreshToken = s?.getItem(REFRESH_KEY);
  if (!refreshToken) return false;
  const config = await authConfig();
  if (!config.oidc?.token_endpoint) return false;
  try {
    const response = await fetch(config.oidc.token_endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        refresh_token: refreshToken,
        client_id: config.oidc.client_id,
      }),
    });
    if (!response.ok) return false;
    storeTokens(await response.json());
    return true;
  } catch {
    return false;
  }
}

/** Clear the local session, then end it at the provider too. */
export async function logout() {
  const s = store();
  const idToken = s?.getItem(ID_TOKEN_KEY);
  const config = await authConfig();
  clearTokens();
  const endSession = config.oidc?.end_session_endpoint;
  if (endSession) {
    const params = new URLSearchParams({ post_logout_redirect_uri: window.location.origin });
    if (idToken) params.set("id_token_hint", idToken);
    window.location.assign(`${endSession}?${params.toString()}`);
    return;
  }
  window.location.assign("/login");
}
