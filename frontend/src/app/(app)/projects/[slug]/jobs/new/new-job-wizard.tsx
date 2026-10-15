"use client";

import { BookOpen, ChevronLeft, ChevronRight, Rocket } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Dropzone } from "@/components/features/dropzone";
import { SourceKindChip } from "@/components/features/chips";
import { StatusBadge } from "@/components/features/status-badge";
import { Stepper } from "@/components/features/stepper";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { dataTypeLabel, modelFamilyLabel, taskTypeLabel } from "@/i18n/zh-TW";
import { formatMb } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DataSourceKind, DataType, DataFormat, ModelFamily, TaskType } from "@/types/domain";

interface ProjectInfo {
  slug: string;
  dataType: DataType;
  taskType: TaskType;
  gpuLimit: number;
  cpuLimit: number;
  memoryLimitMb: number;
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
  family: ModelFamily;
  isDefault: boolean;
}

/** Mirrors docs/MODEL_CATALOG.md §4 — replaced by GET /catalog later. */
const catalog: Record<
  ModelFamily,
  {
    dataTypes: DataType[];
    tasks: TaskType[];
    gpu: boolean;
    sop: string;
    params: { key: string; label: string; def: string }[];
  }
> = {
  "tabular.linear": {
    dataTypes: ["TABULAR", "TEXT"],
    tasks: ["classification", "regression"],
    gpu: false,
    sop: "最簡單、可解釋、秒級訓練，當基準線。",
    params: [{ key: "C", label: "C / alpha", def: "1.0" }],
  },
  "tabular.svm": {
    dataTypes: ["TABULAR"],
    tasks: ["classification", "regression"],
    gpu: false,
    sop: "小資料、特徵多時好；> 50k 列會很慢。",
    params: [
      { key: "C", label: "C", def: "1.0" },
      { key: "kernel", label: "kernel", def: "rbf" },
    ],
  },
  "tabular.random_forest": {
    dataTypes: ["TABULAR"],
    tasks: ["classification", "regression"],
    gpu: false,
    sop: "穩健、不太需要調參、給特徵重要度。",
    params: [
      { key: "n_estimators", label: "樹的數量", def: "300" },
      { key: "max_depth", label: "最大深度", def: "" },
    ],
  },
  "tabular.xgboost": {
    dataTypes: ["TABULAR"],
    tasks: ["classification", "regression"],
    gpu: false,
    sop: "表格資料的預設首選，多數情況最準。",
    params: [
      { key: "learning_rate", label: "learning rate", def: "0.05" },
      { key: "max_depth", label: "max depth", def: "6" },
      { key: "n_estimators", label: "n estimators", def: "500" },
    ],
  },
  "vision.yolo": {
    dataTypes: ["IMAGE"],
    tasks: ["detection", "segmentation", "classification"],
    gpu: true,
    sop: "即時物件偵測 / 分割的標準做法。",
    params: [
      { key: "model", label: "model", def: "yolo11s" },
      { key: "imgsz", label: "imgsz", def: "640" },
      { key: "epochs", label: "epochs", def: "100" },
    ],
  },
  "vision.dino": {
    dataTypes: ["IMAGE"],
    tasks: ["classification", "anomaly_detection"],
    gpu: true,
    sop: "預訓練特徵 + 線性頭，少量標籤也能分得好。",
    params: [
      { key: "backbone", label: "backbone", def: "dinov2_vits14" },
      { key: "epochs", label: "epochs", def: "20" },
    ],
  },
  "sequence.patch_autoencoder": {
    dataTypes: ["SEQUENCE", "SPECTRUM"],
    tasks: ["anomaly_detection", "regression"],
    gpu: true,
    sop: "切 patch 做自編碼器，重建誤差大 = 異常。",
    params: [
      { key: "patch_size", label: "patch size", def: "16" },
      { key: "latent", label: "latent", def: "32" },
      { key: "epochs", label: "epochs", def: "50" },
    ],
  },
  "text.bert_classifier": {
    dataTypes: ["TEXT"],
    tasks: ["classification"],
    gpu: true,
    sop: "預訓練 BERT 接分類頭，語意理解。",
    params: [
      { key: "model", label: "model", def: "bert-base-chinese" },
      { key: "max_len", label: "max len", def: "256" },
      { key: "epochs", label: "epochs", def: "3" },
    ],
  },
};

const specFields: Record<DataType, { key: string; label: string; placeholder: string }[]> = {
  TABULAR: [
    { key: "target", label: "目標欄位", placeholder: "例：yield_pct" },
    { key: "categorical", label: "類別欄位（逗號分隔，可選）", placeholder: "line,shift" },
  ],
  IMAGE: [
    { key: "classes", label: "類別（自動偵測，可修改）", placeholder: "scratch,dent,particle" },
    { key: "imgsz", label: "影像尺寸", placeholder: "640" },
  ],
  SEQUENCE: [
    { key: "window", label: "視窗長度", placeholder: "1024" },
    { key: "stride", label: "步長", placeholder: "256" },
  ],
  TEXT: [
    { key: "text_column", label: "文字欄位", placeholder: "text" },
    { key: "label_column", label: "標籤欄位", placeholder: "label" },
  ],
  SPECTRUM: [
    { key: "patch_size", label: "patch 大小", placeholder: "16" },
    { key: "label", label: "標籤欄位（可選）", placeholder: "" },
  ],
};

export function NewJobWizard({
  kind,
  project,
  sources,
  models,
}: {
  kind: "train" | "inference";
  project: ProjectInfo;
  sources: SourceInfo[];
  models: ModelInfo[];
}) {
  const router = useRouter();
  const isTrain = kind === "train";
  const steps = isTrain ? ["資料", "欄位設定", "模式", "模型與參數", "資源", "確認"] : ["模型", "輸入", "資源", "確認"];
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [inputKind, setInputKind] = useState<"upload" | "data_source" | "inline">(isTrain ? "upload" : "inline");
  const [sourceId, setSourceId] = useState<number | null>(sources[0]?.id ?? null);
  const [spec, setSpec] = useState<Record<string, string>>({});
  const [auto, setAuto] = useState(true);
  const compatible = (Object.keys(catalog) as ModelFamily[]).filter(
    (f) => catalog[f].dataTypes.includes(project.dataType) && catalog[f].tasks.includes(project.taskType),
  );
  const [family, setFamily] = useState<ModelFamily>(compatible[0]);
  const [candidates, setCandidates] = useState<ModelFamily[]>(compatible);
  const [budget, setBudget] = useState({ trials: 20, minutes: 60 });
  const [params, setParams] = useState<Record<string, string>>({});
  const [modelId, setModelId] = useState<number | null>(models.find((m) => m.isDefault)?.id ?? models[0]?.id ?? null);
  const needsGpu = isTrain
    ? auto
      ? candidates.some((c) => catalog[c].gpu)
      : catalog[family].gpu
    : catalog[models.find((m) => m.id === modelId)?.family ?? "tabular.linear"].gpu;
  const [res, setRes] = useState({
    gpu: Math.min(1, project.gpuLimit),
    cpu: Math.min(4, project.cpuLimit),
    memoryMb: Math.min(16384, project.memoryLimitMb),
    timeout: 240,
  });
  const overQuota = res.gpu > project.gpuLimit || res.cpu > project.cpuLimit || res.memoryMb > project.memoryLimitMb;
  const last = step === steps.length - 1;

  const next = () => setStep((s) => Math.min(steps.length - 1, s + 1));
  const back = () => setStep((s) => Math.max(0, s - 1));
  const submit = () => {
    toast.success(`已建立${isTrain ? "訓練" : "推論"}任務，已加入佇列（接上 backend 後生效）`);
    router.push(`/projects/${project.slug}/jobs`);
  };

  const dataStep = (
    <Card>
      <CardHeader>
        <CardTitle>{isTrain ? "資料" : "輸入"}</CardTitle>
        <CardDescription>一次性上傳的檔案只存在於這個任務執行期間；資料來源則由任務容器直接抓取。</CardDescription>
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
            <TabsContent value="inline" className="pt-4">
              <Textarea rows={8} className="font-mono text-xs" placeholder='[{"col_a": 1.2, "col_b": "x"}, …]' />
            </TabsContent>
          ) : null}
          <TabsContent value="upload" className="pt-4">
            <Dropzone />
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
                  <StatusBadge status={s.ok ? "ok" : "error"} />
                </span>
              </label>
            ))}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );

  const specStep = (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div className="space-y-1">
          <CardTitle>欄位設定</CardTitle>
          <CardDescription>
            {project.dataType} · {dataTypeLabel[project.dataType]} / {taskTypeLabel[project.taskType]}
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
              <SheetDescription>對應 docs/MODEL_CATALOG.md，之後由 /catalog 提供。</SheetDescription>
            </SheetHeader>
            <div className="space-y-3 px-4 pb-4 text-sm">
              {compatible.map((f) => (
                <div key={f} className="rounded-lg border border-border p-3">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{modelFamilyLabel[f]}</span>
                    <span className="font-mono text-[11px] text-subtle-foreground">{f}</span>
                  </div>
                  <p className="mt-1 text-muted-foreground">
                    {catalog[f].sop}
                    {catalog[f].gpu ? "（需要 GPU）" : "（CPU 即可）"}
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
          </div>
        ))}
      </CardContent>
    </Card>
  );

  const modeStep = (
    <Card>
      <CardHeader>
        <CardTitle>模式</CardTitle>
        <CardDescription>自動模式會依資料類型挑多個候選模型並搜尋超參數；手動模式自己指定。</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2">
        {[
          { v: true, t: "自動（AutoML）", d: "推薦。候選模型 + Optuna 搜尋，結束後給 leaderboard 與最佳模型。" },
          { v: false, t: "手動", d: "指定一個模型家族與參數。適合已經知道要什麼的時候。" },
        ].map((o) => (
          <button
            key={String(o.v)}
            type="button"
            onClick={() => setAuto(o.v)}
            className={cn(
              "rounded-xl border p-4 text-left transition-colors focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none",
              auto === o.v ? "border-primary/50 bg-primary/5 shadow-glow-sm" : "border-border hover:bg-accent/40",
            )}
          >
            <div className="font-medium">{o.t}</div>
            <div className="mt-1 text-sm text-muted-foreground">{o.d}</div>
          </button>
        ))}
      </CardContent>
    </Card>
  );

  const modelStep = auto ? (
    <Card>
      <CardHeader>
        <CardTitle>候選模型與預算</CardTitle>
        <CardDescription>
          依 {dataTypeLabel[project.dataType]} × {taskTypeLabel[project.taskType]} 自動挑選，可取消勾選。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-2">
          {compatible.map((f) => {
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
                {modelFamilyLabel[f]}
                {catalog[f].gpu ? <span className="ml-1 font-mono text-[11px]">GPU</span> : null}
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
                <span className="font-medium">{modelFamilyLabel[f]}</span>
                {catalog[f].gpu ? <span className="font-mono text-[11px] text-muted-foreground">GPU</span> : null}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">{catalog[f].sop}</div>
            </button>
          ))}
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          {catalog[family].params.map((p) => (
            <div key={p.key} className="grid gap-2">
              <Label htmlFor={`p-${p.key}`}>{p.label}</Label>
              <Input
                id={`p-${p.key}`}
                className="font-mono"
                placeholder={p.def}
                value={params[p.key] ?? ""}
                onChange={(e) => setParams({ ...params, [p.key]: e.target.value })}
              />
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );

  const pickModelStep = (
    <Card>
      <CardHeader>
        <CardTitle>模型</CardTitle>
        <CardDescription>選擇要用來推論的已訓練模型。</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-2">
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
          <Label htmlFor="r-to">逾時（分鐘）</Label>
          <Input
            id="r-to"
            type="number"
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
            placeholder={isTrain ? (auto ? "automl-run-1" : `${family.split(".")[1]}-run-1`) : "batch-infer-1"}
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
                ? "一次性上傳（任務結束即刪）"
                : "直接輸入"}
          </dd>
          {isTrain ? (
            <>
              <dt className="text-label">模式</dt>
              <dd>
                {auto
                  ? `自動 · ${candidates.length} 個候選 · ${budget.trials} trials / ${budget.minutes} 分鐘`
                  : `手動 · ${modelFamilyLabel[family]}`}
              </dd>
            </>
          ) : (
            <>
              <dt className="text-label">模型</dt>
              <dd>{models.find((m) => m.id === modelId)?.name ?? "—"}</dd>
            </>
          )}
          <dt className="text-label">資源</dt>
          <dd className="font-mono text-xs tabular-nums">
            {res.gpu} GPU · {res.cpu} CPU · {formatMb(res.memoryMb)} · 逾時 {res.timeout} 分鐘
          </dd>
        </dl>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <Switch defaultChecked />
          完成或失敗時通知我
        </label>
      </CardContent>
    </Card>
  );

  const content = isTrain
    ? [dataStep, specStep, modeStep, modelStep, resourceStep, confirmStep][step]
    : [pickModelStep, dataStep, resourceStep, confirmStep][step];

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6">
      <Stepper steps={steps} current={step} />
      {content}
      <div className="flex items-center justify-between">
        <Button type="button" variant="outline" onClick={step === 0 ? () => router.back() : back}>
          <ChevronLeft />
          {step === 0 ? "取消" : "上一步"}
        </Button>
        {last ? (
          <Button
            type="button"
            onClick={submit}
            disabled={overQuota || (isTrain && inputKind === "data_source" && !sourceId)}
          >
            <Rocket />
            建立任務
          </Button>
        ) : (
          <Button type="button" onClick={next}>
            下一步
            <ChevronRight />
          </Button>
        )}
      </div>
    </div>
  );
}
