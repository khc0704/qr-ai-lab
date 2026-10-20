"use client";

// Data exploration: pick an analysis, upload, set the few parameters, start a job in the personal workspace.
import { ChartScatter, LoaderCircle, Play, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { Dropzone } from "@/components/features/dropzone";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { analysisKindLabel, dinoBackboneLabel } from "@/i18n/zh-TW";
import { analyzeToolAction, deleteToolUploadAction } from "@/lib/actions";
import { aliasLocalFile, attachLocalFile, jobKey, uploadKey } from "@/lib/local-data";
import { toToolUpload } from "@/lib/api/mappers";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { AnalysisKind, ToolUpload, Upload } from "@/types/domain";

const KINDS: { value: AnalysisKind; dataType: "TABULAR" | "IMAGE"; hint: string; accept: string; files: string }[] = [
  {
    value: "tabular_profile",
    dataType: "TABULAR",
    hint: "哪些欄位高度相關 / 共線、哪些對目標有解釋力、該補值還是該丟、該用哪種模型",
    accept: ".csv,.parquet,.jsonl",
    files: "csv / parquet / jsonl",
  },
  {
    value: "image_quality",
    dataType: "IMAGE",
    hint: "不同機台 / 條件的影像：哪些 IQA 指標最會飄、群組在 embedding 上是否可分、哪些影像偏離",
    accept: ".zip",
    files: "zip，子資料夾 = 機台 / 條件",
  },
];

export function AnalyzeTool() {
  const router = useRouter();
  const [kind, setKind] = useState<AnalysisKind>("tabular_profile");
  const [upload, setUpload] = useState<ToolUpload | null>(null);
  const [target, setTarget] = useState("");
  const [idColumn, setIdColumn] = useState("");
  const [dino, setDino] = useState(false);
  const [backbone, setBackbone] = useState<string>("dinov2-small");
  const [pending, startTransition] = useTransition();
  const [resetKey, setResetKey] = useState(0);
  const current = KINDS.find((k) => k.value === kind)!;
  const onUploaded = (u: Upload | null, raw?: Record<string, unknown>, file?: File) => {
    const tu = u && raw ? toToolUpload(raw) : null;
    setUpload(tu);
    // keep the browser's copy so the report can show the image behind a point (the server deletes the input)
    if (tu && file) attachLocalFile(uploadKey("tool", tu.id), file);
  };
  const submit = () =>
    startTransition(async () => {
      if (!upload) return;
      const params =
        kind === "tabular_profile"
          ? { ...(target ? { target } : {}), ...(idColumn ? { id_column: idColumn } : {}) }
          : dino
            ? { embedding: "dino", backbone }
            : { embedding: "metrics" };
      const r = await analyzeToolAction(upload.id, kind, params);
      if (!r.ok) toast.error(r.error);
      else {
        aliasLocalFile(uploadKey("tool", upload.id), jobKey(r.data.id));
        toast.success(`已建立分析任務 #${r.data.id}，排入佇列`);
        setUpload(null);
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
      setResetKey((k) => k + 1);
    });
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <Card>
        <CardHeader>
          <CardTitle>1. 分析類型與檔案</CardTitle>
          <CardDescription>先選分析（決定接受的檔案），再上傳。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-2" role="radiogroup" aria-label="分析類型">
            {KINDS.map((k) => (
              <button
                key={k.value}
                type="button"
                role="radio"
                aria-checked={k.value === kind}
                disabled={!!upload}
                onClick={() => setKind(k.value)}
                className={cn(
                  "rounded-lg border p-3 text-left transition-colors focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60",
                  k.value === kind ? "border-primary/50 bg-primary/5" : "border-border hover:bg-accent/40",
                )}
                data-testid={`analysis-${k.value}`}
              >
                <div className="flex items-center gap-2 text-sm font-medium">
                  <ChartScatter className="size-4 text-brand-ink" />
                  {analysisKindLabel[k.value]}
                  <span className="font-mono text-[11px] font-normal text-subtle-foreground">{k.dataType}</span>
                </div>
                <div className="text-xs text-muted-foreground">{k.hint}</div>
              </button>
            ))}
          </div>
          <Dropzone
            key={`${kind}-${resetKey}`}
            endpoint="/api/tools/upload"
            fields={{ data_type: current.dataType }}
            accept={current.accept}
            hint={`${current.files}；大小上限 2 GB`}
            onUploaded={onUploaded}
          />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>2. 參數與建立任務</CardTitle>
          <CardDescription>
            {upload ? `${upload.originalFilename}（${formatBytes(upload.sizeBytes)}）` : "上傳後填參數。"}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {kind === "tabular_profile" ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="grid gap-1.5">
                <Label htmlFor="an-target">目標欄位（選填）</Label>
                <Input
                  id="an-target"
                  value={target}
                  placeholder="例：yield_pct"
                  onChange={(e) => setTarget(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  填了才會算每個欄位對目標的解釋力與推薦；留空只做相關性 / 共線性。
                </p>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="an-id">ID 欄位（排除）</Label>
                <Input
                  id="an-id"
                  value={idColumn}
                  placeholder="例：lot_id"
                  onChange={(e) => setIdColumn(e.target.value)}
                />
              </div>
            </div>
          ) : (
            <div className="space-y-3 rounded-lg border border-border p-3">
              <div className="flex items-start justify-between gap-4">
                <div className="space-y-0.5">
                  <Label htmlFor="an-dino">用 DINO embedding 比較相似度、檢查標籤、解讀各層特徵</Label>
                  <p className="text-xs text-muted-foreground">
                    需要模型庫有選定的骨幹且工具池有 GPU 配額；否則自動改用 17 個 IQA
                    指標的向量。開啟後報告多兩節：標籤一致性檢查（最後一層 vs
                    跨層特徵各自猜每張影像屬於哪個資料夾）與各層特徵代表什麼。
                  </p>
                </div>
                <Switch id="an-dino" checked={dino} onCheckedChange={setDino} />
              </div>
              {dino ? (
                <div className="grid gap-1.5">
                  <Label htmlFor="an-backbone">骨幹</Label>
                  <Select value={backbone} onValueChange={setBackbone}>
                    <SelectTrigger id="an-backbone" className="w-full font-mono" data-testid="analysis-backbone">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {Object.entries(dinoBackboneLabel).map(([id, label]) => (
                        <SelectItem key={id} value={id}>
                          <span className="font-mono">{id}</span>
                          <span className="ml-2 text-xs text-muted-foreground">{label}</span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              ) : null}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={submit} disabled={!upload || pending} data-testid="analysis-run">
              {pending ? <LoaderCircle className="animate-spin" /> : <Play />}
              建立分析任務
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
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
