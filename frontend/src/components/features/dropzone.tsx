"use client";

import { CircleCheck, FileUp, Info, LoaderCircle, X } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { common, uploadCopy } from "@/i18n/zh-TW";
import { toUpload } from "@/lib/api/mappers";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Upload } from "@/types/domain";

/** Matches the backend / nginx limit; a larger file is refused before any byte is sent. */
export const DEFAULT_MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024;

/** The proxies relay JSON errors as `{detail:{code,message}}`; anything else (nginx 413 page) is handled here. */
async function readError(res: Response): Promise<string> {
  const type = res.headers.get("content-type") ?? "";
  if (type.includes("application/json")) {
    try {
      const json = (await res.json()) as { detail?: { message?: string } | string };
      const d = json.detail;
      const msg = typeof d === "string" ? d : d?.message;
      if (msg) return msg;
    } catch {
      /* fall through */
    }
  }
  return uploadCopy.rejectedByServer(res.status);
}

export function Dropzone({
  slug,
  endpoint,
  fields,
  onUploaded,
  accept,
  hint,
  maxBytes = DEFAULT_MAX_UPLOAD_BYTES,
  className,
}: {
  /** Project upload (default endpoint /api/upload/{slug}). */
  slug?: string;
  /** Override the upload URL (the standalone preprocessing tool posts to /api/tools/upload). */
  endpoint?: string;
  /** Extra multipart fields sent next to the file (the tool upload needs `data_type`). */
  fields?: Record<string, string>;
  /** `raw` is the backend's JSON as-is (the tool endpoint returns a string id the Upload type cannot hold). */
  onUploaded: (upload: Upload | null, raw?: Record<string, unknown>) => void;
  accept?: string;
  hint?: string;
  /** Client-side size limit; files above it are rejected with a toast before uploading. */
  maxBytes?: number;
  className?: string;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [upload, setUpload] = useState<Upload | null>(null);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const send = async (f: File) => {
    if (maxBytes > 0 && f.size > maxBytes) {
      toast.error(uploadCopy.tooLarge(formatBytes(maxBytes), formatBytes(f.size)));
      if (inputRef.current) inputRef.current.value = "";
      return;
    }
    setFile(f);
    setBusy(true);
    try {
      const form = new FormData();
      for (const [k, v] of Object.entries(fields ?? {})) form.append(k, v);
      form.append("file", f);
      const url = endpoint ?? `/api/upload/${encodeURIComponent(slug ?? "")}`;
      const res = await fetch(url, { method: "POST", body: form });
      if (!res.ok) throw new Error(await readError(res));
      let json: Record<string, unknown>;
      try {
        json = (await res.json()) as Record<string, unknown>;
      } catch {
        throw new Error("伺服器回應不是 JSON");
      }
      const up = toUpload(json);
      setUpload(up);
      onUploaded(up, json);
      toast.success(`已上傳 ${up.originalFilename}`);
    } catch (e) {
      setFile(null);
      toast.error(uploadCopy.failed(e instanceof Error ? e.message : String(e)));
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
            {hint ?? `csv / parquet / jsonl / npy，或圖片 zip；大小上限 ${formatBytes(maxBytes)}`}
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
