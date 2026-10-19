"use client";

import { Download, FolderInput, LoaderCircle, RefreshCw, Trash2, Upload } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";
import { toast } from "sonner";
import { StatusBadge } from "@/components/features/status-badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { familyLabel } from "@/i18n/zh-TW";
import { deleteWeightAction, importWeightAction } from "@/lib/actions";
import { formatBytes } from "@/lib/format";
import type { ModelZooEntry, ZooStatus } from "@/types/domain";
import { withBase } from "@/lib/base-path";

const zooStatusLabel: Partial<Record<ZooStatus, string>> = { error: "匯入失敗" };

export function ZooTable({
  entries,
  verified,
  canManage = true,
}: {
  entries: ModelZooEntry[];
  verified: boolean;
  canManage?: boolean;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [uploading, setUploading] = useState<string | null>(null);
  const [importTarget, setImportTarget] = useState<ModelZooEntry | null>(null);
  const [source, setSource] = useState<"url" | "path">("url");
  const [url, setUrl] = useState("");
  const [path, setPath] = useState("");
  const inputs = useRef<Record<string, HTMLInputElement | null>>({});
  const importing = entries.some((e) => e.status === "importing");

  // background imports: refresh the server-rendered table while any is running
  useEffect(() => {
    if (!importing) return;
    const id = setInterval(() => router.refresh(), 2000);
    return () => clearInterval(id);
  }, [importing, router]);

  const upload = async (entry: ModelZooEntry, file: File) => {
    setUploading(entry.id);
    try {
      const form = new FormData();
      form.append("file", file, file.name);
      const res = await fetch(withBase(`/api/admin/model-zoo/${encodeURIComponent(entry.id)}/upload`), {
        method: "POST",
        body: form,
      });
      const data = (await res.json()) as { detail?: { message?: string } };
      if (!res.ok) throw new Error(data.detail?.message ?? `HTTP ${res.status}`);
      toast.success(`${entry.id} 已匯入模型庫`);
      router.refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(null);
    }
  };

  const submitImport = () =>
    startTransition(async () => {
      if (!importTarget) return;
      const r = await importWeightAction(importTarget.id, {
        source,
        url: source === "url" ? url.trim() : undefined,
        path: source === "path" ? path.trim() : undefined,
      });
      if (!r.ok) toast.error(r.error);
      else {
        toast.success("已開始匯入，完成後會更新狀態");
        setImportTarget(null);
        setUrl("");
        setPath("");
        router.refresh();
      }
    });

  const remove = (entry: ModelZooEntry) =>
    startTransition(async () => {
      const r = await deleteWeightAction(entry.id);
      if (!r.ok) toast.error(r.error);
      else toast.success(`${entry.id} 已從模型庫移除`);
    });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" asChild>
          <Link href={verified ? "/admin/model-zoo" : "/admin/model-zoo?verify=1"}>
            <RefreshCw />
            {verified ? "已重新驗證 sha256" : "重新驗證 sha256"}
          </Link>
        </Button>
        <span className="text-xs text-muted-foreground">
          sha256 驗證會讀完整個檔案；大權重（BERT、xlm-roberta）要幾秒。
        </span>
      </div>
      <div className="overflow-x-auto rounded-xl border border-border bg-card">
        <Table className="table-fixed">
          <TableHeader>
            <TableRow>
              <TableHead className="w-[27%]">權重</TableHead>
              <TableHead className="w-[17%]">使用的家族</TableHead>
              <TableHead className="w-[15%]">狀態</TableHead>
              <TableHead className="w-[8%] text-right">大小</TableHead>
              <TableHead className="w-[22%]">來源 / 時間</TableHead>
              <TableHead className="w-[11%] text-right">動作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.map((e) => (
              <TableRow key={e.id}>
                <TableCell>
                  <div className="font-medium">{e.id}</div>
                  <div className="truncate font-mono text-xs text-muted-foreground" title={e.file}>
                    {e.file} · {e.kind === "hf_repo" ? "HF snapshot" : "單檔"} · {e.license ?? "—"}
                  </div>
                </TableCell>
                <TableCell className="truncate text-sm">{e.families.map((f) => familyLabel(f)).join("、")}</TableCell>
                <TableCell>
                  <div className="flex flex-col gap-1">
                    <StatusBadge status={e.status} label={zooStatusLabel[e.status]} />
                    {e.task?.state === "running" ? (
                      <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                        {e.task.downloadedMb} MB{e.task.totalMb ? ` / ${e.task.totalMb} MB` : ""}
                        {e.task.message ? ` · ${e.task.message}` : ""}
                      </span>
                    ) : null}
                    {e.task?.state === "error" ? (
                      <span className="text-[11px] text-destructive">{e.task.message}</span>
                    ) : null}
                    {e.sha256Actual ? (
                      <span className="font-mono text-[11px] text-muted-foreground">
                        sha256 {e.sha256Actual.slice(0, 12)}…
                      </span>
                    ) : null}
                  </div>
                </TableCell>
                <TableCell className="text-right font-mono text-xs tabular-nums">
                  {e.sizeBytes ? formatBytes(e.sizeBytes) : "—"}
                </TableCell>
                <TableCell
                  className="truncate font-mono text-xs text-muted-foreground"
                  title={e.importedFrom ?? e.source}
                >
                  {e.importedFrom ?? e.source ?? "—"}
                  {e.importedAt ? <div>{e.importedAt.slice(0, 16).replace("T", " ")}</div> : null}
                </TableCell>
                <TableCell className="text-right">
                  {!canManage ? (
                    <span className="text-xs text-muted-foreground">僅 superadmin</span>
                  ) : (
                    <div className="flex justify-end gap-1">
                      <input
                        type="file"
                        className="hidden"
                        ref={(el) => {
                          inputs.current[e.id] = el;
                        }}
                        accept={e.kind === "hf_repo" ? ".zip,.tar,.tar.gz,.tgz" : undefined}
                        onChange={(ev) => {
                          const f = ev.target.files?.[0];
                          if (f) void upload(e, f);
                          ev.target.value = "";
                        }}
                        data-testid={`zoo-upload-${e.id}`}
                      />
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="上傳"
                        title="從瀏覽器上傳"
                        disabled={uploading === e.id || e.status === "importing"}
                        onClick={() => inputs.current[e.id]?.click()}
                      >
                        {uploading === e.id ? <LoaderCircle className="animate-spin" /> : <Upload />}
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="匯入"
                        title="從伺服器路徑或內網 URL 匯入"
                        disabled={e.status === "importing"}
                        onClick={() => setImportTarget(e)}
                      >
                        <FolderInput />
                      </Button>
                      {e.present ? (
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label="移除"
                          disabled={pending}
                          onClick={() => remove(e)}
                        >
                          <Trash2 />
                        </Button>
                      ) : null}
                    </div>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <Dialog open={!!importTarget} onOpenChange={(o) => !o && setImportTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>匯入 {importTarget?.id}</DialogTitle>
            <DialogDescription>
              {importTarget?.kind === "hf_repo"
                ? "Hugging Face 類型：URL 或路徑指向整個 snapshot 的 zip / tar.gz，或伺服器上的資料夾。"
                : "單檔權重：URL 或伺服器路徑指向 .pt 檔。"}
              匯入在背景執行並比對 sha256。
            </DialogDescription>
          </DialogHeader>
          <Tabs value={source} onValueChange={(v) => setSource(v as "url" | "path")}>
            <TabsList className="w-full">
              <TabsTrigger value="url" className="flex-1">
                內網 URL
              </TabsTrigger>
              <TabsTrigger value="path" className="flex-1">
                伺服器路徑
              </TabsTrigger>
            </TabsList>
            <TabsContent value="url" className="grid gap-2 pt-4">
              <Label htmlFor="zoo-url">URL（主機須在 MODEL_ZOO_ALLOWED_HOSTS）</Label>
              <Input
                id="zoo-url"
                className="font-mono"
                placeholder={`http://mirror.example.com/models/${importTarget?.file ?? "weights.pt"}`}
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
            </TabsContent>
            <TabsContent value="path" className="grid gap-2 pt-4">
              <Label htmlFor="zoo-path">路徑（相對 MODEL_ZOO_IMPORT_ROOT，例如 NAS 或 USB 掛載點）</Label>
              <Input
                id="zoo-path"
                className="font-mono"
                placeholder={importTarget?.file ?? "weights.pt"}
                value={path}
                onChange={(e) => setPath(e.target.value)}
              />
            </TabsContent>
          </Tabs>
          <DialogFooter>
            <Button variant="outline" onClick={() => setImportTarget(null)}>
              取消
            </Button>
            <Button onClick={submitImport} disabled={pending || (source === "url" ? !url.trim() : !path.trim())}>
              <Download />
              開始匯入
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
