"use client";

// One-off inference: pick a model (the project default is preselected), the inference mode, drop a file or
// paste a few rows, press 推論. Resources, name and timeout are the server's business (jobs.ephemeral). The
// uploaded File stays in this browser so the result rows can open their samples.
import { Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { Dropzone } from "@/components/features/dropzone";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { inferenceModeLabel } from "@/i18n/zh-TW";
import { createJobAction } from "@/lib/actions";
import { aliasLocalFile, attachLocalFile, jobKey, uploadKey } from "@/lib/local-data";
import { cn } from "@/lib/utils";
import type { DataType, InferenceMode, TaskType, Upload } from "@/types/domain";

export interface InferModel {
  id: number;
  name: string;
  version: number;
  family: string;
  isDefault: boolean;
  inferenceModes: string[];
  gpuRequired: boolean;
  weightsReady: boolean;
  /** op ids the model replays at inference (trained with preprocessing) */
  preprocess: string[];
}

const ACCEPT: Record<DataType, string> = {
  TABULAR: ".csv,.parquet,.jsonl",
  IMAGE: ".zip,.png,.jpg,.jpeg,.bmp,.tif,.tiff,.webp",
  SEQUENCE: ".csv,.npy",
  SPECTRUM: ".csv,.npy",
  TEXT: ".csv,.parquet,.jsonl",
};

const INLINE_EXAMPLE: Record<DataType, string> = {
  TABULAR: '[{"x1": 1.2, "x2": 0.4}, {"x1": -0.3, "x2": 1.1}]',
  IMAGE: "",
  SEQUENCE: '[{"values": [0.1, 0.2, 0.15, 0.3]}]',
  SPECTRUM: '[{"values": [0.11, 0.12, 0.10, 0.09]}]',
  TEXT: '[{"text": "機台 A 溫度過高"}]',
};

export function InferPanel({
  slug,
  dataType,
  taskType,
  canRun,
  models,
}: {
  slug: string;
  dataType: DataType;
  taskType: TaskType;
  canRun: boolean;
  models: InferModel[];
}) {
  const router = useRouter();
  const [modelId, setModelId] = useState<number | null>(models.find((m) => m.isDefault)?.id ?? models[0]?.id ?? null);
  const model = models.find((m) => m.id === modelId);
  const modes = (model?.inferenceModes.length ? model.inferenceModes : ["predict"]) as InferenceMode[];
  const [mode, setMode] = useState<string>("");
  const effectiveMode = modes.includes(mode as InferenceMode) ? mode : modes[0];
  const inlineAllowed = dataType !== "IMAGE";
  const [inputKind, setInputKind] = useState<"upload" | "inline">("upload");
  const [upload, setUpload] = useState<Upload | null>(null);
  const [resetKey, setResetKey] = useState(0);
  const [rowsText, setRowsText] = useState("");
  const [pending, startTransition] = useTransition();
  const ready = Boolean(model) && (inputKind === "upload" ? Boolean(upload) : rowsText.trim().length > 0);

  const run = () =>
    startTransition(async () => {
      if (!model) return;
      let rows: unknown[] | undefined;
      if (inputKind === "inline") {
        try {
          rows = JSON.parse(rowsText || "[]") as unknown[];
          if (!Array.isArray(rows) || rows.length === 0) throw new Error("rows");
        } catch {
          toast.error(`直接輸入必須是 JSON 陣列，例如 ${INLINE_EXAMPLE[dataType]}`);
          return;
        }
      }
      const r = await createJobAction(slug, {
        kind: "inference",
        ephemeral: true,
        name: `推論 ${model.name} v${model.version}`,
        artifact_id: model.id,
        config: { mode: effectiveMode },
        input: {
          kind: inputKind,
          upload_id: inputKind === "upload" ? upload?.id : undefined,
          rows,
          spec: {},
        },
        task_type: taskType,
      });
      if (!r.ok) {
        toast.error(r.error);
        return;
      }
      if (inputKind === "upload" && upload) aliasLocalFile(uploadKey("project", upload.id), jobKey(r.data.id));
      toast.success(`推論 #${r.data.id} 已排入佇列`);
      setUpload(null);
      setRowsText("");
      setResetKey((k) => k + 1);
      router.push(`/projects/${slug}/infer?job=${r.data.id}`);
    });

  return (
    <Card data-testid="infer-panel">
      <CardHeader>
        <CardTitle>一次性推論</CardTitle>
        <CardDescription>
          選模型、選推論模式、給資料，按「推論」。結果只在這一頁看，不會變成專案產物，也不列入任務列表；資料與結果在保留時間過後自動清除。
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-4">
          <div className="grid gap-2">
            <span className="text-label">模型</span>
            {models.length === 0 ? (
              <p className="text-sm text-muted-foreground">還沒有模型，先完成一個訓練任務。</p>
            ) : null}
            {models.map((m) => (
              <label
                key={m.id}
                className={cn(
                  "flex cursor-pointer items-center gap-3 rounded-lg border p-3",
                  modelId === m.id ? "border-primary/50 bg-primary/5" : "border-border hover:bg-accent/40",
                  !m.weightsReady && "opacity-60",
                )}
              >
                <input
                  type="radio"
                  name="infer-model"
                  className="accent-current"
                  checked={modelId === m.id}
                  disabled={!m.weightsReady}
                  onChange={() => setModelId(m.id)}
                />
                <span className="font-medium">{m.name}</span>
                <span className="font-mono text-xs text-muted-foreground">
                  v{m.version} · {m.family}
                </span>
                {m.gpuRequired ? (
                  <span className="rounded-sm bg-muted px-1.5 text-[11px] text-muted-foreground">GPU</span>
                ) : null}
                {!m.weightsReady ? (
                  <span className="rounded-sm bg-warning/10 px-1.5 text-[11px] text-warning">缺預訓練權重</span>
                ) : null}
                {m.isDefault ? (
                  <span className="ml-auto rounded-sm bg-primary/10 px-1.5 text-[11px] text-brand-ink">預設</span>
                ) : null}
              </label>
            ))}
          </div>
          {model?.preprocess.length ? (
            <p className="text-xs text-muted-foreground" data-testid="model-preprocess-note">
              這個模型訓練時用了前處理，推論會自動套用同一組步驟：
              <span className="ml-1 font-mono">{model.preprocess.join(" → ")}</span>；給原始資料就好。
            </p>
          ) : null}
          {model ? (
            <div className="grid gap-2">
              <Label htmlFor="infer-mode">推論模式</Label>
              <Select value={effectiveMode} onValueChange={setMode}>
                <SelectTrigger id="infer-mode" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {modes.map((m) => (
                    <SelectItem key={m} value={m}>
                      {inferenceModeLabel[m] ?? m}
                      <span className="ml-2 font-mono text-[11px] text-muted-foreground">{m}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : null}
        </div>
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <span className="text-label">資料</span>
            {inlineAllowed ? (
              <div className="ml-auto flex rounded-md border border-border p-0.5" role="tablist" aria-label="輸入方式">
                {(["upload", "inline"] as const).map((k) => (
                  <button
                    key={k}
                    type="button"
                    role="tab"
                    aria-selected={inputKind === k}
                    onClick={() => setInputKind(k)}
                    className={cn(
                      "rounded-sm px-2 py-1 text-xs transition-colors",
                      inputKind === k
                        ? "bg-secondary font-medium text-foreground"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {k === "upload" ? "上傳檔案" : "直接輸入"}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          {inputKind === "upload" ? (
            <Dropzone
              key={resetKey}
              slug={slug}
              accept={ACCEPT[dataType]}
              hint="與訓練時相同格式；檔案只在推論期間存在，原始檔留在你的瀏覽器供查看樣本"
              onUploaded={(u, _raw, file) => {
                setUpload(u);
                if (u && file) attachLocalFile(uploadKey("project", u.id), file);
              }}
            />
          ) : (
            <div className="grid gap-2">
              <Label htmlFor="infer-rows">JSON 陣列，每個元素一筆</Label>
              <Textarea
                id="infer-rows"
                rows={8}
                className="font-mono text-xs"
                placeholder={INLINE_EXAMPLE[dataType]}
                value={rowsText}
                onChange={(e) => setRowsText(e.target.value)}
              />
            </div>
          )}
          <div className="flex items-center justify-end gap-3">
            {!canRun ? (
              <span className="text-xs text-muted-foreground">你在這個專案是檢視者，不能執行推論。</span>
            ) : null}
            <Button onClick={run} disabled={!canRun || !ready || pending} data-testid="infer-run">
              <Sparkles />
              推論
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
