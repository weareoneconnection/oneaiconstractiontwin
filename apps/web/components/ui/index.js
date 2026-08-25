"use client";
import { Component } from "react";

export function Card({ title, meta, actions, children, className = "", padded = true }) {
  return (
    <section className={`card ${padded ? "panel" : ""} ${className}`}>
      {(title || actions) && (
        <div className="panel-head">
          <div>
            {title && <div className="panel-title">{title}</div>}
            {meta && <div className="panel-meta">{meta}</div>}
          </div>
          {actions && <div className="actions">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Metric({ label, value, sub, tone }) {
  return (
    <div className="card metric">
      <div className="metric-label">{label}</div>
      <div className={`metric-value ${tone || ""}`}>{value}</div>
      {sub && <div className="metric-sub">{sub}</div>}
    </div>
  );
}

export function Badge({ children, tone = "neutral", title }) {
  return <span className={`ui-badge ${tone}`} title={title}>{children}</span>;
}

export function Skeleton({ lines = 3, height = 14 }) {
  return (
    <div className="skeleton" aria-hidden="true">
      {Array.from({ length: lines }).map((_, index) => (
        <div key={index} className="skeleton-line" style={{ height, width: `${88 - index * 11}%` }} />
      ))}
    </div>
  );
}

export function EmptyState({ title, description, action }) {
  return (
    <div className="empty-state">
      <div className="empty-title">{title}</div>
      {description && <p className="empty-description">{description}</p>}
      {action}
    </div>
  );
}

/**
 * A button that reflects the caller's permissions.
 *
 * Hiding an action the role cannot perform is worse than disabling it: the operator
 * cannot tell whether the feature is missing or simply not theirs. This shows it,
 * disables it, and says which permission is required.
 */
export function PermissionButton({ allowed, permission, children, className = "btn", ...props }) {
  if (allowed) return <button className={className} {...props}>{children}</button>;
  return (
    <button className={`${className} denied`} disabled title={`Requires the ${permission} permission`}>
      {children}
    </button>
  );
}

export class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <Card title="This section could not be displayed" meta="The rest of the workspace is unaffected.">
        <div className="result">{String(this.state.error.message || this.state.error)}</div>
        <button className="btn" onClick={() => this.setState({ error: null })}>Try again</button>
      </Card>
    );
  }
}
