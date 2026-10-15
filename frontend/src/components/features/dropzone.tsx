"use client";

import { FileUp, Info, X } from "lucide-react";
import { useRef, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { common } from "@/i18n/zh-TW";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

export function Dropzone({ accept, hint, className }: { accept?: string; hint?: string; className?: string }) {
  const [file, setFile] = useState<File | null>(null);
  const [over, setOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div className={cn("space-y-3", className)}>
      <Alert>
        <Info />
        <AlertDescription>{common.dataNotStoredNotice}</AlertDescription>
      </Alert>
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
          if (f) setFile(f);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed px-6 py-10 text-center transition-colors focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none",
          over ? "border-primary/50 bg-primary/5" : "border-border-strong hover:bg-accent/40",
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          className="sr-only"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <FileUp className="size-6 text-muted-foreground" />
        <div className="mt-3 text-sm font-medium">拖曳檔案到這裡，或點擊選擇</div>
        <div className="mt-1 text-xs text-muted-foreground">{hint ?? "單一檔案或 zip；大小上限 2 GB"}</div>
      </div>
      {file ? (
        <div className="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2">
          <div className="min-w-0">
            <div className="truncate font-mono text-sm">{file.name}</div>
            <div className="font-mono text-xs text-muted-foreground">{formatBytes(file.size)}</div>
          </div>
          <Button variant="ghost" size="icon-sm" aria-label="移除檔案" onClick={() => setFile(null)}>
            <X />
          </Button>
        </div>
      ) : null}
    </div>
  );
}
