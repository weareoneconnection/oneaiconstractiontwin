"use client";
import { useEffect, useState } from "react";

/**
 * Offline support for site use.
 *
 * Two capabilities, both scoped to what is honest:
 *
 * 1. **Read-through cache.** Successful GET responses are kept, and when the network is
 *    gone the cached copy is served with the timestamp it was fetched, so nobody mistakes
 *    yesterday's schedule for today's.
 * 2. **Queued comments.** A note written in a basement is held locally and sent when the
 *    connection returns. Only comments are queued: replaying an approval or an import
 *    after an unknown delay could act on a state that no longer exists.
 */

const CACHE_PREFIX = "oneai:cache:";
const QUEUE_KEY = "oneai:queue:comments";

export function cacheResponse(path, data) {
  try {
    window.localStorage.setItem(CACHE_PREFIX + path, JSON.stringify({ at: Date.now(), data }));
  } catch { /* storage full or unavailable: caching is best-effort */ }
}

export function readCache(path) {
  try {
    const raw = window.localStorage.getItem(CACHE_PREFIX + path);
    if (!raw) return null;
    const entry = JSON.parse(raw);
    return { data: entry.data, at: entry.at };
  } catch {
    return null;
  }
}

export function queuedComments() {
  try {
    return JSON.parse(window.localStorage.getItem(QUEUE_KEY) || "[]");
  } catch {
    return [];
  }
}

export function queueComment(entry) {
  const queue = queuedComments();
  queue.push({ ...entry, queued_at: Date.now(), id: `local-${Date.now()}-${Math.random().toString(16).slice(2)}` });
  window.localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
  return queue;
}

export function removeQueued(id) {
  const remaining = queuedComments().filter(entry => entry.id !== id);
  window.localStorage.setItem(QUEUE_KEY, JSON.stringify(remaining));
  return remaining;
}

/** Reports connectivity and how many writes are waiting to be sent. */
export function useConnectivity() {
  const [online, setOnline] = useState(true);
  const [pending, setPending] = useState(0);

  useEffect(() => {
    const sync = () => {
      setOnline(navigator.onLine);
      setPending(queuedComments().length);
    };
    sync();
    window.addEventListener("online", sync);
    window.addEventListener("offline", sync);
    const timer = setInterval(sync, 4000);
    return () => {
      window.removeEventListener("online", sync);
      window.removeEventListener("offline", sync);
      clearInterval(timer);
    };
  }, []);

  return { online, pending };
}
