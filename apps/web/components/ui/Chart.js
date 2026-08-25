"use client";
import { useId, useMemo, useState } from "react";

/**
 * Charts drawn as inline SVG.
 *
 * No charting library: the bundle already carries Three.js and Cesium, and these shapes
 * are simple enough that a dependency would cost more than it saves. Everything here
 * follows the same rules as the rest of the product — a series with no data says so
 * rather than rendering an empty frame that looks like "zero".
 */

const PADDING = { top: 14, right: 16, bottom: 26, left: 38 };

function useScales(points, width, height, valueKeys) {
  return useMemo(() => {
    const values = points.flatMap(point => valueKeys.map(key => point[key]).filter(value => value != null));
    const max = Math.max(1, ...values);
    const innerWidth = width - PADDING.left - PADDING.right;
    const innerHeight = height - PADDING.top - PADDING.bottom;
    const x = index => PADDING.left + (points.length < 2 ? innerWidth / 2 : (index / (points.length - 1)) * innerWidth);
    const y = value => PADDING.top + innerHeight - (value / max) * innerHeight;
    return { x, y, max, innerWidth, innerHeight };
  }, [points, width, height, valueKeys]);
}

function path(points, xOf, yOf, key) {
  let started = false;
  return points
    .map((point, index) => {
      const value = point[key];
      if (value == null) { started = false; return ""; }
      const command = started ? "L" : "M";
      started = true;
      return `${command}${xOf(index).toFixed(1)},${yOf(value).toFixed(1)}`;
    })
    .join(" ")
    .trim();
}

export function LineChart({
  points,
  series,
  height = 220,
  width = 720,
  yLabel = "",
  xKey = "date",
  emptyTitle = "No data",
  emptyDescription = "",
  todayIndex = null,
}) {
  const clipId = useId();
  const [hover, setHover] = useState(null);
  const valueKeys = series.map(item => item.key);
  const { x, y, max } = useScales(points || [], width, height, valueKeys);

  if (!points || points.length === 0) {
    return (
      <div className="chart-empty">
        <b>{emptyTitle}</b>
        {emptyDescription && <span>{emptyDescription}</span>}
      </div>
    );
  }

  const ticks = [0, 0.25, 0.5, 0.75, 1].map(fraction => Math.round(max * fraction));
  const active = hover != null ? points[hover] : null;

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${series.map(s => s.label).join(" and ")} over time`}>
        <defs>
          <clipPath id={clipId}>
            <rect x={PADDING.left} y={PADDING.top} width={width - PADDING.left - PADDING.right} height={height - PADDING.top - PADDING.bottom} />
          </clipPath>
        </defs>

        {ticks.map(tick => (
          <g key={tick}>
            <line className="grid" x1={PADDING.left} x2={width - PADDING.right} y1={y(tick)} y2={y(tick)} />
            <text className="axis" x={PADDING.left - 7} y={y(tick) + 3} textAnchor="end">{tick}</text>
          </g>
        ))}

        {todayIndex != null && todayIndex >= 0 && todayIndex < points.length && (
          <g>
            <line className="today" x1={x(todayIndex)} x2={x(todayIndex)} y1={PADDING.top} y2={height - PADDING.bottom} />
            <text className="axis today-label" x={x(todayIndex) + 4} y={PADDING.top + 9}>today</text>
          </g>
        )}

        {series.map(item => (
          <path
            key={item.key}
            className={`series ${item.tone || ""}`}
            clipPath={`url(#${clipId})`}
            d={path(points, x, y, item.key)}
            strokeDasharray={item.dashed ? "5 4" : undefined}
          />
        ))}

        {active && series.map(item => active[item.key] != null && (
          <circle key={item.key} className={`marker ${item.tone || ""}`} cx={x(hover)} cy={y(active[item.key])} r="3.5" />
        ))}

        <text className="axis" x={PADDING.left} y={height - 8}>{points[0][xKey]}</text>
        <text className="axis" x={width - PADDING.right} y={height - 8} textAnchor="end">{points[points.length - 1][xKey]}</text>
        {yLabel && <text className="axis y-label" x={PADDING.left - 26} y={PADDING.top - 4}>{yLabel}</text>}

        <rect
          x={PADDING.left}
          y={PADDING.top}
          width={width - PADDING.left - PADDING.right}
          height={height - PADDING.top - PADDING.bottom}
          fill="transparent"
          onMouseLeave={() => setHover(null)}
          onMouseMove={event => {
            const box = event.currentTarget.getBoundingClientRect();
            const ratio = (event.clientX - box.left) / box.width;
            setHover(Math.max(0, Math.min(points.length - 1, Math.round(ratio * (points.length - 1)))));
          }}
        />
      </svg>

      <div className="chart-legend">
        {series.map(item => (
          <span key={item.key} className={`legend-item ${item.tone || ""}`}>
            <i className={item.dashed ? "dashed" : ""} />
            {item.label}
            {active && active[item.key] != null && <b>{active[item.key]}</b>}
          </span>
        ))}
        {active && <span className="legend-date">{active[xKey]}</span>}
      </div>
    </div>
  );
}

/** Small inline bar series, for daily counts rather than a continuous quantity. */
export function BarChart({ buckets, keys, height = 150, emptyTitle = "No activity recorded" }) {
  if (!buckets || buckets.length === 0) return <div className="chart-empty"><b>{emptyTitle}</b></div>;
  const max = Math.max(1, ...buckets.map(bucket => keys.reduce((total, key) => total + (bucket[key.key] || 0), 0)));
  return (
    <div className="chart bar-chart" style={{ height }}>
      <div className="bars">
        {buckets.map(bucket => {
          const total = keys.reduce((sum, key) => sum + (bucket[key.key] || 0), 0);
          return (
            <div key={bucket.date} className="bar-column" title={`${bucket.date} · ${total} events`}>
              {keys.map(key => (
                <div
                  key={key.key}
                  className={`bar-segment ${key.tone}`}
                  style={{ height: `${((bucket[key.key] || 0) / max) * 100}%` }}
                />
              ))}
              <span className="bar-total">{total || ""}</span>
            </div>
          );
        })}
      </div>
      <div className="chart-legend">
        {keys.map(key => <span key={key.key} className={`legend-item ${key.tone}`}><i />{key.label}</span>)}
        <span className="legend-date">{buckets[0].date} → {buckets[buckets.length - 1].date}</span>
      </div>
    </div>
  );
}
