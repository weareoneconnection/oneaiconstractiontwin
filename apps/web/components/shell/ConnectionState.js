"use client";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useConnectivity, queuedComments, removeQueued } from "../../lib/offline";
import { useToast } from "../ui/Toast";

/**
 * Connectivity indicator and the flush loop for anything written while offline.
 *
 * Queued work is sent one item at a time and only on a real reconnect; a failure leaves
 * the item in the queue rather than dropping it, so nothing a person typed is lost.
 */
export default function ConnectionState({ live }) {
  const { online, pending } = useConnectivity();
  const { notify } = useToast();
  const [flushing, setFlushing] = useState(false);

  useEffect(() => {
    if (!online || pending === 0 || flushing) return;
    const flush = async () => {
      setFlushing(true);
      let sent = 0;
      for (const entry of queuedComments()) {
        try {
          await api(`/api/v1/projects/${entry.project_id}/comments`, {
            method: "POST",
            body: JSON.stringify({
              body: entry.body,
              target_type: entry.target_type,
              target_id: entry.target_id,
              parent_id: entry.parent_id,
            }),
          });
          removeQueued(entry.id);
          sent += 1;
        } catch {
          break; // keep the rest queued; a partial flush is fine
        }
      }
      if (sent) notify(`Sent ${sent} comment${sent > 1 ? "s" : ""} written while offline`, "success");
      setFlushing(false);
    };
    flush();
  }, [online, pending, flushing, notify]);

  const state = !online ? "offline" : live === "live" ? "live" : live === "reconnecting" ? "reconnecting" : "online";
  const label = {
    offline: "Offline",
    live: "Live",
    reconnecting: "Reconnecting",
    online: "Online",
  }[state];

  return (
    <div className={`connection-state ${state}`} title={
      state === "offline"
        ? "Showing cached data. Comments you write will be sent when the connection returns."
        : state === "live"
          ? "Receiving live project events"
          : "Connected; live updates are not currently streaming"
    }>
      <span className="connection-dot" />
      <span>{label}</span>
      {pending > 0 && <b>{pending} queued</b>}
    </div>
  );
}
