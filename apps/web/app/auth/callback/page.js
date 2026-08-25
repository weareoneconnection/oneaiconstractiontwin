"use client";
import { useEffect, useState } from "react";
import { completeLogin } from "../../../lib/auth";

export default function AuthCallbackPage(){
  const [error,setError]=useState("");
  useEffect(()=>{
    completeLogin(new URLSearchParams(window.location.search))
      .then(returnTo=>window.location.replace(returnTo||"/"))
      .catch(e=>setError(e.message));
  },[]);
  return <div className="auth-shell">
    <div className="card panel auth-card">
      <div className="brand-kicker">ONEAI LABS · PHYSICAL INTELLIGENCE</div>
      <h1 className="title">{error?"Sign-in failed":"Completing sign-in…"}</h1>
      {error
        ? <><div className="provisional-badge">{error}</div><a className="btn auth-button" href="/login">Try again</a></>
        : <div className="result">Exchanging the authorization code for a session.</div>}
    </div>
  </div>
}
