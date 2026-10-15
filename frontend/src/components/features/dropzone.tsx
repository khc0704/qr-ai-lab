"use client";

import { CircleCheck, FileUp, Info, LoaderCircle, X } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { common } from "@/i18n/zh-TW";
import { toUpload } from "@/lib/api/mappers";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Upload } from "@/types/domain";

export function Dropzone({
  slug,
  onUploaded,
  accept,
  hint,
  className,
}: {
  slug: string;
  onUploaded: (upload: Upload | null) => void;
  accept?: string;
  hint?: string;
  className?: string;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [upload, setUpload] = useState<Upload | null>(null);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const send = async (f: File) => {
    setFile(f);
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", f);
      const res = await fetch(`/api/upload/${encodeURIComponent(slug)}`, { method: "POST", body: form });
      const json = (await res.json()) as Record<string, unknown>;
      if (!res.ok) {
        const d = json.detail as { message?: string } | string | undefined;
        throw new Error(typeof d === "string" ? d : (d?.message ?? `HTTP ${res.status}`));
      }
      const up = toUpload(json);
      setUpload(up);
      onUploaded(up);
      toast.success(`已上傳 ${up.originalFilename}`);
    } catch (e) {
      setFile(null);
      toast.error(`上傳失敗：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const clear = () => {
    setFile(null);
    setUpload(null);
    onUploaded(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div className={cn("space-y-3", className)}>
      <Alert>
        <Info />
        <AlertDescription>{common.dataNotStoredNotice}</AlertDescription>
      </Alert>
      {!file ? (
        <div
          role="button"
          tabIndex={0}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setOver(false);
            const f = e.dataTransfer.files?.[0];
            if (f) void send(f);
          }}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed px-6 py-10 text-center transition-colors focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none",
            over ? "border-primary/50 bg-primary/5" : "border-border-strong hover:bg-accent/40",
          )}
        >
          <FileUp className="size-6 text-muted-foreground" />
          <div className="mt-3 text-sm font-medium">拖曳檔案到這裡，或點擊選擇</div>
          <div className="mt-1 text-xs text-muted-foreground">
            {hint ?? "csv / parquet / jsonl / npy，或圖片 zip；大小上限 2 GB"}
          </div>
        </div>
      ) : null}
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="sr-only"
        data-testid="upload-input"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void send(f);
        }}
      />
      {file ? (
        <div className="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2">
          <div className="flex min-w-0 items-center gap-3">
            {busy ? (
              <LoaderCircle className="size-4 animate-spin text-muted-foreground" />
            ) : (
              <CircleCheck className="size-4 text-success" />
            )}
            <div className="min-w-0">
              <div className="truncate font-mono text-sm">{file.name}</div>
              <div className="font-mono text-xs text-muted-foreground">
                {formatBytes(file.size)}
                {upload?.detectedSpec && "row_count" in upload.detectedSpec
                  ? ` · ${String(upload.detectedSpec.row_count)} 列`
                  : ""}
                {upload?.detectedSpec && "image_count" in upload.detectedSpec
                  ? ` · ${String(upload.detectedSpec.image_count)} 張影像`
                  : ""}
              </div>
            </div>
          </div>
          <Button variant="ghost" size="icon-sm" aria-label="移除檔案" onClick={clear} disabled={busy}>
            <X />
          </Button>
        </div>
      ) : null}
    </div>
  );
}
