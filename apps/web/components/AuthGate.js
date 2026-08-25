"use client";
import { useEffect, useState } from "react";
import { authConfig, isAuthenticated } from "../lib/auth";
import { setSessionExpiredHandler } from "../lib/api";

/**
 * Decides whether the dashboard may render.
 *
 * The rule comes from the API, not from the build: `/api/v1/auth/config` reports
 * whether this deployment still accepts development identity headers. When it does
 * not, an unauthenticated visitor is sent to sign in instead of watching every request
 * fail with 401.
 */
export default function AuthGate({ children }){
  const [state,setState]=useState("checking");

  useEffect(()=>{
    let active=true;
    setSessionExpiredHandler(()=>{
      window.location.assign(`/login?returnTo=${encodeURIComponent(window.location.pathname)}`);
    });
    authConfig().then(config=>{
      if(!active) return;
      if(isAuthenticated()){ setState("allowed"); return }
      // Development header auth still open: the pilot dashboard stays usable.
      if(config.dev_header_auth){ setState("allowed"); return }
      window.location.assign(`/login?returnTo=${encodeURIComponent(window.location.pathname)}`);
      setState("redirecting");
    }).catch(()=>active&&setState("allowed"));
    return()=>{active=false};
  },[]);

  if(state==="checking"||state==="redirecting"){
    return <div className="auth-shell"><div className="card panel auth-card">
      <div className="brand-kicker">ONEAI LABS · PHYSICAL INTELLIGENCE</div>
      <div className="result">{state==="checking"?"Checking your session…":"Redirecting to sign in…"}</div>
    </div></div>;
  }
  return children;
}
