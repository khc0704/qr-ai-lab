"use client";

// Report of an analysis job. Charts follow the usage page: one hue, labels only where they carry information,
// tables as the data view. Groups in the image scatter get categorical token colors.
import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { analysisCopy } from "@/i18n/zh-TW";
import { formatMetric } from "@/lib/format";
import { SampleViewer } from "@/components/features/sample-viewer";
import { jobKey } from "@/lib/local-data";
import { cn } from "@/lib/utils";
import type { Job } from "@/types/domain";

type J = Record<string, unknown>;
type Rec = { level?: string; text?: string };

const num = (v: unknown, d = 0) => (typeof v === "number" && Number.isFinite(v) ? v : d);
const arr = <T,>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);

function Recommendations({ items }: { items: Rec[] }) {
  if (!items.length) return null;
  return (
    <Card data-testid="analysis-recommendations">
      <CardHeader>
        <CardTitle>建議</CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2 text-sm">
          {items.map((r, i) => (
            <li key={i} className="flex gap-2">
              <span
                className={cn(
                  "mt-1.5 size-2 shrink-0 rounded-full",
                  r.level === "warn" ? "bg-warning" : r.level === "error" ? "bg-destructive" : "bg-primary",
                )}
                aria-hidden
              />
              <span>{r.text}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function BarList({
  rows,
  max,
  format = (v) => formatMetric(v),
}: {
  rows: { label: string; value: number; hint?: string }[];
  max?: number;
  format?: (v: number) => string;
}) {
  const top = max ?? Math.max(...rows.map((r) => Math.abs(r.value)), 1e-9);
  return (
    <ul className="space-y-1.5">
      {rows.map((r, i) => (
        <li key={r.label} className="grid grid-cols-[minmax(0,160px)_1fr_auto] items-center gap-3 text-xs">
          <span className="truncate font-mono" title={r.label}>
            {r.label}
          </span>
          <div className="h-2 overflow-hidden rounded-full bg-muted" aria-hidden>
            <div
              className={cn("h-full rounded-full", i === 0 ? "bg-primary" : "bg-primary/60")}
              style={{ width: `${Math.min(100, (Math.abs(r.value) / top) * 100)}%` }}
            />
          </div>
          <span className="font-mono text-muted-foreground tabular-nums">
            {format(r.value)}
            {r.hint ? <span className="ml-1">{r.hint}</span> : null}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Heatmap({ columns, matrix }: { columns: string[]; matrix: (number | null)[][] }) {
  const [hover, setHover] = useState<[number, number] | null>(null);
  const n = columns.length;
  if (n < 2) return null;
  const cell = Math.max(10, Math.min(28, Math.floor(560 / n)));
  const label = Math.min(120, 7 * Math.max(...columns.map((c) => c.length)) + 8);
  const w = label + n * cell;
  const h = label + n * cell;
  const hv = hover ? matrix[hover[0]]?.[hover[1]] : null;
  return (
    <figure className="space-y-2">
      <figcaption className="flex items-baseline justify-between text-xs text-muted-foreground">
        <span>Pearson 相關係數：橘 = 正相關、藍 = 負相關，越深越強</span>
        <span className="font-mono tabular-nums">
          {hover && hv != null ? `${columns[hover[0]]} × ${columns[hover[1]]} = ${hv.toFixed(2)}` : `${n} 欄`}
        </span>
      </figcaption>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="w-full max-w-3xl"
        role="img"
        aria-label="相關係數矩陣"
        onMouseLeave={() => setHover(null)}
      >
        {columns.map((c, i) => (
          <g key={c}>
            <text
              x={label - 4}
              y={label + i * cell + cell * 0.7}
              textAnchor="end"
              className="fill-muted-foreground font-mono text-[9px]"
            >
              {c.length > 16 ? `${c.slice(0, 15)}…` : c}
            </text>
            <text
              x={label + i * cell + cell / 2}
              y={label - 4}
              transform={`rotate(-60 ${label + i * cell + cell / 2} ${label - 4})`}
              className="fill-muted-foreground font-mono text-[9px]"
            >
              {c.length > 16 ? `${c.slice(0, 15)}…` : c}
            </text>
          </g>
        ))}
        {matrix.map((row, i) =>
          row.map((v, j) => (
            <rect
              key={`${i}-${j}`}
              x={label + j * cell}
              y={label + i * cell}
              width={cell - 1}
              height={cell - 1}
              className={v == null ? "fill-muted" : v >= 0 ? "fill-primary" : "fill-info"}
              style={{ opacity: v == null ? 0.3 : 0.12 + 0.88 * Math.abs(v) }}
              onMouseEnter={() => setHover([i, j])}
            />
          )),
        )}
      </svg>
    </figure>
  );
}

const GROUP_CLASSES = ["fill-primary", "fill-info", "fill-success", "fill-warning", "fill-signal", "fill-destructive"];

function Scatter({
  points,
  labels,
  onSelect,
}: {
  points: { id: string; group: string; x: number; y: number; outlier: number }[];
  labels: string[];
  /** Click a point to open its image (the file is read from this browser's copy of the upload). */
  onSelect?: (id: string) => void;
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (!points.length) return null;
  const W = 560;
  const H = 320;
  const pad = 24;
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  const [y0, y1] = [Math.min(...ys), Math.max(...ys)];
  const sx = (x: number) => pad + ((x - x0) / (x1 - x0 || 1)) * (W - 2 * pad);
  const sy = (y: number) => H - pad - ((y - y0) / (y1 - y0 || 1)) * (H - 2 * pad);
  const cls = (g: string) => GROUP_CLASSES[Math.max(0, labels.indexOf(g)) % GROUP_CLASSES.length];
  return (
    <figure className="space-y-2">
      <figcaption className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>
          embedding 的前兩個主成分（PCA）；顏色 = 群組，空心圈 = 偏離群組的影像{onSelect ? "；點一點看影像" : ""}
        </span>
        <span className="flex flex-wrap gap-3">
          {labels.map((l) => (
            <span key={l} className="inline-flex items-center gap-1">
              <svg width="10" height="10" aria-hidden>
                <circle cx="5" cy="5" r="4" className={cls(l)} />
              </svg>
              {l}
            </span>
          ))}
        </span>
      </figcaption>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full max-w-3xl rounded-lg border border-border"
        role="img"
        aria-label="embedding 散佈圖"
        onMouseLeave={() => setHover(null)}
      >
        {points.map((p, i) => (
          <circle
            key={p.id}
            cx={sx(p.x)}
            cy={sy(p.y)}
            r={hover === i ? 6 : p.outlier > 3.5 ? 5 : 3.5}
            style={{
              opacity: hover == null || hover === i ? 0.85 : 0.35,
              fill: p.outlier > 3.5 ? "transparent" : undefined,
            }}
            strokeWidth={p.outlier > 3.5 ? 1.5 : 0}
            onMouseEnter={() => setHover(i)}
            onClick={onSelect ? () => onSelect(p.id) : undefined}
            className={cn(cls(p.group), p.outlier > 3.5 && "stroke-foreground", onSelect && "cursor-pointer")}
          >
            <title>{`${p.id} (${p.group})`}</title>
          </circle>
        ))}
        {hover != null ? (
          <text x={pad} y={H - 8} className="fill-muted-foreground font-mono text-[10px]">
            {points[hover].id} · {points[hover].group} · outlier z = {points[hover].outlier}
          </text>
        ) : null}
      </svg>
    </figure>
  );
}

export function TabularProfileReport({ result }: { result: J }) {
  const columns = arr<J>(result.columns);
  const corr = (result.correlation as J) ?? {};
  const rel = (result.relevance as J) ?? {};
  const feats = arr<J>(rel.features);
  const vif = arr<J>((result.collinearity as J)?.vif);
  const model = (rel.model as J) ?? {};
  return (
    <div className="space-y-4" data-testid="analysis-tabular">
      <div className="grid gap-3 sm:grid-cols-3">
        {[
          ["列數", String(num(result.rows))],
          ["欄位", String(num(result.columns_total))],
          ["目標", rel.target ? `${String(rel.target)}（${rel.task === "regression" ? "迴歸" : "分類"}）` : "未指定"],
        ].map(([k, v]) => (
          <Card key={k} className="gap-1 p-4">
            <div className="text-label">{k}</div>
            <div className="font-mono text-sm tabular-nums">{v}</div>
          </Card>
        ))}
      </div>
      <Recommendations items={arr<Rec>(result.recommendations)} />
      {feats.length ? (
        <Card>
          <CardHeader>
            <CardTitle>對目標的解釋力</CardTitle>
            <CardDescription>
              綜合分數 = 0.5 × 互資訊（正規化）+ 0.3 × 置換重要度占比 + 0.2 × |相關性|。
              {"holdout_score" in model
                ? ` 隨機森林保留集 ${String(model.metric)} = ${num(model.holdout_score).toFixed(3)}（${num(model.train_rows)} / ${num(model.test_rows)} 列）。`
                : ""}
              {typeof model.permutation_rows === "number" || Array.isArray(model.columns_used)
                ? ` 置換重要度${typeof model.permutation_rows === "number" ? `以 ${num(model.permutation_rows)} 列計算` : ""}${
                    Array.isArray(model.columns_used) ? `，使用 ${arr<string>(model.columns_used).length} 欄` : ""
                  }；未納入模型的欄位顯示「${analysisCopy.permutationSkipped}」。`
                : ""}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <BarList
              rows={feats.slice(0, 15).map((f) => ({
                label: String(f.name),
                value: num(f.score),
                hint: f.kind === "categorical" ? "類別" : undefined,
              }))}
              max={1}
              format={(v) => v.toFixed(3)}
            />
            <div className="overflow-hidden rounded-lg border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>欄位</TableHead>
                    <TableHead className="text-right">互資訊</TableHead>
                    <TableHead className="text-right">相關 / η</TableHead>
                    <TableHead className="text-right">置換重要度</TableHead>
                    <TableHead className="text-right">分數</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {feats.slice(0, 40).map((f) => (
                    <TableRow key={String(f.name)}>
                      <TableCell className="font-mono text-xs">{String(f.name)}</TableCell>
                      <TableCell className="text-right font-mono text-xs tabular-nums">
                        {num(f.mutual_info).toFixed(4)}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs tabular-nums">
                        {f.corr_target == null ? "—" : num(f.corr_target).toFixed(3)}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs tabular-nums">
                        {f.permutation_skipped === true ? (
                          <span className="font-sans text-muted-foreground">{analysisCopy.permutationSkipped}</span>
                        ) : f.permutation_importance == null ? (
                          "—"
                        ) : (
                          num(f.permutation_importance).toFixed(4)
                        )}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs font-semibold tabular-nums">
                        {num(f.score).toFixed(3)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>相關性</CardTitle>
            <CardDescription>|r| ≥ 0.7 的欄位對列在下方；≥ 0.9 視為共線。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Heatmap columns={arr<string>(corr.columns)} matrix={arr<(number | null)[]>(corr.matrix)} />
            {arr<J>(corr.high_pairs).length ? (
              <BarList
                rows={arr<J>(corr.high_pairs)
                  .slice(0, 12)
                  .map((p) => ({ label: `${String(p.a)} ↔ ${String(p.b)}`, value: num(p.r) }))}
                max={1}
                format={(v) => v.toFixed(2)}
              />
            ) : (
              <p className="text-xs text-muted-foreground">沒有 |r| ≥ 0.7 的欄位對。</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>共線性（VIF）</CardTitle>
            <CardDescription>VIF &gt; 10 表示該欄位幾乎能由其他欄位線性組合出來。</CardDescription>
          </CardHeader>
          <CardContent>
            {vif.length ? (
              <BarList
                rows={vif.slice(0, 15).map((v) => ({
                  label: String(v.name),
                  value: v.vif == null ? 100 : Math.min(100, num(v.vif)),
                  hint: v.vif == null ? "∞" : undefined,
                }))}
                max={100}
                format={(v) => (v >= 100 ? "≥100" : v.toFixed(1))}
              />
            ) : (
              <p className="text-xs text-muted-foreground">數值欄位少於 2 個，略過。</p>
            )}
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>欄位概況</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-auto rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>欄位</TableHead>
                  <TableHead>型別</TableHead>
                  <TableHead className="text-right">缺值</TableHead>
                  <TableHead className="text-right">相異值</TableHead>
                  <TableHead className="text-right">平均</TableHead>
                  <TableHead className="text-right">標準差</TableHead>
                  <TableHead className="text-right">離群</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {columns.map((c) => (
                  <TableRow key={String(c.name)}>
                    <TableCell className="font-mono text-xs">{String(c.name)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{String(c.dtype)}</TableCell>
                    <TableCell
                      className={cn(
                        "text-right font-mono text-xs tabular-nums",
                        num(c.missing_ratio) > 0.3 && "text-warning",
                      )}
                    >
                      {(num(c.missing_ratio) * 100).toFixed(1)}%
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">{num(c.unique)}</TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {c.mean == null ? "—" : formatMetric(num(c.mean))}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {c.std == null ? "—" : formatMetric(num(c.std))}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {c.outlier_ratio == null ? "—" : `${(num(c.outlier_ratio) * 100).toFixed(1)}%`}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export function ImageQualityReport({ result, job }: { result: J; job?: Job }) {
  const [selected, setSelected] = useState<string | null>(null);
  const groups = arr<J>(result.groups);
  const drift = arr<J>(result.drift);
  // Metrics without enough images (< 3 per group) or zero within-group spread have no ratio: shown as
  // "樣本不足" with the backend's note and left out of the ranking.
  const insufficient = (d: J) => d.insufficient === true || typeof d.drift_ratio !== "number";
  const ranked = drift.filter((d) => !insufficient(d));
  const sim = (result.similarity as J) ?? {};
  const labels = arr<string>(sim.labels);
  const matrix = arr<number[]>(sim.matrix);
  const points = arr<{ id: string; group: string; x: number; y: number; outlier: number }>(result.points);
  const outliers = arr<J>(result.outliers);
  return (
    <div className="space-y-4" data-testid="analysis-image">
      <div className="grid gap-3 sm:grid-cols-4">
        {[
          ["影像", String(num(result.images_total))],
          ["群組", String(groups.length)],
          ["embedding", String(result.embedding ?? "metrics")],
          ["silhouette", result.silhouette == null ? "—" : num(result.silhouette).toFixed(3)],
        ].map(([k, v]) => (
          <Card key={k} className="gap-1 p-4">
            <div className="text-label">{k}</div>
            <div className="font-mono text-sm tabular-nums">{v}</div>
          </Card>
        ))}
      </div>
      <Recommendations items={arr<Rec>(result.recommendations)} />
      <Card>
        <CardHeader>
          <CardTitle>最會飄的指標</CardTitle>
          <CardDescription>
            飄移比 = 群組中位數的最大差 ÷ 群內 IQR 的中位數；&gt; 1 表示群組差異超過群內變異。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {ranked.length ? (
            <BarList
              rows={ranked.slice(0, 10).map((d) => ({
                label: String(d.label ?? d.metric),
                value: num(d.drift_ratio),
                hint: d.p_value == null ? undefined : `p=${num(d.p_value).toExponential(1)}`,
              }))}
              format={(v) => `${v.toFixed(2)}×`}
            />
          ) : (
            <p className="text-xs text-muted-foreground">每個群組至少需要 3 張影像才能計算飄移比。</p>
          )}
          <div className="overflow-auto rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>指標</TableHead>
                  {groups.map((g) => (
                    <TableHead key={String(g.name)} className="text-right">
                      {String(g.name)}{" "}
                      <span className="font-mono text-[10px] text-subtle-foreground">n={num(g.images)}</span>
                      {g.insufficient === true ? (
                        <span className="ml-1 text-[10px] text-warning">{analysisCopy.insufficient}</span>
                      ) : null}
                    </TableHead>
                  ))}
                  <TableHead className="text-right">飄移比</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {drift.map((d) => (
                  <TableRow key={String(d.metric)}>
                    <TableCell className="text-xs">{String(d.label ?? d.metric)}</TableCell>
                    {groups.map((g) => (
                      <TableCell key={String(g.name)} className="text-right font-mono text-xs tabular-nums">
                        {formatMetric(num((d.group_medians as J)?.[String(g.name)]))}
                      </TableCell>
                    ))}
                    {insufficient(d) ? (
                      <TableCell
                        className="text-right text-xs text-muted-foreground"
                        title={d.note ? String(d.note) : undefined}
                      >
                        {analysisCopy.insufficient}
                        {d.note ? <span className="ml-1 text-subtle-foreground">（{String(d.note)}）</span> : null}
                      </TableCell>
                    ) : (
                      <TableCell
                        className={cn(
                          "text-right font-mono text-xs tabular-nums",
                          num(d.drift_ratio) > 1 && "font-semibold text-warning",
                        )}
                      >
                        {num(d.drift_ratio).toFixed(2)}
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Card>
          <CardHeader>
            <CardTitle>embedding 分佈</CardTitle>
          </CardHeader>
          <CardContent>
            <Scatter points={points} labels={labels} onSelect={job ? setSelected : undefined} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>群組相似度</CardTitle>
            <CardDescription>群組 centroid 的 cosine 相似度（1 = 相同）。</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="overflow-auto rounded-lg border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead />
                    {labels.map((l) => (
                      <TableHead key={l} className="text-right">
                        {l}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {matrix.map((row, i) => (
                    <TableRow key={labels[i]}>
                      <TableCell className="text-xs font-medium">{labels[i]}</TableCell>
                      {row.map((v, j) => (
                        <TableCell
                          key={j}
                          className={cn(
                            "text-right font-mono text-xs tabular-nums",
                            i !== j && v < 0.9 && "text-warning",
                          )}
                        >
                          {v.toFixed(3)}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {outliers.length ? (
              <div className="mt-4 space-y-1 text-xs">
                <div className="text-label">偏離自己群組的影像</div>
                {outliers.slice(0, 8).map((o) => (
                  <div key={String(o.id)} className="flex justify-between gap-2 font-mono">
                    {job ? (
                      <button
                        type="button"
                        className="truncate text-left text-brand-ink hover:underline"
                        onClick={() => setSelected(String(o.id))}
                      >
                        {String(o.id)}
                      </button>
                    ) : (
                      <span className="truncate">{String(o.id)}</span>
                    )}
                    <span className="text-muted-foreground">
                      {String(o.group)} · z={num(o.score).toFixed(1)}
                    </span>
                  </div>
                ))}
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>
      {job ? (
        <SampleViewer
          open={selected !== null}
          onOpenChange={(o) => (o ? undefined : setSelected(null))}
          dataKey={jobKey(job.id)}
          target={selected ? { ref: { id: selected } } : null}
          fingerprint={{
            name: job.input.originalFilename,
            size: job.input.fingerprint?.sizeBytes ?? job.input.sizeBytes,
            sha256: job.input.fingerprint?.sha256,
          }}
          accept=".zip"
        />
      ) : null}
    </div>
  );
}

export function AnalysisReport({ result, job }: { result: J; job?: Job }) {
  if (result.analysis === "image_quality") return <ImageQualityReport result={result} job={job} />;
  return <TabularProfileReport result={result} />;
}
