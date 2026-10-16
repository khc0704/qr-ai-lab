"use client";

// Standalone preprocessing: data type → upload → steps (real-time preview on a sample) → a job for the whole file.
import { LoaderCircle, Play, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { Dropzone } from "@/components/features/dropzone";
import { PreprocessEditor } from "@/components/features/preprocess-editor";
import { Stepper } from "@/components/features/stepper";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { dataTypeLabel } from "@/i18n/zh-TW";
import { deleteToolUploadAction, previewToolAction, processToolAction } from "@/lib/actions";
import { toToolUpload } from "@/lib/api/mappers";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DataType, PreprocessOp, PreprocessStep, ToolUpload, Upload } from "@/types/domain";

export const TOOL_TYPES: { value: DataType; hint: string; accept: string; files: string }[] = [
  {
    value: "TABULAR",
    hint: "表格資料：csv / parquet / jsonl",
    accept: ".csv,.parquet,.jsonl",
    files: "csv / parquet / jsonl",
  },
  {
    value: "IMAGE",
    hint: "影像：zip（資料夾結構保留）或單張圖片",
    accept: ".zip,.png,.jpg,.jpeg,.bmp,.tif,.tiff,.webp",
    files: "zip 或單張影像",
  },
  {
    value: "SEQUENCE",
    hint: "時間序列：長表 csv（series_id, t, 特徵…）或 npy",
    accept: ".csv,.npy",
    files: "csv / npy",
  },
  { value: "SPECTRUM", hint: "光譜：寬表 csv（每列一條光譜）或 npy", accept: ".csv,.npy", files: "csv / npy" },
  {
    value: "TEXT",
    hint: "文字：csv / jsonl，含文字欄位",
    accept: ".csv,.parquet,.jsonl",
    files: "csv / parquet / jsonl",
  },
];

const SPEC_FIELDS: Record<DataType, { key: string; label: string; hint?: string }[]> = {
  TABULAR: [
    { key: "target", label: "目標欄位（不會被處理）", hint: "例：yield_pct" },
    { key: "id_column", label: "ID 欄位（不會被處理）" },
  ],
  TEXT: [
    { key: "text_column", label: "文字欄位", hint: "預設 text" },
    { key: "label_column", label: "標籤欄位（不會被處理）" },
  ],
  SEQUENCE: [
    { key: "series_id", label: "序列 ID 欄位", hint: "預設 series_id" },
    { key: "time", label: "時間欄位", hint: "預設 t" },
    { key: "window", label: "視窗長度", hint: "預設 256" },
    { key: "label", label: "標籤欄位（排除）" },
  ],
  SPECTRUM: [
    { key: "label", label: "標籤欄位（排除）" },
    { key: "id_column", label: "ID 欄位（排除）" },
  ],
  IMAGE: [],
};

export function PreprocessTool({ ops }: { ops: PreprocessOp[] }) {
  const router = useRouter();
  const [dataType, setDataType] = useState<DataType>("TABULAR");
  const [upload, setUpload] = useState<ToolUpload | null>(null);
  const [steps, setSteps] = useState<PreprocessStep[]>([]);
  const [spec, setSpec] = useState<Record<string, string>>({});
  const [pending, startTransition] = useTransition();
  const [resetKey, setResetKey] = useState(0);
  const type = TOOL_TYPES.find((t) => t.value === dataType)!;
  const typeOps = ops.filter((o) => o.dataTypes.includes(dataType));
  const cleanSpec = Object.fromEntries(Object.entries(spec).filter(([, v]) => v !== ""));
  const step = upload ? (steps.length ? 2 : 1) : 0;

  const onUploaded = (u: Upload | null, raw?: Record<string, unknown>) => {
    // Dropzone parses the project Upload shape (numeric id); the tool's id is a hex string, so use the raw JSON
    setUpload(u && raw ? toToolUpload(raw) : null);
  };
  const changeType = (t: DataType) => {
    if (upload) return;
    setDataType(t);
    setSteps([]);
    setSpec({});
  };
  const submit = () =>
    startTransition(async () => {
      if (!upload) return;
      const r = await processToolAction(upload.id, steps, cleanSpec);
      if (!r.ok) toast.error(r.error);
      else {
        toast.success(`已建立前處理任務 #${r.data.id}，排入佇列`);
        setUpload(null);
        setSteps([]);
        setResetKey((k) => k + 1);
        router.refresh();
      }
    });
  const discard = () =>
    startTransition(async () => {
      if (upload) {
        const r = await deleteToolUploadAction(upload.id);
        if (!r.ok && r.code !== "TOOL_UPLOAD_NOT_FOUND") toast.error(r.error);
      }
      setUpload(null);
      setSteps([]);
      setResetKey((k) => k + 1);
    });

  return (
    <div className="space-y-6">
      <Stepper steps={["資料類型與檔案", "前處理步驟與預覽", "建立任務"]} current={step} />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle>1. 資料類型與檔案</CardTitle>
            <CardDescription>先選類型（決定可用的步驟與讀檔方式），再上傳。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="資料類型">
              {TOOL_TYPES.map((t) => (
                <button
                  key={t.value}
                  type="button"
                  role="radio"
                  aria-checked={t.value === dataType}
                  disabled={!!upload}
                  onClick={() => changeType(t.value)}
                  className={cn(
                    "rounded-lg border p-3 text-left transition-colors focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60",
                    t.value === dataType ? "border-primary/50 bg-primary/5" : "border-border hover:bg-accent/40",
                  )}
                  data-testid={`tool-type-${t.value}`}
                >
                  <div className="text-sm font-medium">{dataTypeLabel[t.value]}</div>
                  <div className="text-xs text-muted-foreground">{t.hint}</div>
                </button>
              ))}
            </div>
            {SPEC_FIELDS[dataType].length ? (
              <div className="grid gap-3 sm:grid-cols-2">
                {SPEC_FIELDS[dataType].map((f) => (
                  <div key={f.key} className="grid gap-1.5">
                    <Label htmlFor={`tool-spec-${f.key}`}>{f.label}</Label>
                    <Input
                      id={`tool-spec-${f.key}`}
                      value={spec[f.key] ?? ""}
                      placeholder={f.hint}
                      onChange={(e) => setSpec({ ...spec, [f.key]: e.target.value })}
                    />
                  </div>
                ))}
              </div>
            ) : null}
            <Dropzone
              key={`${dataType}-${resetKey}`}
              endpoint="/api/tools/upload"
              fields={{ data_type: dataType }}
              accept={type.accept}
              hint={`${type.files}；大小上限 2 GB`}
              onUploaded={onUploaded}
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>2. 前處理步驟與預覽</CardTitle>
            <CardDescription>
              {upload
                ? `對 ${upload.originalFilename}（${formatBytes(upload.sizeBytes)}）加入步驟，按「抽樣預覽」即時看前後差異（只取樣，不會處理整個檔案）。`
                : "上傳後才能預覽；步驟可以先挑。"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <PreprocessEditor
              ops={typeOps}
              steps={steps}
              onChange={setSteps}
              uploadId={upload?.id}
              spec={cleanSpec}
              onPreview={(s, sp) => previewToolAction(upload?.id ?? "", s, sp, 5)}
            />
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>3. 建立任務</CardTitle>
          <CardDescription>
            整個檔案的處理是一個任務：進入全域佇列、受個人工作區的 CPU / 記憶體配額限制、有即時 log。完成後到任務頁下載
            zip；下載一次就刪除。
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          <Button onClick={submit} disabled={!upload || pending} data-testid="tool-run">
            {pending ? <LoaderCircle className="animate-spin" /> : <Play />}
            建立前處理任務
          </Button>
          <Button
            variant="ghost"
            onClick={discard}
            disabled={!upload || pending}
            className="text-destructive hover:text-destructive"
          >
            <Trash2 />
            刪除暫存檔
          </Button>
          {upload && steps.length === 0 ? (
            <p className="basis-full text-xs text-muted-foreground">
              沒有加入任何步驟時，任務只會把檔案原樣打包（可用來確認格式）。
            </p>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
