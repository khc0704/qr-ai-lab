"use client";

// The preprocessing editor: a spreadsheet of the preview sample with per-column menus, row-level operations,
// the step chain as chips and a live (debounced) preview. Non-tabular data types fall back to the step list.
import { ArrowDown, ArrowUp, Eye, LoaderCircle, Settings2, TriangleAlert, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { PreprocessEditor } from "@/components/features/preprocess-editor";
import { PreprocessGrid, type ColumnAction } from "@/components/features/preprocess-grid";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type { ActionResult } from "@/lib/actions";
import {
  addColumnStep,
  addStep,
  changedCells,
  classifyOp,
  columnDiff,
  describeParams,
  moveStep,
  removeStep,
  updateStepParams,
} from "@/lib/preprocess-steps";
import { cn } from "@/lib/utils";
import type {
  DataType,
  PreprocessOp,
  PreprocessParam,
  PreprocessStep,
  PreviewColumnStat,
  PreviewPayload,
} from "@/types/domain";

export const PREVIEW_ROWS = 300;

export type PreviewFn = (
  steps: PreprocessStep[],
  spec: Record<string, unknown>,
  sample: number,
) => Promise<ActionResult<PreviewPayload>>;

export function isGridType(dataType: DataType) {
  return dataType === "TABULAR" || dataType === "TEXT";
}

export function PreprocessWorkbench({
  ops,
  steps,
  onChange,
  dataType,
  spec,
  uploadId,
  onPreview,
  disabledReason,
  onPreviewLoaded,
}: {
  ops: PreprocessOp[];
  steps: PreprocessStep[];
  onChange: (steps: PreprocessStep[]) => void;
  dataType: DataType;
  spec: Record<string, unknown>;
  uploadId?: number | string;
  onPreview: PreviewFn;
  disabledReason?: string;
  /** Lets the host keep a summary (rows in / out, warnings) outside the drawer. */
  onPreviewLoaded?: (payload: PreviewPayload) => void;
}) {
  const [preview, setPreview] = useState<PreviewPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState<"after" | "before">("after");
  const seq = useRef(0);
  const specKey = JSON.stringify(spec);
  const stepsKey = JSON.stringify(steps);
  // Parents pass inline objects / callbacks; keep the latest ones in a ref (written in an effect, never during
  // render) so the debounced preview only re-arms when the serialised inputs change.
  const latest = useRef({ steps, spec, onPreview, onPreviewLoaded });
  useEffect(() => {
    latest.current = { steps, spec, onPreview, onPreviewLoaded };
  });
  const runPreview = useCallback(() => {
    if (!uploadId) return;
    const { steps: st, spec: sp, onPreview: fn, onPreviewLoaded: loaded } = latest.current;
    const my = ++seq.current;
    setLoading(true);
    void fn(st, sp, PREVIEW_ROWS).then((r) => {
      if (my !== seq.current) return;
      setLoading(false);
      if (!r.ok) {
        toast.error(r.error);
        return;
      }
      setPreview(r.data);
      loaded?.(r.data);
    });
  }, [uploadId]);
  // Debounced live preview whenever the steps / spec / upload change (TABULAR / TEXT only).
  useEffect(() => {
    if (!uploadId || !isGridType(dataType)) return;
    const t = setTimeout(runPreview, 400);
    return () => clearTimeout(t);
  }, [uploadId, stepsKey, specKey, dataType, runPreview]);

  if (!isGridType(dataType)) {
    return (
      <PreprocessEditor
        ops={ops}
        steps={steps}
        onChange={onChange}
        uploadId={uploadId}
        spec={spec}
        disabledReason={disabledReason}
        onPreview={(s, sp) => onPreview(s, sp, 5)}
      />
    );
  }
  return (
    <TabularWorkbench
      ops={ops}
      steps={steps}
      onChange={onChange}
      spec={spec}
      uploadId={uploadId}
      preview={preview}
      loading={loading}
      view={view}
      setView={setView}
      refresh={runPreview}
    />
  );
}

function TabularWorkbench({
  ops,
  steps,
  onChange,
  spec,
  uploadId,
  preview,
  loading,
  view,
  setView,
  refresh,
}: {
  ops: PreprocessOp[];
  steps: PreprocessStep[];
  onChange: (steps: PreprocessStep[]) => void;
  spec: Record<string, unknown>;
  uploadId?: number | string;
  preview: PreviewPayload | null;
  loading: boolean;
  view: "after" | "before";
  setView: (v: "after" | "before") => void;
  refresh: () => void;
}) {
  const byId = useMemo(() => Object.fromEntries(ops.map((o) => [o.id, o])), [ops]);
  const columnOps = ops.filter((o) => classifyOp(o) === "column" && !/drop_columns|keep_columns/.test(o.id));
  const rowOps = ops.filter((o) => classifyOp(o) === "row");
  const dropOp = ops.find((o) => o.id.endsWith(".drop_columns"));
  const actions: ColumnAction[] = columnOps.map((op) => {
    const choice = op.params.find((p) => p.type === "choice" && p.choices?.length);
    return choice ? { op, choice: { name: choice.name, label: choice.label, values: choice.choices ?? [] } } : { op };
  });
  const protectedColumns = new Set(
    ["target", "id_column", "label_column", "label", "text_column"]
      .map((k) => spec[k])
      .filter((v): v is string => typeof v === "string" && v.length > 0),
  );
  const side = view === "after" ? preview?.after : preview?.before;
  const statsList = (view === "after" ? preview?.columns_out : preview?.columns_in) ?? [];
  const stats = new Map<string, PreviewColumnStat>(statsList.map((c) => [c.name, c]));
  const columns = side?.columns ?? statsList.map((c) => c.name);
  const rows = side?.rows ?? [];
  const changed = useMemo(
    () => (view === "after" ? changedCells(preview?.before.rows, preview?.after.rows, columns) : new Set<never>()),
    [preview, view, columns],
  );
  const diff = columnDiff(preview?.columns_in, preview?.columns_out);
  const warnings = preview?.warnings ?? [];
  const [adding, setAdding] = useState("");

  const onColumnAction = (op: PreprocessOp, column: string, extra?: Record<string, unknown>) => {
    onChange(addColumnStep(steps, op, column, extra));
    if (op.id.endsWith(".encode") && extra?.method === "ordinal") {
      toast.info("序數編碼：請在步驟的參數裡填入類別順序（order）");
    }
  };
  const addGeneric = (id: string) => {
    const op = byId[id];
    if (!op) return;
    onChange(addStep(steps, op));
    setAdding("");
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {/* toolbar: row-level ops, generic add, preview controls */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-label">列 / 整表</span>
        {rowOps.map((op) => (
          <Button key={op.id} type="button" variant="outline" size="sm" onClick={() => onChange(addStep(steps, op))}>
            {op.label}
          </Button>
        ))}
        <Select value={adding} onValueChange={addGeneric}>
          <SelectTrigger className="w-60" size="sm" aria-label="新增前處理步驟">
            <SelectValue placeholder="＋ 新增步驟（套用到全部欄位）…" />
          </SelectTrigger>
          <SelectContent>
            {ops.map((o) => (
              <SelectItem key={o.id} value={o.id}>
                {o.label}
                <span className="ml-2 font-mono text-[11px] text-muted-foreground">{o.id}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="ml-auto flex items-center gap-2">
          <div className="flex rounded-md border border-border p-0.5" role="tablist" aria-label="顯示">
            {(["before", "after"] as const).map((v) => (
              <button
                key={v}
                type="button"
                role="tab"
                aria-selected={view === v}
                onClick={() => setView(v)}
                className={cn(
                  "rounded-sm px-2 py-1 text-xs transition-colors",
                  view === v
                    ? "bg-secondary font-medium text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {v === "before" ? "原始" : "處理後"}
              </button>
            ))}
          </div>
          <Button type="button" variant="outline" size="sm" onClick={refresh} disabled={!uploadId || loading}>
            {loading ? <LoaderCircle className="animate-spin" /> : <Eye />}
            抽樣預覽
          </Button>
        </div>
      </div>

      {/* step chain */}
      <div className="flex flex-wrap items-center gap-1.5" data-testid="step-chips">
        <span className="text-label">步驟</span>
        {steps.length === 0 ? (
          <span className="text-xs text-muted-foreground">
            還沒有步驟：按欄位標頭的 ⋯ 對單一欄位操作，或用上面的按鈕處理整表。
          </span>
        ) : null}
        {steps.map((s, i) => {
          const op = byId[s.op];
          const stepWarnings = preview?.step_details?.[i]?.warnings ?? [];
          return (
            <StepChip
              key={`${s.op}-${i}`}
              index={i}
              step={s}
              op={op}
              warnings={stepWarnings}
              onMove={(d) => onChange(moveStep(steps, i, i + d))}
              onRemove={() => onChange(removeStep(steps, i))}
              onParams={(p) => onChange(updateStepParams(steps, i, p))}
              first={i === 0}
              last={i === steps.length - 1}
            />
          );
        })}
      </div>

      {/* summary + warnings */}
      {preview ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs tabular-nums">
          <span>
            輸入 <b>{preview.rows_in ?? preview.before.row_count ?? "?"}</b> 列 → 輸出{" "}
            <b>{preview.rows_out ?? preview.after.row_count ?? "?"}</b> 列
            {preview.rows_in != null && preview.rows_out != null && preview.rows_in !== preview.rows_out ? (
              <span className="text-warning">（移除 {preview.rows_in - preview.rows_out} 列）</span>
            ) : null}
          </span>
          <span>
            欄位 <b>{preview.columns_in?.length ?? "?"}</b> → <b>{preview.columns_out?.length ?? "?"}</b>
            {diff.added.length ? <span className="text-success">（新增 {diff.added.join(", ")}）</span> : null}
            {diff.dropped.length ? (
              <span className="text-muted-foreground">（移除 {diff.dropped.join(", ")}）</span>
            ) : null}
          </span>
          {changed.size ? <span className="text-brand-ink">{changed.size} 格有變動</span> : null}
          <span className="text-muted-foreground">只取樣前 {PREVIEW_ROWS} 列預覽；整個檔案由任務處理</span>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">{uploadId ? "計算預覽中…" : "上傳檔案後會自動抽樣預覽。"}</p>
      )}
      {warnings.length ? (
        <Alert className="border-warning/30 bg-warning/10">
          <TriangleAlert className="text-warning" />
          <AlertTitle>預覽發現的問題</AlertTitle>
          <AlertDescription>
            <ul className="list-disc space-y-0.5 pl-4">
              {warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}

      {/* grid */}
      <div className="min-h-0 flex-1" style={{ minHeight: 280 }}>
        <PreprocessGrid
          className="h-full max-h-[60vh]"
          columns={columns}
          rows={rows}
          stats={stats}
          changed={changed}
          protectedColumns={protectedColumns}
          actions={actions}
          dropOp={dropOp}
          onColumnAction={onColumnAction}
          loading={loading}
        />
      </div>
    </div>
  );
}

function StepChip({
  index,
  step,
  op,
  warnings,
  onMove,
  onRemove,
  onParams,
  first,
  last,
}: {
  index: number;
  step: PreprocessStep;
  op?: PreprocessOp;
  warnings: string[];
  onMove: (delta: number) => void;
  onRemove: () => void;
  onParams: (params: Record<string, unknown>) => void;
  first: boolean;
  last: boolean;
}) {
  const label = op?.label ?? step.op;
  const summary = describeParams(step.params);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border bg-card py-0.5 pr-0.5 pl-2 text-xs",
        warnings.length ? "border-warning/40" : "border-border",
      )}
    >
      <span className="font-mono text-[11px] text-brand-ink">{index + 1}</span>
      <span className="font-medium">{label}</span>
      {summary ? (
        <span className="max-w-56 truncate font-mono text-[11px] text-muted-foreground">{summary}</span>
      ) : null}
      {warnings.length ? (
        <TriangleAlert className="size-3.5 text-warning" aria-label={`${warnings.length} 個警告`} />
      ) : null}
      {op?.params.length ? (
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label={`編輯步驟 ${index + 1} 的參數`}>
              <Settings2 />
            </Button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-80 space-y-3">
            <div className="text-sm font-medium">{label}</div>
            {op.description ? <p className="text-xs text-muted-foreground">{op.description}</p> : null}
            {op.params.map((p) => (
              <ParamField
                key={p.name}
                param={p}
                value={step.params?.[p.name]}
                onChange={(v) => onParams({ [p.name]: v })}
              />
            ))}
            {warnings.length ? (
              <ul className="list-disc pl-4 text-xs text-warning">
                {warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            ) : null}
          </PopoverContent>
        </Popover>
      ) : null}
      <Button variant="ghost" size="icon-sm" aria-label="上移" disabled={first} onClick={() => onMove(-1)}>
        <ArrowUp />
      </Button>
      <Button variant="ghost" size="icon-sm" aria-label="下移" disabled={last} onClick={() => onMove(1)}>
        <ArrowDown />
      </Button>
      <Button variant="ghost" size="icon-sm" aria-label="移除步驟" onClick={onRemove}>
        <X />
      </Button>
    </span>
  );
}

function ParamField({
  param: p,
  value,
  onChange,
}: {
  param: PreprocessParam;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const id = `wb-${p.name}`;
  const v = value ?? p.default ?? "";
  if (p.type === "bool")
    return (
      <label className="flex items-center gap-2 text-sm">
        <Switch checked={Boolean(v)} onCheckedChange={(c) => onChange(c)} />
        {p.label}
      </label>
    );
  if (p.type === "choice")
    return (
      <div className="grid gap-1.5">
        <Label htmlFor={id}>{p.label}</Label>
        <Select value={String(v)} onValueChange={(x) => onChange((p.choices ?? []).find((c) => String(c) === x) ?? x)}>
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
        {p.help ? <p className="text-[11px] text-muted-foreground">{p.help}</p> : null}
      </div>
    );
  const isList = p.type === "columns" || p.type === "list";
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{p.label}</Label>
      <Input
        id={id}
        className="h-8 font-mono text-xs"
        type={p.type === "int" || p.type === "float" ? "number" : "text"}
        step={p.type === "float" ? "any" : undefined}
        min={p.min}
        max={p.max}
        placeholder={isList ? "a,b,c（留空 = 自動）" : undefined}
        value={Array.isArray(v) ? v.join(",") : String(v)}
        onChange={(e) => {
          const raw = e.target.value;
          if (p.type === "int") onChange(raw === "" ? "" : Number.parseInt(raw, 10));
          else if (p.type === "float") onChange(raw === "" ? "" : Number(raw));
          else if (isList)
            onChange(
              raw
                .split(",")
                .map((x) => x.trim())
                .filter(Boolean),
            );
          else onChange(raw);
        }}
      />
      {p.help ? <p className="text-[11px] text-muted-foreground">{p.help}</p> : null}
    </div>
  );
}
