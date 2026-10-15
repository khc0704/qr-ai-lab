"use client";

// AutoML leaderboard as a single-series horizontal bar chart (one hue, best trial emphasised, value
// labelled only at the extreme; a tooltip carries the rest). The table next to it is the data view.
import { useState } from "react";
import { familyLabel } from "@/i18n/zh-TW";
import { formatMetric } from "@/lib/format";
import type { LeaderboardRow } from "@/types/domain";

const ROW_H = 22;
const BAR_H = 14;
const LABEL_W = 150;
const VALUE_W = 64;

export function LeaderboardChart({
  rows,
  metricName,
  direction = "maximize",
}: {
  rows: LeaderboardRow[];
  metricName: string;
  direction?: "maximize" | "minimize";
}) {
  const [hover, setHover] = useState<number | null>(null);
  const data = rows.slice(0, 12);
  if (data.length === 0) return null;
  const values = data.map((r) => r.metric);
  const max = Math.max(...values, 0);
  const min = Math.min(...values, 0);
  const span = max - min || 1;
  const width = 560;
  const plotW = width - LABEL_W - VALUE_W;
  const height = data.length * ROW_H + 8;
  const x0 = LABEL_W + ((0 - min) / span) * plotW;
  const bestIdx = 0; // rows are sorted by the backend (best first)

  return (
    <figure className="space-y-2">
      <figcaption className="flex items-baseline justify-between text-xs text-muted-foreground">
        <span>
          每個 trial 的 <span className="font-mono">{metricName}</span>（{direction === "maximize" ? "越高越好" : "越低越好"}）
        </span>
        <span className="font-mono tabular-nums">{rows.length} trials</span>
      </figcaption>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        role="img"
        aria-label={`AutoML 各 trial 的 ${metricName}`}
        onMouseLeave={() => setHover(null)}
      >
        <line x1={x0} x2={x0} y1={4} y2={height - 4} className="stroke-border" strokeWidth={1} />
        {data.map((r, i) => {
          const y = 4 + i * ROW_H;
          const x1 = LABEL_W + ((r.metric - min) / span) * plotW;
          const left = Math.min(x0, x1);
          const w = Math.max(Math.abs(x1 - x0), 2);
          const emphasised = i === bestIdx || hover === i;
          return (
            <g
              key={r.trial}
              onMouseEnter={() => setHover(i)}
              onFocus={() => setHover(i)}
              tabIndex={0}
              className="outline-none"
            >
              <rect x={0} y={y} width={width} height={ROW_H} className="fill-transparent" />
              <text
                x={LABEL_W - 8}
                y={y + ROW_H / 2}
                textAnchor="end"
                dominantBaseline="middle"
                className="fill-muted-foreground font-mono text-[11px]"
              >
                #{r.trial} {familyLabel(r.family)}
              </text>
              <rect
                x={left}
                y={y + (ROW_H - BAR_H) / 2}
                width={w}
                height={BAR_H}
                rx={0}
                className={emphasised ? "fill-primary" : "fill-primary/40"}
              />
              {/* 4px rounded data end: a second rect covering the tip so the baseline stays square */}
              <rect
                x={r.metric >= 0 ? x1 - Math.min(4, w) : left}
                y={y + (ROW_H - BAR_H) / 2}
                width={Math.min(4, w)}
                height={BAR_H}
                rx={4}
                className={emphasised ? "fill-primary" : "fill-primary/40"}
              />
              {i === bestIdx || hover === i ? (
                <text
                  x={(r.metric >= 0 ? x1 : left) + (r.metric >= 0 ? 6 : -6)}
                  y={y + ROW_H / 2}
                  textAnchor={r.metric >= 0 ? "start" : "end"}
                  dominantBaseline="middle"
                  className="fill-foreground font-mono text-[11px] tabular-nums"
                >
                  {formatMetric(r.metric)}
                  {i === bestIdx ? " ★" : ""}
                </text>
              ) : null}
              <title>
                {`trial #${r.trial} · ${familyLabel(r.family)} · ${metricName}=${formatMetric(r.metric)} · ${r.durationS}s`}
              </title>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
