"use client";

// Choose preprocessing steps and preview them on a sample of the upload (before / after).
import { Eye, LoaderCircle, Plus, X } from "lucide-react";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { previewPreprocessAction, type ActionResult } from "@/lib/actions";
import { cn } from "@/lib/utils";
import type { ArrayStat, ColumnStat, PreprocessOp, PreprocessStep, PreviewPayload, PreviewSide } from "@/types/domain";

export function PreprocessEditor({
  ops,
  steps,
  onChange,
  slug,
  uploadId,
  spec,
  disabledReason,
  onPreview,
}: {
  ops: PreprocessOp[];
  steps: PreprocessStep[];
  onChange: (steps: PreprocessStep[]) => void;
  slug?: string;
  uploadId?: number | string;
  spec: Record<string, unknown>;
  disabledReason?: string;
  /** Replace the project preview call (standalone tool). */
  onPreview?: (steps: PreprocessStep[], spec: Record<string, unknown>) => Promise<ActionResult<PreviewPayload>>;
}) {
  const [adding, setAdding] = useState<string>("");
  const [preview, setPreview] = useState<PreviewPayload | null>(null);
  const [pending, startTransition] = useTransition();
  const byId = Object.fromEntries(ops.map((o) => [o.id, o]));

  const add = (id: string) => {
    const op = byId[id];
    if (!op) return;
    const params: Record<string, unknown> = {};
    for (const p of op.params) if (p.default !== undefined && p.default !== null) params[p.name] = p.default;
    onChange([...steps, { op: id, params }]);
    setAdding("");
  };
  const setParam = (i: number, name: string, value: unknown) =>
    onChange(steps.map((s, k) => (k === i ? { ...s, params: { ...(s.params ?? {}), [name]: value } } : s)));
  const remove = (i: number) => onChange(steps.filter((_, k) => k !== i));

  const runPreview = () => {
    if (!uploadId) return;
    startTransition(async () => {
      const r = onPreview
        ? await onPreview(steps, spec)
        : await previewPreprocessAction(slug ?? "", Number(uploadId), steps, spec, 5);
      if (!r.ok) {
        toast.error(r.error);
        return;
      }
      setPreview(r.data);
    });
  };

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        {steps.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            尚未加入前處理步驟（可選）。訓練時學到的數值（補值、標準化、對位參考…）會存進模型，推論自動沿用。
          </p>
        ) : null}
        {steps.map((s, i) => {
          const op = byId[s.op];
          return (
            <div key={`${s.op}-${i}`} className="rounded-lg border border-border bg-card p-3">
              <div className="flex items-center gap-2">
                <span className="flex size-5 items-center justify-center rounded-full bg-primary/10 font-mono text-[11px] text-brand-ink">
                  {i + 1}
                </span>
                <span className="font-medium">{op?.label ?? s.op}</span>
                <span className="font-mono text-[11px] text-subtle-foreground">{s.op}</span>
                {op?.fitted ? (
                  <span className="rounded-sm bg-muted px-1.5 text-[11px] text-muted-foreground">訓練時學習</span>
                ) : null}
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="ml-auto"
                  aria-label="移除步驟"
                  onClick={() => remove(i)}
                >
                  <X />
                </Button>
              </div>
              {op?.description ? <p className="mt-1 text-xs text-muted-foreground">{op.description}</p> : null}
              {op?.params.length ? (
                <div className="mt-3 grid gap-3 sm:grid-cols-3">
                  {op.params.map((p) => {
                    const v = s.params?.[p.name] ?? p.default ?? "";
                    const id = `pp-${i}-${p.name}`;
                    if (p.type === "bool")
                      return (
                        <label key={p.name} className="flex items-center gap-2 text-sm">
                          <Switch checked={Boolean(v)} onCheckedChange={(c) => setParam(i, p.name, c)} />
                          {p.label}
                        </label>
                      );
                    if (p.type === "choice")
                      return (
                        <div key={p.name} className="grid gap-1.5">
                          <Label htmlFor={id}>{p.label}</Label>
                          <Select
                            value={String(v)}
                            onValueChange={(x) => setParam(i, p.name, coerceChoice(p.choices, x))}
                          >
                            <SelectTrigger id={id} size="sm">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {(p.choices ?? []).map((c) => (
                                <SelectItem key={String(c)} value={String(c)}>
                                  {String(c)}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      );
                    return (
                      <div key={p.name} className="grid gap-1.5">
                        <Label htmlFor={id}>{p.label}</Label>
                        <Input
                          id={id}
                          className="h-8 font-mono text-xs"
                          type={p.type === "int" || p.type === "float" ? "number" : "text"}
                          step={p.type === "float" ? "any" : undefined}
                          min={p.min}
                          max={p.max}
                          placeholder={p.type === "columns" ? "col_a,col_b（留空 = 自動）" : undefined}
                          value={Array.isArray(v) ? v.join(",") : String(v)}
                          onChange={(e) =>
                            setParam(
                              i,
                              p.name,
                              p.type === "int"
                                ? e.target.value === ""
                                  ? ""
                                  : Number.parseInt(e.target.value, 10)
                                : p.type === "float"
                                  ? e.target.value === ""
                                    ? ""
                                    : Number(e.target.value)
                                  : e.target.value,
                            )
                          }
                        />
                        {p.help ? <p className="text-[11px] text-muted-foreground">{p.help}</p> : null}
                      </div>
                    );
                  })}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Select value={adding} onValueChange={add}>
          <SelectTrigger className="w-72" aria-label="新增前處理步驟">
            <SelectValue placeholder="＋ 新增步驟…" />
          </SelectTrigger>
          <SelectContent>
            {ops.map((o) => (
              <SelectItem key={o.id} value={o.id} disabled={o.geometric && Boolean(disabledReason)}>
                {o.label}
                <span className="ml-2 font-mono text-[11px] text-muted-foreground">{o.id}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button type="button" variant="outline" size="sm" onClick={runPreview} disabled={!uploadId || pending}>
          {pending ? <LoaderCircle className="animate-spin" /> : <Eye />}
          抽樣預覽
        </Button>
        {!uploadId ? (
          <span className="text-xs text-muted-foreground">預覽需要先上傳檔案（資料來源會在任務內處理）。</span>
        ) : null}
        {disabledReason ? <span className="text-xs text-warning">{disabledReason}</span> : null}
      </div>
      {preview ? <PreviewView payload={preview} /> : null}
      <Plus className="hidden" />
    </div>
  );
}

function coerceChoice(choices: unknown[] | undefined, value: string): unknown {
  const match = (choices ?? []).find((c) => String(c) === value);
  return match === undefined ? value : match;
}

export function PreviewView({ payload }: { payload: PreviewPayload }) {
  return (
    <div className="space-y-3 rounded-xl border border-primary/30 bg-primary/5 p-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">抽樣預覽</span>
        <span className="text-xs text-muted-foreground">{payload.steps.join(" → ") || "（沒有步驟）"}</span>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Side title="處理前" side={payload.before} dataType={payload.data_type} />
        <Side title="處理後" side={payload.after} dataType={payload.data_type} highlight />
      </div>
    </div>
  );
}

function Side({
  title,
  side,
  dataType,
  highlight,
}: {
  title: string;
  side: PreviewSide;
  dataType: string;
  highlight?: boolean;
}) {
  return (
    <div
      className={cn(
        "min-w-0 space-y-2 rounded-lg border bg-card p-3",
        highlight ? "border-primary/40" : "border-border",
      )}
    >
      <div className="flex items-baseline justify-between">
        <span className="text-label">{title}</span>
        {side.row_count !== undefined ? (
          <span className="font-mono text-xs text-muted-foreground tabular-nums">{side.row_count} 列</span>
        ) : null}
      </div>
      {Array.isArray(side.stats) ? (
        <StatsTable stats={side.stats} />
      ) : side.stats ? (
        <ArrayStats stats={side.stats} />
      ) : null}
      {side.rows ? <RowsTable columns={side.columns ?? []} rows={side.rows} /> : null}
      {side.images ? (
        <div className="flex flex-wrap gap-2">
          {side.images.map((im) => (
            <figure key={im.id} className="w-28 text-center">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`data:image/png;base64,${im.png_base64}`}
                alt={im.id}
                className="h-24 w-28 rounded-md border border-border bg-muted object-contain"
              />
              <figcaption className="mt-1 truncate font-mono text-[10px] text-muted-foreground" title={im.id}>
                {im.width}×{im.height} · μ{Math.round(im.mean)}
              </figcaption>
            </figure>
          ))}
        </div>
      ) : null}
      {side.curves ? <Curves curves={side.curves} /> : null}
      {dataType === "TEXT" && side.rows ? null : null}
    </div>
  );
}

function ArrayStats({ stats }: { stats: ArrayStat }) {
  const fmt = (v?: number) =>
    v === undefined || Number.isNaN(v) ? "—" : Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(3);
  const cells: [string, string][] = [
    ["shape", stats.shape.join(" × ")],
    ["平均", fmt(stats.mean)],
    ["標準差", fmt(stats.std)],
    ["最小", fmt(stats.min)],
    ["最大", fmt(stats.max)],
    ["NaN 比例", stats.nan_ratio === undefined ? "—" : `${(stats.nan_ratio * 100).toFixed(1)}%`],
  ];
  return (
    <dl className="grid grid-cols-3 gap-x-3 gap-y-1 rounded-md border border-border p-2 font-mono text-xs tabular-nums">
      {cells.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-2">
          <dt className="text-muted-foreground">{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function StatsTable({ stats }: { stats: ColumnStat[] }) {
  const fmt = (v?: number) =>
    v === undefined || Number.isNaN(v) ? "—" : Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(3);
  return (
    <div className="max-h-56 overflow-auto rounded-md border border-border">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-muted text-left text-muted-foreground">
          <tr>
            <th className="px-2 py-1">欄位</th>
            <th className="px-2 py-1 text-right">缺值</th>
            <th className="px-2 py-1 text-right">平均</th>
            <th className="px-2 py-1 text-right">標準差</th>
            <th className="px-2 py-1 text-right">最小</th>
            <th className="px-2 py-1 text-right">最大</th>
          </tr>
        </thead>
        <tbody className="font-mono tabular-nums">
          {stats.map((s) => (
            <tr key={s.column} className="border-t border-border">
              <td className="px-2 py-1 font-sans">{s.column}</td>
              <td className={cn("px-2 py-1 text-right", s.missing > 0 && "text-warning")}>{s.missing}</td>
              <td className="px-2 py-1 text-right">{fmt(s.mean)}</td>
              <td className="px-2 py-1 text-right">{fmt(s.std)}</td>
              <td className="px-2 py-1 text-right">{fmt(s.min)}</td>
              <td className="px-2 py-1 text-right">{fmt(s.max)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RowsTable({ columns, rows }: { columns: string[]; rows: Record<string, unknown>[] }) {
  return (
    <div className="max-h-40 overflow-auto rounded-md border border-border">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-muted text-left text-muted-foreground">
          <tr>
            {columns.map((c) => (
              <th key={c} className="px-2 py-1 whitespace-nowrap">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="font-mono tabular-nums">
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-border">
              {columns.map((c) => (
                <td key={c} className="px-2 py-1 whitespace-nowrap">
                  {r[c] === null || r[c] === undefined ? (
                    <span className="text-warning">∅</span>
                  ) : typeof r[c] === "number" ? (
                    (r[c] as number).toFixed(3)
                  ) : (
                    String(r[c]).slice(0, 40)
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Curves({ curves }: { curves: NonNullable<PreviewSide["curves"]> }) {
  const all = curves.flatMap((c) => c.values.flat());
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const W = 320;
  const H = 120;
  const sx = (i: number, n: number) => (n <= 1 ? 0 : (i / (n - 1)) * W);
  const sy = (v: number) => (hi === lo ? H / 2 : H - ((v - lo) / (hi - lo)) * (H - 8) - 4);
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="h-32 w-full rounded-md border border-border bg-background"
      role="img"
      aria-label="曲線預覽"
    >
      {curves.map((c, ci) =>
        c.values.map((series, si) => (
          <polyline
            key={`${c.id}-${si}`}
            fill="none"
            strokeWidth={1.2}
            className={ci === 0 ? "stroke-primary" : "stroke-muted-foreground/60"}
            points={series.map((v, i) => `${sx(i, series.length).toFixed(1)},${sy(v).toFixed(1)}`).join(" ")}
          />
        )),
      )}
    </svg>
  );
}
