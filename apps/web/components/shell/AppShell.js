"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { API, api } from "../../lib/api";
import { currentIdentity, logout } from "../../lib/auth";
import { roleLabel, useSession } from "../../lib/session";
import ProjectSwitcher from "./ProjectSwitcher";
import ConnectionState from "./ConnectionState";
import { useProjectEvents } from "../../lib/realtime";

function NavLink({ href, label, hint, exact }) {
  const pathname = usePathname();
  const active = exact ? pathname === href : pathname.startsWith(href);
  return (
    <Link href={href} className={`nav-link ${active ? "active" : ""}`}>
      <span>{label}</span>
      {hint && <small>{hint}</small>}
    </Link>
  );
}

/** Readiness is polled here so every page shows the same, current platform state. */
function ReadinessBadge() {
  const [report, setReport] = useState(null);
  const [health, setHealth] = useState(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const liveness = await fetch(`${API}/health`, { cache: "no-store" }).then(r => r.json());
        if (active) setHealth(liveness);
      } catch { if (active) setHealth(null); }
      try {
        // 503 carries a full report body; it is a state, not a transport failure.
        const response = await fetch(`${API}/health/ready`, { cache: "no-store" });
        if (active) setReport(await response.json());
      } catch (error) { if (active) setReport({ status: "unreachable", error: error.message }); }
    };
    load();
    const timer = setInterval(load, 15000);
    return () => { active = false; clearInterval(timer); };
  }, []);

  const status = report?.status || "checking";
  const failing = Object.entries(report?.checks || {}).filter(([, item]) => !item.ok).map(([name]) => name);
  return (
    <Link href="/admin" className={`enterprise-status ${status}`} title={failing.length ? `Failing: ${failing.join(", ")}` : "All readiness checks pass"}>
      <span className="status-dot" />
      <div>
        <b>{status.replace("_", " ").toUpperCase()}</b>
        <small>{health?.version || "version unavailable"}{failing.length ? ` · ${failing.length} failing` : ""}</small>
      </div>
    </Link>
  );
}

export default function AppShell({ children }) {
  const { me, loading } = useSession();
  const identity = currentIdentity();
  const [projectId, setProjectId] = useState(null);
  const [navOpen, setNavOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    const match = pathname.match(/^\/projects\/([^/]+)/);
    setProjectId(match ? match[1] : null);
    // On a phone the sidebar is a drawer: navigating must close it, or the reader
    // lands on a page hidden behind the menu they just used.
    setNavOpen(false);
  }, [pathname]);

  const scope = projectId ? `/projects/${projectId}` : null;
  // One socket per project for the whole shell; pages subscribe through a context event
  // rather than each opening their own connection.
  const liveStatus = useProjectEvents(projectId, message => {
    window.dispatchEvent(new CustomEvent("twin:event", { detail: message }));
  });

  return (
    <div className={`app-shell ${navOpen ? "nav-open" : ""}`}>
      <button className="nav-toggle" aria-expanded={navOpen} aria-label="Toggle navigation" onClick={() => setNavOpen(value => !value)}>
        <span />
        <span />
        <span />
      </button>
      {navOpen && <div className="nav-scrim" onClick={() => setNavOpen(false)} />}
      <aside className="sidebar">
        <Link href="/" className="brand">
          <div className="brand-kicker">ONEAI LABS</div>
          <div className="brand-name">Construction Twin</div>
        </Link>

        <nav className="nav-group">
          <div className="nav-heading">Portfolio</div>
          <NavLink href="/" label="Projects" exact />
          <NavLink href="/compare" label="Compare" hint="portfolio metrics" />
          <NavLink href="/admin" label="Platform" hint="readiness · workers" />
        </nav>

        {scope && (
          <nav className="nav-group">
            <div className="nav-heading">Project</div>
            <NavLink href={scope} label="Overview" exact />
            <NavLink href={`${scope}/model`} label="BIM & 3D" hint="import · tiles" />
            <NavLink href={`${scope}/schedule`} label="Schedule & 4D" hint="mapping · timeline" />
            <NavLink href={`${scope}/intelligence`} label="Intelligence" hint="ask · risk · forecast" />
            <NavLink href={`${scope}/audit`} label="Audit trail" hint="hash-chained" />
            <NavLink href={`${scope}/report`} label="Report & export" hint="print · csv" />
          </nav>
        )}

        <div className="sidebar-foot">
          <a href={`${API}/docs`} target="_blank" rel="noreferrer">API documentation ↗</a>
          <span>No AI conclusion without evidence.</span>
        </div>
      </aside>

      <div className="workspace">
        <header className="workspace-bar">
          <ProjectSwitcher currentId={projectId} />
          <div className="status-cluster">
            <ConnectionState live={projectId ? liveStatus : null} />
            <ReadinessBadge />
            {(identity || me) && (
              <div className="identity-chip" title={me ? `${me.user_id} · ${me.auth_source}` : ""}>
                <div>
                  <b>{identity?.name || me?.user_id || "—"}</b>
                  <small>{loading ? "loading…" : `${roleLabel(me?.role)} · ${me?.organization_id || "no org"}`}</small>
                </div>
                {identity && <button className="btn ghost" onClick={() => logout()}>Sign out</button>}
              </div>
            )}
          </div>
        </header>
        <main className="workspace-body">{children}</main>
      </div>
    </div>
  );
}
