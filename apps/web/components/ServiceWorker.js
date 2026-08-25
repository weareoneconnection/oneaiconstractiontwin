"use client";
import { useEffect } from "react";

/** Registers the shell cache. Failure is non-fatal: the app simply needs a connection. */
export default function ServiceWorker() {
  useEffect(() => {
    if (typeof window === "undefined" || !("serviceWorker" in navigator)) return;
    if (window.location.protocol !== "https:" && window.location.hostname !== "localhost") return;
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }, []);
  return null;
}
