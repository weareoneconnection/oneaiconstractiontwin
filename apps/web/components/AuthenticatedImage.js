"use client";
import { useEffect, useState } from "react";
import { API, authHeaders } from "../lib/api";

/**
 * An <img> for a tenant-scoped endpoint.
 *
 * Site photographs are served from an authenticated route, and a plain src attribute
 * cannot carry credentials. The bytes are fetched, turned into an object URL and
 * revoked on unmount, so a long evidence list does not leak blobs.
 */
export default function AuthenticatedImage({ path, alt, className }) {
  const [src, setSrc] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let objectUrl = null;
    let cancelled = false;

    fetch(`${API}${path}`, { headers: authHeaders(), cache: "no-store" })
      .then(response => (response.ok ? response.blob() : Promise.reject(new Error(String(response.status)))))
      .then(blob => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      })
      .catch(() => !cancelled && setFailed(true));

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path]);

  if (failed) return <div className={`${className || ""} image-missing`}>Image unavailable</div>;
  if (!src) return <div className={`${className || ""} image-loading`} aria-hidden="true" />;
  return <img className={className} src={src} alt={alt} loading="lazy" />;
}
