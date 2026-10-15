"use client";

// Usage history: one line chart per resource (single hue; the denominator line is the only second mark),
// then the per-project window share as sorted bars. The denominator toggle picks what 100 % means.
import { ChartLine, Info } from "lucide-react";
import { useMemo, useState } from "react";
import { EmptyState } from "@/components/features/empty-state";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatMb } from "@/lib/format";
import type { UsageHistory, UsagePoint } from "@/types/domain";

type Denominator = "quota" | "pool" | "node";

const W = 640;
const H = 160;
const PAD = { l: 44, r: 12, t: 10, b: 22 };

function fmtTime(iso: string, range: UsageHistory["range"]) {
  const d = new Date(iso);
  const hh = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  if (range === "7d" || range === "30d") return `${d.getMonth() + 1}/${d.getDate()} ${hh}`;
  return hh;
}

function LineChart({
  title,
  points,
  value,
  max,
  maxLabel,
  format,
  range,
  unit,
}: {
  title: string;
  points: UsagePoint[];
  value: (p: UsagePoint) => number | undefined;
  max: number;
  maxLabel: string;
  format: (n: number) => string;
  range: UsageHistory["range"];
  unit?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const data = points.map((p) => value(p));
  const defined = data.filter((v): v is number => v != null);
  if (defined.length === 0) {
    return (
      <Card className="gap-2 p-4">
        <div className="text-label">{title}</div>
        <p className="text-xs text-muted-foreground">這段期間沒有讀數。</p>
      </Card>
    );
  }
  const top = Math.max(max, ...defined) * 1.05 || 1;
  const plotW = W - PAD.l - PAD.r;
  const plotH = H - PAD.t - PAD.b;
  const x = (i: number) => PAD.l + (points.length > 1 ? (i / (points.length - 1)) * plotW : plotW / 2);
  const y = (v: number) => PAD.t + plotH - (v / top) * plotH;
  const path = data
    .map((v, i) =>
      v == null ? null : `${i === 0 || data[i - 1] == null ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`,
    )
    .filter(Boolean)
    .join(" ");
  const area = `${path} L${x(points.length - 1).toFixed(1)},${(PAD.t + plotH).toFixed(1)} L${x(0).toFixed(1)},${(PAD.t + plotH).toFixed(1)} Z`;
  const latest = defined[defined.length - 1];
  const peak = Math.max(...defined);
  const avg = defined.reduce((a, b) => a + b, 0) / defined.length;
  const hv = hover != null ? data[hover] : undefined;
  // three gridlines, but never two with the same label (small integer scales such as 0 / 1 GPU)
  const ticks = [0, 0.5, 1].map((f) => f * top).filter((t, i, arr) => i === 0 || format(t) !== format(arr[i - 1]));
  return (
    <Card className="gap-2 p-4">
      <div className="flex items-baseline justify-between gap-3">
        <div className="text-label">{title}</div>
        <div className="font-mono text-xs text-muted-foreground tabular-nums">
          {hover != null && hv != null ? (
            <>
              {fmtTime(points[hover].t, range)} · {format(hv)}
              {unit ?? ""}
            </>
          ) : (
            <>
              最新 {format(latest)}
              {unit ?? ""} · 平均 {format(avg)}
              {unit ?? ""} · 峰值 {format(peak)}
              {unit ?? ""}
            </>
          )}
        </div>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        role="img"
        aria-label={`${title}，最新 ${format(latest)}${unit ?? ""}`}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const px = ((e.clientX - rect.left) / rect.width) * W;
          const i = Math.round(((px - PAD.l) / plotW) * (points.length - 1));
          setHover(Math.max(0, Math.min(points.length - 1, i)));
        }}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} className="stroke-border" strokeWidth={1} />
            <text x={PAD.l - 6} y={y(t) + 3} textAnchor="end" className="fill-muted-foreground font-mono text-[10px]">
              {format(t)}
            </text>
          </g>
        ))}
        {max > 0 && max <= top ? (
          <g>
            <line
              x1={PAD.l}
              x2={W - PAD.r}
              y1={y(max)}
              y2={y(max)}
              className="stroke-foreground/50"
              strokeWidth={1}
              strokeDasharray="4 3"
            />
            <text x={W - PAD.r} y={y(max) - 3} textAnchor="end" className="fill-muted-foreground text-[10px]">
              {maxLabel} {format(max)}
              {unit ?? ""}
            </text>
          </g>
        ) : null}
        <path d={area} className="fill-primary/15" />
        <path d={path} className="fill-none stroke-primary" strokeWidth={1.5} strokeLinejoin="round" />
        {hover != null && hv != null ? (
          <g>
            <line
              x1={x(hover)}
              x2={x(hover)}
              y1={PAD.t}
              y2={PAD.t + plotH}
              className="stroke-foreground/30"
              strokeWidth={1}
            />
            <circle cx={x(hover)} cy={y(hv)} r={3} className="fill-primary stroke-background" strokeWidth={1.5} />
          </g>
        ) : null}
        <text x={PAD.l} y={H - 6} className="fill-muted-foreground font-mono text-[10px]">
          {fmtTime(points[0].t, range)}
        </text>
        <text x={W - PAD.r} y={H - 6} textAnchor="end" className="fill-muted-foreground font-mono text-[10px]">
          {fmtTime(points[points.length - 1].t, range)}
        </text>
      </svg>
    </Card>
  );
}

export function UsageCharts({ history }: { history: UsageHistory }) {
  const [denom, setDenom] = useState<Denominator>("pool");
  const { points, totals, range } = history;
  const projectRows = useMemo(() => {
    const byId = new Map(history.projects.map((p) => [String(p.id), p]));
    return Object.entries(history.projectShare)
      .map(([id, s]) => ({ id, project: byId.get(id), share: s }))
      .sort((a, b) => b.share.cpuAvg + b.share.gpuAvg * 8 - (a.share.cpuAvg + a.share.gpuAvg * 8));
  }, [history]);
  if (points.length === 0) {
    return (
      <EmptyState
        icon={ChartLine}
        title="還沒有取樣資料"
        description="排程器啟動後每 30 秒會寫入一筆；請稍後再看，或確認排程器（或 SCHEDULER_EMBEDDED）有在跑。"
      />
    );
  }
  const nodeMax = denom === "node";
  const pick = (s: (typeof projectRows)[number]["share"], metric: "gpu" | "cpu" | "memoryMb") => {
    const key = `${metric}Of${denom === "quota" ? "Quota" : denom === "pool" ? "Pool" : "Node"}` as const;
    return s[key as keyof typeof s] as number;
  };
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="inline-flex items-center gap-2 text-sm text-muted-foreground">
          <Info className="size-4" />
          分母：
          {denom === "quota"
            ? "各專案自己的配額（專案圖表），節點圖表以資源池為上限"
            : denom === "pool"
              ? "管理員設定的總資源池"
              : "伺服器實際總資源"}
        </p>
        <Tabs value={denom} onValueChange={(v) => setDenom(v as Denominator)}>
          <TabsList>
            <TabsTrigger value="quota">專案配額</TabsTrigger>
            <TabsTrigger value="pool">資源池</TabsTrigger>
            <TabsTrigger value="node">系統總量</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <LineChart
          title="CPU 實際使用（核）"
          points={points}
          value={(p) => (p.cpuPct == null ? undefined : (p.cpuPct / 100) * totals.cpuCores)}
          max={nodeMax ? totals.cpuCores : totals.poolCpu}
          maxLabel={nodeMax ? "系統" : "資源池"}
          format={(n) => n.toFixed(1)}
          range={range}
        />
        <LineChart
          title="CPU 已配置給任務（核）"
          points={points}
          value={(p) => p.allocCpu}
          max={nodeMax ? totals.cpuCores : totals.poolCpu}
          maxLabel={nodeMax ? "系統" : "資源池"}
          format={(n) => n.toFixed(1)}
          range={range}
        />
        <LineChart
          title="記憶體實際使用"
          points={points}
          value={(p) => p.memUsedMb}
          max={nodeMax ? totals.memoryMb : totals.poolMemoryMb}
          maxLabel={nodeMax ? "系統" : "資源池"}
          format={formatMb}
          range={range}
        />
        <LineChart
          title="記憶體已配置給任務"
          points={points}
          value={(p) => p.allocMemoryMb}
          max={nodeMax ? totals.memoryMb : totals.poolMemoryMb}
          maxLabel={nodeMax ? "系統" : "資源池"}
          format={formatMb}
          range={range}
        />
        <LineChart
          title="GPU 使用率（資源池內各卡平均）"
          points={points}
          value={(p) => p.gpuUtil}
          max={100}
          maxLabel="上限"
          format={(n) => n.toFixed(0)}
          unit="%"
          range={range}
        />
        <LineChart
          title="GPU 顯存使用（資源池內合計）"
          points={points}
          value={(p) => p.gpuMemUsedMb}
          max={totals.gpuMemoryMb}
          maxLabel="總顯存"
          format={formatMb}
          range={range}
        />
        <LineChart
          title="GPU 已配置給任務（張）"
          points={points}
          value={(p) => p.allocGpu}
          max={nodeMax ? totals.gpuCount : totals.poolGpu}
          maxLabel={nodeMax ? "系統" : "資源池"}
          format={(n) => n.toFixed(0)}
          range={range}
        />
        <LineChart
          title="執行中的任務數"
          points={points}
          value={(p) => p.runningJobs}
          max={0}
          maxLabel=""
          format={(n) => n.toFixed(0)}
          range={range}
        />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>各專案占用（此區間的時間加權平均）</CardTitle>
          <CardDescription>
            配置 = 排程器給任務的量；實際 = 任務程序量到的 CPU 核數與 PSS 記憶體。百分比以目前選的分母計算。
          </CardDescription>
        </CardHeader>
        <CardContent>
          {projectRows.length === 0 ? (
            <p className="text-sm text-muted-foreground">這段期間沒有專案跑過任務。</p>
          ) : (
            <div className="overflow-hidden rounded-lg border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>專案</TableHead>
                    <TableHead>GPU</TableHead>
                    <TableHead>CPU</TableHead>
                    <TableHead>記憶體</TableHead>
                    <TableHead className="text-right">實際 CPU / 記憶體</TableHead>
                    <TableHead className="text-right">任務時數</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {projectRows.map(({ id, project, share }) => (
                    <TableRow key={id}>
                      <TableCell>
                        <div className="font-medium">{project?.name ?? `#${id}`}</div>
                        <div className="font-mono text-xs text-muted-foreground">{project?.slug ?? id}</div>
                      </TableCell>
                      {(["gpu", "cpu", "memoryMb"] as const).map((m) => {
                        const pct = pick(share, m);
                        const avg = m === "gpu" ? share.gpuAvg : m === "cpu" ? share.cpuAvg : share.memoryMbAvg;
                        return (
                          <TableCell key={m} className="min-w-36">
                            <div className="flex items-center gap-2">
                              <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted" aria-hidden>
                                <div
                                  className={
                                    pct >= 90
                                      ? "h-full bg-destructive"
                                      : pct >= 70
                                        ? "h-full bg-warning"
                                        : "h-full bg-primary"
                                  }
                                  style={{ width: `${Math.min(100, pct)}%` }}
                                />
                              </div>
                              <span className="font-mono text-xs tabular-nums">
                                {pct.toFixed(1)}%
                                <span className="ml-1 text-muted-foreground">
                                  ({m === "memoryMb" ? formatMb(avg) : avg.toFixed(2)})
                                </span>
                              </span>
                            </div>
                          </TableCell>
                        );
                      })}
                      <TableCell className="text-right font-mono text-xs text-muted-foreground tabular-nums">
                        {share.cpuActualAvg.toFixed(2)} 核 / {formatMb(share.memActualAvgMb)}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs tabular-nums">
                        {(share.jobSeconds / 3600).toFixed(2)} h
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
