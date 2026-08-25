"use client";
import { useEffect, useRef, useState } from "react";
import { API } from "./api";

/**
 * Live project events over a WebSocket.
 *
 * The socket is an accelerator, never the source of truth: callers keep whatever slow
 * poll they already had, and this only makes updates arrive sooner. A dropped socket
 * therefore degrades latency, not correctness — which is what makes it safe to use on a
 * site connection that comes and goes.
 */
export function useProjectEvents(projectId, onEvent) {
  const [status, setStatus] = useState("connecting");
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    if (!projectId || typeof window === "undefined") return undefined;

    let socket = null;
    let closed = false;
    let attempt = 0;
    let retryTimer = null;

    const connect = () => {
      if (closed) return;
      const token = window.sessionStorage.getItem("oneai_access_token");
      const params = new URLSearchParams();
      if (token) {
        // A browser cannot set headers on a WebSocket handshake, so the token travels
        // as a query parameter over TLS. See docs/AUTH_OIDC.md for the trade-off.
        params.set("token", token);
      } else {
        params.set("tenant_id", process.env.NEXT_PUBLIC_TENANT_ID || "demo-tenant");
        params.set("organization_id", process.env.NEXT_PUBLIC_ORGANIZATION_ID || "demo-org");
        params.set("role", process.env.NEXT_PUBLIC_ROLE || "platform_admin");
      }
      const base = API.replace(/^http/, "ws");
      socket = new WebSocket(`${base}/api/v1/ws/projects/${projectId}?${params}`);

      socket.onopen = () => { attempt = 0; setStatus("live"); };
      socket.onmessage = event => {
        try {
          const message = JSON.parse(event.data);
          if (message.type === "heartbeat" || message.type === "connected") return;
          handler.current?.(message);
        } catch { /* a malformed frame must not take the socket down */ }
      };
      socket.onerror = () => setStatus("offline");
      socket.onclose = () => {
        if (closed) return;
        setStatus("reconnecting");
        // Capped exponential backoff: a site connection that drops repeatedly must not
        // turn into a reconnect storm against the API.
        const delay = Math.min(30000, 1000 * 2 ** attempt++);
        retryTimer = setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(retryTimer);
      socket?.close();
    };
  }, [projectId]);

  return status;
}
