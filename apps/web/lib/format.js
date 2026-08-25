export const percent = (value, digits = 1) => `${Number(value || 0).toFixed(digits)}%`;
export const days = value => `${Number(value || 0).toFixed(Math.abs(value) < 10 ? 1 : 0)} d`;
export const bytes = value => {
  const size = Number(value || 0);
  if (size < 1024) return `${size} B`;
  if (size < 1024 ** 2) return `${(size / 1024).toFixed(0)} KB`;
  return `${(size / 1024 ** 2).toFixed(1)} MB`;
};
export const dateTime = value => (value ? new Date(value).toLocaleString() : "—");
export const date = value => (value ? new Date(value).toLocaleDateString() : "—");
export const shortId = value => (value ? String(value).slice(0, 8) : "—");
/** Relative time that stays useful for audit trails and heartbeats. */
export const since = value => {
  if (!value) return "—";
  const seconds = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
};
