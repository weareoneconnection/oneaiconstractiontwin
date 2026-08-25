"use client";
import { useEffect, useState } from "react";
import { authConfig, beginLogin, isAuthenticated } from "../../lib/auth";

export default function LoginPage(){
  const [config,setConfig]=useState(null),[error,setError]=useState(""),[busy,setBusy]=useState(false);
  useEffect(()=>{
    if(isAuthenticated()){window.location.assign("/");return}
    authConfig().then(setConfig).catch(e=>setError(e.message));
  },[]);

  const signIn=async()=>{
    setBusy(true);setError("");
    try{ await beginLogin(new URLSearchParams(window.location.search).get("returnTo")||"/") }
    catch(e){ setError(e.message); setBusy(false) }
  };

  const provider=config?.oidc;
  const unavailable=config && !provider;
  return <div className="auth-shell">
    <div className="card panel auth-card">
      <div className="brand-kicker">ONEAI LABS · PHYSICAL INTELLIGENCE</div>
      <h1 className="title">Construction Twin</h1>
      <div className="subtitle">Sign in to continue to the enterprise pilot</div>

      {!config && <div className="result">Checking how this deployment authenticates…</div>}

      {provider && <>
        <button className="btn primary auth-button" disabled={busy||!provider.authorization_endpoint} onClick={signIn}>
          {busy?"Redirecting…":"Sign in with your organization account"}
        </button>
        <div className="panel-meta auth-meta">{provider.issuer}</div>
        {provider.discovered===false && <div className="provisional-badge">
          The identity provider could not be reached: {provider.error}
        </div>}
      </>}

      {unavailable && <div className="result">
        <b>No identity provider is configured for this deployment.</b>
        <div className="provenance">
          auth_mode is <code>{config.auth_mode}</code>{config.dev_header_auth?" and development header authentication is enabled, so the dashboard is reachable without signing in.":"."}
        </div>
        {config.dev_header_auth && <a className="btn auth-button" href="/">Continue to the dashboard</a>}
      </div>}

      {error && <div className="provisional-badge">{error}</div>}
    </div>
  </div>
}
