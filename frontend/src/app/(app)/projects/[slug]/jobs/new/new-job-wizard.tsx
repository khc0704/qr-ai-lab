"use client";

import { BookOpen, ChevronDown, ChevronLeft, ChevronRight, LoaderCircle, Rocket } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { SourceKindChip } from "@/components/features/chips";
import { Dropzone } from "@/components/features/dropzone";
import { PreprocessDrawer, PreprocessSummary } from "@/components/features/preprocess-drawer";
import { PreprocessWorkbench } from "@/components/features/preprocess-workbench";
import {
  clampK,
  DEFAULT_RETRIEVE,
  isRetrieveOrder,
  RetrieveOptions,
  type RetrieveConfig,
} from "@/components/features/retrieve-options";
import { StatusBadge } from "@/components/features/status-badge";
import { Stepper } from "@/components/features/stepper";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  augmentOpLabel,
  dataTypeLabel,
  familyLabel,
  finetuneStepCopy,
  inferenceModeLabel,
  jobCopy,
  paramChoiceLabel,
  paramChoices,
  paramHint,
  taskTypeLabel,
} from "@/i18n/zh-TW";
import { createJobAction, previewPreprocessAction } from "@/lib/actions";
import { formatMb } from "@/lib/format";
import { cn } from "@/lib/utils";
import type {
  Catalog,
  CatalogFamily,
  DataFormat,
  DataSourceKind,
  DataType,
  InferenceMode,
  Job,
  PreprocessOp,
  PreprocessStep,
  PreviewPayload,
  TaskType,
  Upload,
} from "@/types/domain";

interface ProjectInfo {
  slug: string;
  dataType: DataType;
  taskType: TaskType;
  gpuLimit: number;
  cpuLimit: number;
  memoryLimitMb: number;
  defaultTimeout: number;
}
interface SourceInfo {
  id: number;
  name: string;
  kind: DataSourceKind;
  format: DataFormat;
  ok?: boolean;
}
interface ModelInfo {
  id: number;
  name: string;
  version: number;
  family: string;
  isDefault: boolean;
  inferenceModes: string[];
  /** op ids the model replays at inference (trained with preprocessing) */
  preprocess?: string[];
}

type FieldKind = "string" | "number" | "boolean";
interface SpecField {
  key: string;
  label: string;
  placeholder: string;
  hint?: string;
  /** Only fields declared numeric are coerced; column names such as "2024" or "null" stay strings. */
  type?: FieldKind;
}

const specFields: Record<DataType, SpecField[]> = {
  TABULAR: [
    { key: "target", label: "目標欄位", placeholder: "例：yield_pct", hint: "訓練必填；異常偵測可留空" },
    { key: "categorical", label: "類別欄位（逗號分隔，可選）", placeholder: "line,shift" },
    { key: "id_column", label: "識別欄位（可選）", placeholder: "lot_id", hint: "不參與訓練，推論結果會帶回" },
  ],
  IMAGE: [{ key: "classes", label: "類別（自動偵測，可修改）", placeholder: "scratch,dent,particle" }],
  SEQUENCE: [
    { key: "window", label: "視窗長度", placeholder: "256", type: "number" },
    { key: "stride", label: "步長", placeholder: "128", type: "number" },
    { key: "series_id", label: "序列 id 欄位", placeholder: "series_id" },
    { key: "label", label: "標籤欄位（可選）", placeholder: "label" },
  ],
  TEXT: [
    { key: "text_column", label: "文字欄位", placeholder: "text" },
    { key: "label_column", label: "標籤欄位", placeholder: "label" },
  ],
  SPECTRUM: [{ key: "label", label: "標籤欄位（可選）", placeholder: "label", hint: "異常標籤或迴歸目標" }],
};

function familiesFor(catalog: Catalog, dataType: DataType, task: TaskType): string[] {
  return Object.entries(catalog.families)
    .filter(([, f]) => !f.deprecated && (f.supports[dataType] ?? []).includes(task))
    .map(([id]) => id);
}

function automlCandidates(catalog: Catalog, dataType: DataType, task: TaskType) {
  const entry = catalog.automl.find((a) => a.data_type === dataType && a.tasks.includes(task));
  return entry ? { candidates: entry.candidates, budget: entry.budget } : null;
}

/** Text input → typed value, but only for the kind the catalog / field table declares; "" means "use default". */
function coerceValue(v: string, kind: FieldKind, nullable = false): unknown {
  if (v === "") return undefined;
  if (nullable && v.trim().toLowerCase() === "null") return null;
  if (kind === "number") {
    const n = Number(v);
    return v.trim() !== "" && !Number.isNaN(n) ? n : v;
  }
  if (kind === "boolean") return v === "true" ? true : v === "false" ? false : v;
  return v;
}

const DEFAULT_SENTINEL = "__default__";
const AUGMENT_NONE = "none"; // the user unticked every op: sent as [] (an empty string would mean "use the default")

/** `augment` list / comma string → the ops; "" (untouched) falls back to the family default. */
function augmentOps(value: string | undefined, fallback: unknown): string[] {
  if (value === AUGMENT_NONE) return [];
  const raw = value
    ? value
    : Array.isArray(fallback)
      ? fallback.join(",")
      : typeof fallback === "string"
        ? fallback
        : "";
  return raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

/** One hyper-parameter input: a select for categorical / boolean params, a multi-select for `augment`, a text
 *  box otherwise. "" always means "use the catalog default". */
function ParamField({
  family,
  name,
  def,
  value,
  onChange,
}: {
  family: CatalogFamily | undefined;
  name: string;
  def: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const id = `p-${name}`;
  const space = family?.search_space?.[name];
  const choices = family?.augment_choices;
  if (name === "augment" && choices?.length) {
    const ops = augmentOps(value, family?.defaults?.augment);
    const set = (op: string, on: boolean) => {
      const next = choices.filter((c) => (c === op ? on : ops.includes(c)));
      onChange(next.length ? next.join(",") : AUGMENT_NONE);
    };
    return (
      <div className="flex min-w-0 flex-col gap-2">
        <Label htmlFor={id}>{name}</Label>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              id={id}
              type="button"
              variant="outline"
              className="h-9 w-full justify-between font-mono font-normal"
              data-testid="augment-picker"
            >
              <span className="truncate">{ops.length ? ops.join(", ") : "（不做增強）"}</span>
              <ChevronDown className="size-4 opacity-60" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-64">
            <DropdownMenuLabel>訓練時的隨機增強（各以 0.5 機率套用）</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {choices.map((op) => (
              <DropdownMenuCheckboxItem
                key={op}
                checked={ops.includes(op)}
                onCheckedChange={(on) => set(op, on === true)}
                onSelect={(e) => e.preventDefault()}
              >
                <span className="font-mono">{op}</span>
                <span className="ml-2 text-xs text-muted-foreground">{augmentOpLabel[op] ?? ""}</span>
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
        <p className="text-[11px] text-muted-foreground">方向有意義的影像不要加翻轉 / 旋轉。</p>
      </div>
    );
  }
  const { kind } = paramKind(family, name);
  const choiceLabel = (v: string) => paramChoiceLabel[name]?.[v];
  const hint = paramHint[name];
  // the wizard's choices = the UI list (may include "auto") ∪ the AutoML search space, in that order
  const listed = [
    ...(paramChoices[name] ?? []),
    ...(space?.type === "categorical" && space.choices?.length ? space.choices.map((c) => String(c)) : []),
  ].filter((v, i, all) => all.indexOf(v) === i);
  const options: { value: string; label: string }[] | null = listed.length
    ? listed.map((v) => ({ value: v, label: v }))
    : kind === "boolean"
      ? [
          { value: "true", label: "true" },
          { value: "false", label: "false" },
        ]
      : null;
  if (options) {
    return (
      <div className="flex min-w-0 flex-col gap-2">
        <Label htmlFor={id}>{name}</Label>
        <Select value={value || DEFAULT_SENTINEL} onValueChange={(v) => onChange(v === DEFAULT_SENTINEL ? "" : v)}>
          <SelectTrigger id={id} className="w-full font-mono" data-testid={`param-${name}`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={DEFAULT_SENTINEL}>
              <span className="font-mono">{def}</span>
              <span className="ml-2 truncate text-xs text-muted-foreground">
                預設{choiceLabel(def) ? `・${choiceLabel(def)}` : ""}
              </span>
            </SelectItem>
            {options
              .filter((o) => o.value !== def)
              .map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  <span className="font-mono">{o.label}</span>
                  {choiceLabel(o.value) ? (
                    <span className="ml-2 truncate text-xs text-muted-foreground">{choiceLabel(o.value)}</span>
                  ) : null}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
        {hint ? <p className="text-[11px] text-muted-foreground">{hint}</p> : null}
      </div>
    );
  }
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <Label htmlFor={id}>{name}</Label>
      <Input
        id={id}
        className="font-mono"
        inputMode={kind === "number" ? "decimal" : undefined}
        placeholder={def}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      {hint ? <p className="text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

/** Hyper-parameters that only matter together with another setting are hidden until that setting is chosen:
 *  `k` with `head = knn`; for the DINO family the fine-tune knobs only when a fine-tune was chosen (on its own
 *  step), `backbone_lr` only for a full fine-tune, the PatchCore knobs only while `patchcore` is not off. */
function paramVisible(family: string, key: string, params: Record<string, string>, fam?: CatalogFamily): boolean {
  const effective = (name: string) => params[name] || String(fam?.defaults?.[name] ?? "");
  if (key === "k" && fam?.defaults?.head !== undefined) return effective("head") === "knn";
  if (family === DINO_FAMILY) {
    if (key === "finetune") return false; // chosen on the 骨幹微調 step
    const ft = effective("finetune");
    if (FINETUNE_PARAMS.has(key)) return ft !== "none";
    if (key === "backbone_lr") return ft === "full";
    if (PATCHCORE_PARAMS.has(key)) return effective("patchcore") !== "off";
  }
  return true;
}

const DINO_FAMILY = "vision.dino";
const FINETUNE_PARAMS = new Set(["epochs", "batch", "lr", "rank", "lora_alpha", "augment"]);
const PATCHCORE_PARAMS = new Set(["normal_class", "neighborhood", "score_agg", "coreset_ratio", "bank_augment"]);
type StepKey = "data" | "input" | "spec" | "mode" | "backbone" | "model" | "resources" | "confirm";
const STEP_LABELS: Record<StepKey, string> = {
  data: "資料",
  input: "輸入",
  spec: "欄位與前處理",
  mode: "模式",
  backbone: "骨幹微調",
  model: "模型與參數",
  resources: "資源",
  confirm: "確認",
};
const NORMAL_FOLDERS = new Set(["good", "normal", "ok", "pass"]); // what the trainer treats as "no defect"

/** What type a hyper-parameter has: the search space's declared type first, then the default value's type. */
function paramKind(family: CatalogFamily | undefined, key: string): { kind: FieldKind; nullable: boolean } {
  const space = family?.search_space?.[key];
  if (space?.type === "int" || space?.type === "float") return { kind: "number", nullable: false };
  if (space?.type === "categorical" && space.choices?.length) {
    const kinds = new Set(space.choices.map((c) => typeof c));
    if (kinds.size === 1 && kinds.has("number")) return { kind: "number", nullable: false };
    if (kinds.size === 1 && kinds.has("boolean")) return { kind: "boolean", nullable: false };
    return { kind: "string", nullable: false };
  }
  const def = family?.defaults?.[key];
  if (def === null) return { kind: "number", nullable: true }; // e.g. max_depth: null → unlimited or an int
  if (typeof def === "number") return { kind: "number", nullable: false };
  if (typeof def === "boolean") return { kind: "boolean", nullable: false };
  return { kind: "string", nullable: false };
}

export function NewJobWizard({
  kind,
  project,
  sources,
  models,
  catalog,
  ops,
  cloneFrom,
}: {
  kind: "train" | "inference";
  project: ProjectInfo;
  sources: SourceInfo[];
  models: ModelInfo[];
  catalog: Catalog;
  ops: PreprocessOp[];
  cloneFrom?: Job;
}) {
  const router = useRouter();
  const isTrain = kind === "train";
  const compatible = familiesFor(catalog, project.dataType, project.taskType);
  const auto = automlCandidates(catalog, project.dataType, project.taskType);
  const cloneSpec = (cloneFrom?.input.spec ?? {}) as Record<string, unknown>;
  const cloneSearch = cloneFrom?.config?.search as
    { candidates?: string[]; max_trials?: number; time_budget_minutes?: number } | undefined;

  const [step, setStep] = useState(0);
  const [name, setName] = useState(cloneFrom ? `${cloneFrom.name}-copy` : "");
  const [inputKind, setInputKind] = useState<"upload" | "data_source" | "inline">(
    cloneFrom?.input.kind === "data_source" ? "data_source" : isTrain ? "upload" : "inline",
  );
  const [sourceId, setSourceId] = useState<number | null>(cloneFrom?.dataSourceId ?? sources[0]?.id ?? null);
  const [upload, setUploadState] = useState<Upload | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [lastPreview, setLastPreview] = useState<PreviewPayload | null>(null);
  const setUpload = (u: Upload | null) => {
    setUploadState(u);
    setLastPreview(null);
    // The editor is not opened automatically here: the upload happens on step ①, while the target / id columns the
    // editor protects are entered on step ②, where 開啟編輯器 sits next to those fields.
  };
  const [inlineText, setInlineText] = useState(
    cloneFrom?.input.rows ? JSON.stringify(cloneFrom.input.rows, null, 1) : "",
  );
  const [spec, setSpec] = useState<Record<string, string>>(
    Object.fromEntries(
      Object.entries(cloneSpec)
        .filter(([k, v]) => k !== "preprocess" && (typeof v === "string" || typeof v === "number"))
        .map(([k, v]) => [k, String(v)]),
    ),
  );
  const [preprocess, setPreprocess] = useState<PreprocessStep[]>(
    (cloneSpec.preprocess as PreprocessStep[] | undefined) ?? [],
  );
  const [mode, setMode] = useState<"auto" | "manual">(cloneFrom?.mode ?? (auto ? "auto" : "manual"));
  // DINO image classification gets its own "fine-tune the backbone?" step before the model / parameter step
  const hasBackboneStep = isTrain && mode === "manual" && compatible.includes(DINO_FAMILY);
  const stepKeys: StepKey[] = isTrain
    ? ["data", "spec", "mode", ...(hasBackboneStep ? (["backbone"] as StepKey[]) : []), "model", "resources", "confirm"]
    : ["model", "input", "resources", "confirm"];
  const steps = stepKeys.map((k) => STEP_LABELS[k]);
  const [family, setFamily] = useState<string>(cloneFrom?.modelFamily ?? compatible[0] ?? "");
  const [candidates, setCandidates] = useState<string[]>(cloneSearch?.candidates ?? auto?.candidates ?? compatible);
  const [budget, setBudget] = useState({
    trials: cloneSearch?.max_trials ?? auto?.budget.max_trials ?? 10,
    minutes: cloneSearch?.time_budget_minutes ?? auto?.budget.time_budget_minutes ?? 60,
  });
  const [params, setParams] = useState<Record<string, string>>(
    Object.fromEntries(
      Object.entries(cloneFrom?.config ?? {})
        .filter(([k]) => k !== "search" && k !== "mode")
        .map(([k, v]) => [k, String(v)]),
    ),
  );
  const [modelId, setModelId] = useState<number | null>(
    cloneFrom?.artifactId ?? models.find((m) => m.isDefault)?.id ?? models[0]?.id ?? null,
  );
  const selectedModel = models.find((m) => m.id === modelId);
  // a model trained with preprocessing replays its own fitted pipeline: the wizard never sends steps for it
  const modelSteps = isTrain ? [] : (selectedModel?.preprocess ?? []);
  const inferenceModes = (
    selectedModel?.inferenceModes.length ? selectedModel.inferenceModes : ["predict"]
  ) as InferenceMode[];
  const [inferMode, setInferMode] = useState<string>((cloneFrom?.config?.mode as string | undefined) ?? "");
  const effectiveMode =
    inferMode && inferenceModes.includes(inferMode as InferenceMode) ? inferMode : inferenceModes[0];
  const [retrieve, setRetrieve] = useState<RetrieveConfig>(() => ({
    order: isRetrieveOrder(cloneFrom?.config?.order) ? cloneFrom.config.order : DEFAULT_RETRIEVE.order,
    k: typeof cloneFrom?.config?.k === "number" ? clampK(cloneFrom.config.k) : DEFAULT_RETRIEVE.k,
  }));
  const [pending, startTransition] = useTransition();

  const gpuOf = (f: string) => catalog.families[f]?.resources.gpu === "required";
  const weightsMissing = (f: string) => catalog.families[f]?.weights_ready === false;
  const needsGpu = isTrain
    ? mode === "auto"
      ? candidates.some(gpuOf)
      : gpuOf(family)
    : gpuOf(selectedModel?.family ?? "");
  const [res, setRes] = useState({
    gpu: cloneFrom?.requestedGpu ?? Math.min(needsGpu ? 1 : 0, project.gpuLimit),
    cpu: cloneFrom?.requestedCpu ?? Math.min(2, project.cpuLimit),
    memoryMb: cloneFrom?.requestedMemoryMb ?? Math.min(needsGpu ? 8192 : 4096, project.memoryLimitMb),
    // VRAM-shared placement is the norm: a declared amount lets the scheduler pack jobs by measured free memory
    gpuMemoryMb: cloneFrom?.requestedGpuMemoryMb ?? 8192,
    timeout: cloneFrom?.timeoutMinutes ?? project.defaultTimeout,
  });
  const overQuota = res.gpu > project.gpuLimit || res.cpu > project.cpuLimit || res.memoryMb > project.memoryLimitMb;
  const stepKey = stepKeys[Math.min(step, stepKeys.length - 1)];
  const last = step === steps.length - 1;
  const geometricBlocked = project.taskType === "detection" || project.taskType === "segmentation";

  const next = () => setStep((s) => Math.min(steps.length - 1, s + 1));
  const back = () => setStep((s) => Math.max(0, s - 1));

  const submit = () =>
    startTransition(async () => {
      const specOut: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(spec)) {
        const kind = specFields[project.dataType].find((f) => f.key === k)?.type ?? "string";
        const parsed = coerceValue(v, kind);
        if (parsed !== undefined) specOut[k] = parsed;
      }
      if (preprocess.length && modelSteps.length === 0) specOut.preprocess = preprocess;
      let rows: unknown[] | undefined;
      if (inputKind === "inline") {
        try {
          rows = JSON.parse(inlineText || "[]") as unknown[];
          if (!Array.isArray(rows) || rows.length === 0) throw new Error("rows");
        } catch {
          toast.error('直接輸入必須是 JSON 陣列，例如 [{"x1": 1.2}]');
          return;
        }
      }
      const config: Record<string, unknown> = {};
      if (isTrain && mode === "manual") {
        const fam = catalog.families[family];
        for (const [k, v] of Object.entries(params)) {
          if (k === "augment" && fam?.augment_choices?.length) {
            if (v) config.augment = augmentOps(v, fam.defaults?.augment);
            continue;
          }
          const { kind, nullable } = paramKind(fam, k);
          const parsed = coerceValue(v, kind, nullable);
          if (parsed !== undefined) config[k] = parsed;
        }
      }
      if (isTrain && mode === "auto") {
        config.search = { candidates, max_trials: budget.trials, time_budget_minutes: budget.minutes };
      }
      if (!isTrain && effectiveMode) config.mode = effectiveMode;
      if (!isTrain && effectiveMode === "retrieve") {
        config.order = retrieve.order;
        config.k = retrieve.k;
      }
      const body = {
        kind,
        name: name || (isTrain ? (mode === "auto" ? "automl-run" : `${family.split(".")[1]}-run`) : "batch-infer"),
        input: {
          kind: inputKind,
          upload_id: inputKind === "upload" ? upload?.id : undefined,
          data_source_id: inputKind === "data_source" ? sourceId : undefined,
          rows,
          spec: specOut,
        },
        task_type: project.taskType,
        mode: isTrain ? mode : undefined,
        model_family: isTrain && mode === "manual" ? family : undefined,
        config: Object.keys(config).length ? config : undefined,
        artifact_id: isTrain ? undefined : modelId,
        requested_gpu: res.gpu,
        requested_cpu: res.cpu,
        requested_memory_mb: res.memoryMb,
        requested_gpu_memory_mb: res.gpu > 0 && res.gpuMemoryMb > 0 ? res.gpuMemoryMb : null,
        timeout_minutes: res.timeout,
      };
      const r = await createJobAction(project.slug, body);
      if (!r.ok) {
        toast.error(r.error);
        return;
      }
      toast.success(`任務 #${r.data.id} 已建立，進入佇列`);
      router.push(`/projects/${project.slug}/jobs/${r.data.id}`);
    });

  const canProceed = () => {
    const dataOk =
      inputKind === "upload"
        ? Boolean(upload)
        : inputKind === "data_source"
          ? Boolean(sourceId)
          : inlineText.trim().length > 0;
    if (isTrain) {
      if (stepKey === "data") return dataOk;
      if (stepKey === "model") return mode === "auto" ? candidates.length > 0 : Boolean(family);
    } else {
      if (stepKey === "model") return Boolean(modelId);
      if (stepKey === "input") return dataOk;
    }
    return true;
  };

  const dataStep = (
    <Card>
      <CardHeader>
        <CardTitle>{isTrain ? "資料" : "輸入"}</CardTitle>
        <CardDescription>{jobCopy.wizardInputNotice}</CardDescription>
      </CardHeader>
      <CardContent>
        <Tabs value={inputKind} onValueChange={(v) => setInputKind(v as typeof inputKind)}>
          <TabsList className="w-full">
            {!isTrain ? (
              <TabsTrigger value="inline" className="flex-1">
                直接輸入
              </TabsTrigger>
            ) : null}
            <TabsTrigger value="upload" className="flex-1">
              一次性上傳
            </TabsTrigger>
            <TabsTrigger value="data_source" className="flex-1">
              資料來源
            </TabsTrigger>
          </TabsList>
          {!isTrain ? (
            <TabsContent value="inline" className="space-y-2 pt-4">
              <Textarea
                rows={8}
                className="font-mono text-xs"
                placeholder='[{"x1": 1.2, "x2": 0.3, "line": "A"}, …]  光譜 / 序列：[{"id": "s1", "values": [0.1, 0.2, …]}]'
                value={inlineText}
                onChange={(e) => setInlineText(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">適合少量即時推論；大量資料請用上傳或資料來源。</p>
            </TabsContent>
          ) : null}
          <TabsContent value="upload" className="pt-4">
            <Dropzone slug={project.slug} onUploaded={setUpload} />
          </TabsContent>
          <TabsContent value="data_source" className="grid gap-2 pt-4">
            {sources.length === 0 ? (
              <p className="text-sm text-muted-foreground">這個專案還沒有資料來源，先到「資料來源」新增。</p>
            ) : null}
            {sources.map((s) => (
              <label
                key={s.id}
                className={cn(
                  "flex cursor-pointer items-center gap-3 rounded-lg border p-3 transition-colors",
                  sourceId === s.id ? "border-primary/50 bg-primary/5" : "border-border hover:bg-accent/40",
                )}
              >
                <input
                  type="radio"
                  name="source"
                  className="accent-current"
                  checked={sourceId === s.id}
                  onChange={() => setSourceId(s.id)}
                />
                <span className="font-medium">{s.name}</span>
                <SourceKindChip kind={s.kind} />
                <span className="font-mono text-xs text-muted-foreground">{s.format}</span>
                <span className="ml-auto">
                  <StatusBadge status={s.ok == null ? "pending" : s.ok ? "ok" : "error"} />
                </span>
              </label>
            ))}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );

  const specStep = (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div className="space-y-1">
            <CardTitle>欄位設定</CardTitle>
            <CardDescription>
              {project.dataType} · {dataTypeLabel[project.dataType]} / {taskTypeLabel[project.taskType]}
              {upload?.detectedSpec ? (
                <span className="ml-2 font-mono text-xs">
                  偵測到 {String((upload.detectedSpec as { row_count?: number }).row_count ?? "?")} 列
                  {Array.isArray((upload.detectedSpec as { columns?: string[] }).columns)
                    ? `，欄位：${((upload.detectedSpec as { columns: string[] }).columns ?? []).slice(0, 12).join(", ")}`
                    : ""}
                </span>
              ) : null}
            </CardDescription>
          </div>
          <Sheet>
            <SheetTrigger asChild>
              <Button type="button" variant="outline" size="sm">
                <BookOpen />
                SOP
              </Button>
            </SheetTrigger>
            <SheetContent className="w-full sm:max-w-md">
              <SheetHeader>
                <SheetTitle>{dataTypeLabel[project.dataType]}資料的模型選擇</SheetTitle>
                <SheetDescription>來自模型目錄（GET /catalog）。</SheetDescription>
              </SheetHeader>
              <div className="space-y-3 overflow-auto px-4 pb-4 text-sm">
                {compatible.map((f) => (
                  <div key={f} className="rounded-lg border border-border p-3">
                    <div className="flex items-center justify-between">
                      <span className="font-medium">{familyLabel(f)}</span>
                      <span className="font-mono text-[11px] text-subtle-foreground">{f}</span>
                    </div>
                    <p className="mt-1 text-muted-foreground">
                      {catalog.families[f]?.sop}
                      {gpuOf(f) ? "（需要 GPU）" : "（CPU 即可）"}
                    </p>
                    <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                      推論：{catalog.families[f]?.inference_modes.map((m) => inferenceModeLabel[m] ?? m).join(" / ")}
                    </p>
                  </div>
                ))}
                <p className="text-muted-foreground">第一次建議選「自動模式」，跑完看 leaderboard 再手動微調。</p>
              </div>
            </SheetContent>
          </Sheet>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          {specFields[project.dataType].map((f) => (
            <div key={f.key} className="grid gap-2">
              <Label htmlFor={`spec-${f.key}`}>{f.label}</Label>
              <Input
                id={`spec-${f.key}`}
                className="font-mono"
                placeholder={f.placeholder}
                value={spec[f.key] ?? ""}
                onChange={(e) => setSpec({ ...spec, [f.key]: e.target.value })}
              />
              {f.hint ? <p className="text-xs text-muted-foreground">{f.hint}</p> : null}
            </div>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>資料前處理（可選）</CardTitle>
          <CardDescription>加入步驟後按「抽樣預覽」看處理前後的差異；步驟會隨任務送出。</CardDescription>
        </CardHeader>
        <CardContent>
          <PreprocessSummary
            ops={ops}
            steps={preprocess}
            preview={lastPreview}
            onOpen={() => setEditorOpen(true)}
            hint={
              inputKind === "upload"
                ? "填好欄位後按「開啟編輯器」加入步驟並預覽；也可以不加任何步驟。"
                : "資料來源會在任務內處理：步驟可以先挑，但沒有檔案就無法預覽。"
            }
          />
          <PreprocessDrawer open={editorOpen} onOpenChange={setEditorOpen}>
            <PreprocessWorkbench
              ops={ops}
              steps={preprocess}
              onChange={setPreprocess}
              dataType={project.dataType}
              spec={Object.fromEntries(Object.entries(spec).filter(([, v]) => v !== ""))}
              uploadId={inputKind === "upload" ? upload?.id : undefined}
              onPreview={(s, sp, n, o) => previewPreprocessAction(project.slug, Number(upload?.id ?? 0), s, sp, n, o)}
              onPreviewLoaded={setLastPreview}
              disabledReason={geometricBlocked ? "偵測 / 分割任務不能用會改變座標的步驟" : undefined}
            />
          </PreprocessDrawer>
        </CardContent>
      </Card>
    </div>
  );

  const modeStep = (
    <Card>
      <CardHeader>
        <CardTitle>模式</CardTitle>
        <CardDescription>自動模式會依資料類型挑多個候選模型並搜尋超參數；手動模式自己指定。</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2">
        {[
          {
            v: "auto" as const,
            t: "自動（AutoML）",
            d: "推薦。候選模型 + Optuna 搜尋，結束後給 leaderboard 與最佳模型。",
            disabled: !auto,
          },
          {
            v: "manual" as const,
            t: "手動",
            d: "指定一個模型家族與參數。適合已經知道要什麼的時候。",
            disabled: compatible.length === 0,
          },
        ].map((o) => (
          <button
            key={o.v}
            type="button"
            disabled={o.disabled}
            onClick={() => setMode(o.v)}
            className={cn(
              "rounded-xl border p-4 text-left transition-colors focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none disabled:opacity-50",
              mode === o.v ? "border-primary/50 bg-primary/5 shadow-glow-sm" : "border-border hover:bg-accent/40",
            )}
          >
            <div className="font-medium">{o.t}</div>
            <div className="mt-1 text-sm text-muted-foreground">{o.d}</div>
          </button>
        ))}
      </CardContent>
    </Card>
  );

  const finetune = params.finetune || String(catalog.families[DINO_FAMILY]?.defaults?.finetune ?? "none");
  const backboneStep = (
    <Card>
      <CardHeader>
        <CardTitle>{finetuneStepCopy.title}</CardTitle>
        <CardDescription>{finetuneStepCopy.description}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-3" role="radiogroup" aria-label={finetuneStepCopy.title}>
        {finetuneStepCopy.options.map((o) => (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={finetune === o.value}
            data-testid={`finetune-${o.value}`}
            onClick={() => {
              setParams({ ...params, finetune: o.value });
              if (!compatible.includes(family) || family !== DINO_FAMILY) setFamily(DINO_FAMILY);
            }}
            className={cn(
              "rounded-xl border p-4 text-left transition-colors focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none",
              finetune === o.value
                ? "border-primary/50 bg-primary/5 shadow-glow-sm"
                : "border-border hover:bg-accent/40",
            )}
          >
            <div className="font-medium">{o.title}</div>
            <div className="mt-1 text-sm text-muted-foreground">{o.text}</div>
          </button>
        ))}
      </CardContent>
    </Card>
  );

  const familyParams = (f: string) =>
    Object.entries(catalog.families[f]?.defaults ?? {})
      .map(([key, def]) => ({ key, def: def === null ? "" : String(def) }))
      .filter((p) => paramVisible(f, p.key, params, catalog.families[f]));
  const uploadClasses = Array.isArray((upload?.detectedSpec as { classes?: unknown })?.classes)
    ? ((upload?.detectedSpec as { classes: unknown[] }).classes.map(String) as string[])
    : [];
  const normalFolder =
    (params.normal_class || "").trim() || uploadClasses.find((c) => NORMAL_FOLDERS.has(c.toLowerCase())) || "";

  const modelStep =
    mode === "auto" ? (
      <Card>
        <CardHeader>
          <CardTitle>候選模型與預算</CardTitle>
          <CardDescription>
            依 {dataTypeLabel[project.dataType]} × {taskTypeLabel[project.taskType]} 自動挑選，可取消勾選。
            {res.gpu === 0 ? " 沒申請 GPU 時需要 GPU 的候選會被略過。" : ""}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            {(auto?.candidates ?? compatible).map((f) => {
              const on = candidates.includes(f);
              return (
                <button
                  key={f}
                  type="button"
                  onClick={() => setCandidates(on ? candidates.filter((c) => c !== f) : [...candidates, f])}
                  className={cn(
                    "rounded-md border px-3 py-1.5 text-sm transition-colors",
                    on
                      ? "border-primary/50 bg-primary/10 text-brand-ink"
                      : "border-border text-muted-foreground hover:bg-accent",
                  )}
                >
                  {familyLabel(f)}
                  {gpuOf(f) ? <span className="ml-1 font-mono text-[11px]">GPU</span> : null}
                  {weightsMissing(f) ? <span className="ml-1 text-[11px] text-warning">缺權重</span> : null}
                </button>
              );
            })}
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="trials">最多 trial 數</Label>
              <Input
                id="trials"
                type="number"
                min={1}
                className="text-right font-mono"
                value={budget.trials}
                onChange={(e) => setBudget({ ...budget, trials: Number(e.target.value) })}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="minutes">時間預算（分鐘）</Label>
              <Input
                id="minutes"
                type="number"
                min={1}
                className="text-right font-mono"
                value={budget.minutes}
                onChange={(e) => setBudget({ ...budget, minutes: Number(e.target.value) })}
              />
            </div>
          </div>
        </CardContent>
      </Card>
    ) : (
      <Card>
        <CardHeader>
          <CardTitle>模型與參數</CardTitle>
          <CardDescription>留空的參數用目錄預設值。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-2 sm:grid-cols-2">
            {compatible.map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFamily(f)}
                className={cn(
                  "rounded-lg border p-3 text-left transition-colors",
                  family === f ? "border-primary/50 bg-primary/5" : "border-border hover:bg-accent/40",
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium">{familyLabel(f)}</span>
                  <span className="flex items-center gap-2">
                    {weightsMissing(f) ? <span className="text-[11px] text-warning">缺權重，請管理員匯入</span> : null}
                    {gpuOf(f) ? <span className="font-mono text-[11px] text-muted-foreground">GPU</span> : null}
                  </span>
                </div>
                <div className="mt-1 text-xs text-muted-foreground">{catalog.families[f]?.sop}</div>
              </button>
            ))}
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            {familyParams(family).map((p) => (
              <ParamField
                key={p.key}
                family={catalog.families[family]}
                name={p.key}
                def={p.def}
                value={params[p.key] ?? ""}
                onChange={(v) => setParams({ ...params, [p.key]: v })}
              />
            ))}
          </div>
          {family === DINO_FAMILY && uploadClasses.length ? (
            <p className="text-xs text-muted-foreground" data-testid="normal-folder-hint">
              上傳的 zip 有 {uploadClasses.length} 個類別資料夾
              {normalFolder
                ? `，「${normalFolder}」會被當成正常類別（PatchCore 兩階段）`
                : "，沒有叫 good / normal / ok / pass 的資料夾；要走兩階段請在 normal_class 填正常資料夾的名字"}
              。
            </p>
          ) : null}
        </CardContent>
      </Card>
    );

  const pickModelStep = (
    <Card>
      <CardHeader>
        <CardTitle>模型與推論模式</CardTitle>
        <CardDescription>選擇要用來推論的已訓練模型，以及推論時要做什麼。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2">
          {models.length === 0 ? (
            <p className="text-sm text-muted-foreground">還沒有模型，先完成一個訓練任務。</p>
          ) : null}
          {models.map((m) => (
            <label
              key={m.id}
              className={cn(
                "flex cursor-pointer items-center gap-3 rounded-lg border p-3",
                modelId === m.id ? "border-primary/50 bg-primary/5" : "border-border hover:bg-accent/40",
              )}
            >
              <input
                type="radio"
                name="model"
                className="accent-current"
                checked={modelId === m.id}
                onChange={() => setModelId(m.id)}
              />
              <span className="font-medium">{m.name}</span>
              <span className="font-mono text-xs text-muted-foreground">
                v{m.version} · {m.family}
              </span>
              {m.isDefault ? (
                <span className="ml-auto rounded-sm bg-primary/10 px-1.5 text-[11px] text-brand-ink">預設</span>
              ) : null}
            </label>
          ))}
        </div>
        {selectedModel ? (
          <div className="grid gap-2">
            <Label htmlFor="infer-mode">推論模式</Label>
            <Select value={effectiveMode} onValueChange={setInferMode}>
              <SelectTrigger id="infer-mode" className="w-80">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {inferenceModes.map((m) => (
                  <SelectItem key={m} value={m}>
                    {inferenceModeLabel[m] ?? m}
                    <span className="ml-2 font-mono text-[11px] text-muted-foreground">{m}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {effectiveMode === "retrieve" ? (
              <RetrieveOptions
                value={retrieve}
                onChange={setRetrieve}
                idPrefix="job-retrieve"
                className="max-w-xl pt-1"
              />
            ) : null}
            {modelSteps.length ? (
              <p className="text-xs text-muted-foreground" data-testid="model-preprocess-note">
                這個模型訓練時用了前處理，推論會自動套用同一組步驟：
                <span className="ml-1 font-mono">{modelSteps.join(" → ")}</span>
                ；輸入原始資料即可，不用（也不能）再設定。
              </p>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );

  const resourceStep = (
    <Card>
      <CardHeader>
        <CardTitle>資源與逾時</CardTitle>
        <CardDescription>
          專案配額：
          <span className="font-mono text-foreground tabular-nums">
            {project.gpuLimit} GPU · {project.cpuLimit} CPU · {formatMb(project.memoryLimitMb)}
          </span>
          {needsGpu ? "；所選模型需要 GPU。" : "；所選模型 CPU 即可。"}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-4">
        <div className="grid gap-2">
          <Label htmlFor="r-gpu">GPU</Label>
          <Input
            id="r-gpu"
            type="number"
            min={0}
            className="text-right font-mono"
            value={res.gpu}
            onChange={(e) => setRes({ ...res, gpu: Number(e.target.value) })}
            aria-invalid={res.gpu > project.gpuLimit || (needsGpu && res.gpu === 0)}
          />
          {res.gpu > project.gpuLimit ? (
            <p className="text-xs text-destructive">超過配額 {project.gpuLimit}</p>
          ) : needsGpu && res.gpu === 0 ? (
            <p className="text-xs text-warning">此模型需要至少 1 GPU</p>
          ) : null}
        </div>
        <div className="grid gap-2">
          <Label htmlFor="r-cpu">CPU 核</Label>
          <Input
            id="r-cpu"
            type="number"
            min={1}
            className="text-right font-mono"
            value={res.cpu}
            onChange={(e) => setRes({ ...res, cpu: Number(e.target.value) })}
            aria-invalid={res.cpu > project.cpuLimit}
          />
          {res.cpu > project.cpuLimit ? <p className="text-xs text-destructive">超過配額 {project.cpuLimit}</p> : null}
        </div>
        <div className="grid gap-2">
          <Label htmlFor="r-mem">Memory (MB)</Label>
          <Input
            id="r-mem"
            type="number"
            step={1024}
            className="text-right font-mono"
            value={res.memoryMb}
            onChange={(e) => setRes({ ...res, memoryMb: Number(e.target.value) })}
            aria-invalid={res.memoryMb > project.memoryLimitMb}
          />
          <p
            className={cn(
              "text-xs",
              res.memoryMb > project.memoryLimitMb ? "text-destructive" : "text-muted-foreground",
            )}
          >
            {formatMb(res.memoryMb || 0)}
          </p>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="r-vram">每張 GPU 需要的顯存（MB，選填）</Label>
          <Input
            id="r-vram"
            type="number"
            step={1024}
            min={0}
            className="text-right font-mono"
            value={res.gpuMemoryMb}
            disabled={res.gpu === 0}
            onChange={(e) => setRes({ ...res, gpuMemoryMb: Number(e.target.value) })}
          />
          <p className="text-xs text-muted-foreground">
            {res.gpu === 0
              ? "不用 GPU。"
              : res.gpuMemoryMb > 0
                ? `只要 GPU 還有 ${formatMb(res.gpuMemoryMb)} 顯存就能排上去，可與其他任務共用同一張；程序內會以此為上限。`
                : "留 0 = 獨占整張 GPU（等到有整張空的才開始）。"}
          </p>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="r-to">逾時（分鐘）</Label>
          <Input
            id="r-to"
            type="number"
            min={1}
            className="text-right font-mono"
            value={res.timeout}
            onChange={(e) => setRes({ ...res, timeout: Number(e.target.value) })}
          />
        </div>
      </CardContent>
    </Card>
  );

  const confirmStep = (
    <Card>
      <CardHeader>
        <CardTitle>確認</CardTitle>
        <CardDescription>建立後任務進入全域佇列，依順序與資源池排程。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2">
          <Label htmlFor="job-name">任務名稱</Label>
          <Input
            id="job-name"
            placeholder={
              isTrain ? (mode === "auto" ? "automl-run-1" : `${family.split(".")[1]}-run-1`) : "batch-infer-1"
            }
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <dl className="grid gap-2 rounded-lg bg-muted/60 p-4 text-sm sm:grid-cols-[140px_1fr]">
          <dt className="text-label">輸入</dt>
          <dd className="font-mono text-xs">
            {inputKind === "data_source"
              ? (sources.find((s) => s.id === sourceId)?.name ?? "—")
              : inputKind === "upload"
                ? `${upload?.originalFilename ?? "—"}（任務結束即刪）`
                : "直接輸入"}
          </dd>
          {isTrain ? (
            <>
              <dt className="text-label">欄位</dt>
              <dd className="font-mono text-xs">
                {Object.entries(spec)
                  .filter(([, v]) => v)
                  .map(([k, v]) => `${k}=${v}`)
                  .join("  ") || "—"}
              </dd>
              <dt className="text-label">前處理</dt>
              <dd className="font-mono text-xs">{preprocess.map((s) => s.op).join(" → ") || "無"}</dd>
              <dt className="text-label">模式</dt>
              <dd>
                {mode === "auto"
                  ? `自動 · ${candidates.length} 個候選 · ${budget.trials} trials / ${budget.minutes} 分鐘`
                  : `手動 · ${familyLabel(family)}`}
              </dd>
            </>
          ) : (
            <>
              <dt className="text-label">模型</dt>
              <dd>
                {selectedModel ? `${selectedModel.name} v${selectedModel.version}` : "—"} ·{" "}
                {inferenceModeLabel[effectiveMode as InferenceMode] ?? effectiveMode}
              </dd>
              <dt className="text-label">前處理</dt>
              <dd className="font-mono text-xs">
                {modelSteps.length
                  ? `${modelSteps.join(" → ")}（模型內含，自動套用）`
                  : preprocess.map((s) => s.op).join(" → ") || "無"}
              </dd>
            </>
          )}
          <dt className="text-label">資源</dt>
          <dd className="font-mono text-xs tabular-nums">
            {res.gpu} GPU{res.gpu > 0 && res.gpuMemoryMb > 0 ? `（各 ${formatMb(res.gpuMemoryMb)} 顯存，可共用）` : ""}{" "}
            · {res.cpu} CPU · {formatMb(res.memoryMb)} · 逾時 {res.timeout} 分鐘
          </dd>
        </dl>
      </CardContent>
    </Card>
  );

  const content = {
    data: dataStep,
    input: dataStep,
    spec: specStep,
    mode: modeStep,
    backbone: backboneStep,
    model: isTrain ? modelStep : pickModelStep,
    resources: resourceStep,
    confirm: confirmStep,
  }[stepKey];

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6">
      <Stepper steps={steps} current={step} onSelect={setStep} />
      {content}
      <div className="flex items-center justify-between">
        <Button type="button" variant="outline" onClick={step === 0 ? () => router.back() : back}>
          <ChevronLeft />
          {step === 0 ? "取消" : "上一步"}
        </Button>
        {last ? (
          <Button type="button" onClick={submit} disabled={pending || overQuota || (needsGpu && res.gpu === 0)}>
            {pending ? <LoaderCircle className="animate-spin" /> : <Rocket />}
            建立任務
          </Button>
        ) : (
          <Button type="button" onClick={next} disabled={!canProceed()}>
            下一步
            <ChevronRight />
          </Button>
        )}
      </div>
    </div>
  );
}
