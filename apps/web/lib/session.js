"use client";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api";
import { authConfig } from "./auth";

/**
 * The signed-in identity and what it is allowed to do.
 *
 * Permissions come from the API (`/auth/me`), never from the client: the browser only
 * uses them to decide what to *offer*. Every action is still authorised server-side, so
 * a tampered client gains nothing beyond a nicer-looking 403.
 */
const SessionContext = createContext({ me: null, config: null, loading: true, can: () => false });

export function SessionProvider({ children }) {
  const [state, setState] = useState({ me: null, config: null, loading: true, error: null });

  const load = useCallback(async () => {
    try {
      const [config, me] = await Promise.all([authConfig(), api("/api/v1/auth/me")]);
      setState({ me, config, loading: false, error: null });
    } catch (error) {
      setState({ me: null, config: null, loading: false, error: error.message });
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const permissions = state.me?.permissions || [];
  const can = useCallback(
    permission => permissions.includes("*") || permissions.includes(permission),
    [permissions]
  );

  return <SessionContext.Provider value={{ ...state, permissions, can, reload: load }}>{children}</SessionContext.Provider>;
}

export function useSession() {
  return useContext(SessionContext);
}

/** Human-readable role, e.g. "project_manager" → "Project manager". */
export function roleLabel(role) {
  if (!role) return "Unknown role";
  const text = role.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
