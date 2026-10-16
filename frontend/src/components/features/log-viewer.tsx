"use client";

import { ArrowDownToLine, Copy, Download, WrapText } from "lucide-react";
import { memo, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { StatusBadge } from "@/components/features/status-badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { jobCopy } from "@/i18n/zh-TW";
import type { StreamConnection } from "@/hooks/use-job-stream";
import { cn } from "@/lib/utils";
import type { JobStatus, LogLevel, LogLine } from "@/types/domain";

const levelClass: Record<LogLevel, string> = {
  INFO: "text-foreground",
  WARN: "text-warning",
  ERROR: "text-destructive",
  DEBUG: "text-muted-foreground",
  SYSTEM: "text-brand-ink",
};

function hhmmss(iso: string) {
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`;
}

/** One log line; memoised so an SSE append re-renders only the new row, not the whole table. */
const LogRow = memo(function LogRow({ line, wrap }: { line: LogLine; wrap: boolean }) {
  return (
    <tr className="hover:bg-accent/40">
      <td className="w-10 pr-3 pl-3 text-right align-top text-subtle-foreground select-none">{line.n}</td>
      <td className="w-20 pr-3 align-top text-subtle-foreground select-none">{hhmmss(line.ts)}</td>
      <td
        className={cn(
          "pr-3 align-top",
          levelClass[line.level] ?? levelClass.INFO,
          wrap ? "break-all whitespace-pre-wrap" : "whitespace-pre",
        )}
      >
        {line.level === "SYSTEM" ? <span className="mr-1 select-none">[system]</span> : null}
        {line.text}
      </td>
    </tr>
  );
});

export function LogViewer({
  lines,
  status,
  title = "Log",
  className,
  maxHeight = "max-h-[480px]",
  downloadHref,
  connection = "idle",
  dropped = 0,
}: {
  lines: LogLine[];
  status?: JobStatus;
  title?: string;
  className?: string;
  maxHeight?: string;
  downloadHref?: string;
  /** Live stream state from useJobStream; "reconnecting" shows the disconnected notice. */
  connection?: StreamConnection;
  /** Lines evicted from the client buffer (the download still has them). */
  dropped?: number;
}) {
  const live = status === "running" || status === "scheduled";
  const [autoScroll, setAutoScroll] = useState(true);
  const [wrap, setWrap] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [lines.length, autoScroll]);

  const copy = async () => {
    await navigator.clipboard.writeText(lines.map((l) => `${l.ts} [${l.level}] ${l.text}`).join("\n"));
    toast.success("已複製 log");
  };

  return (
    <div className={cn("overflow-hidden rounded-xl border border-border bg-background", className)}>
      <div className="flex flex-wrap items-center gap-3 border-b border-border bg-card px-3 py-2">
        <span className="text-sm font-medium">{title}</span>
        {status ? <StatusBadge status={status} /> : null}
        <span className="font-mono text-xs text-muted-foreground tabular-nums">{lines.length} 行</span>
        <div className="ml-auto flex items-center gap-3">
          <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
            <ArrowDownToLine className="size-3.5" />
            自動捲動
            <Switch checked={autoScroll} onCheckedChange={setAutoScroll} aria-label="自動捲動" />
          </label>
          <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
            <WrapText className="size-3.5" />
            換行
            <Switch checked={wrap} onCheckedChange={setWrap} aria-label="換行" />
          </label>
          <Button variant="ghost" size="icon-sm" aria-label="複製" onClick={copy}>
            <Copy />
          </Button>
          {downloadHref ? (
            <Button variant="ghost" size="icon-sm" aria-label="下載" asChild>
              <a href={downloadHref} download>
                <Download />
              </a>
            </Button>
          ) : null}
        </div>
      </div>
      <div
        ref={bodyRef}
        className={cn("overflow-auto font-mono text-xs leading-5", maxHeight)}
        aria-live={live && !autoScroll ? "polite" : undefined}
      >
        {dropped > 0 ? (
          <div className="border-b border-border bg-muted px-3 py-1.5 text-muted-foreground">
            {jobCopy.logTruncated(lines.length)}
            <span className="ml-1 tabular-nums">（已省略 {dropped} 行）</span>
          </div>
        ) : null}
        {lines.length === 0 ? (
          <div className="p-4 text-muted-foreground">{jobCopy.noLogYet}</div>
        ) : (
          <table className="w-full border-collapse">
            <tbody>
              {lines.map((l) => (
                <LogRow key={l.n} line={l} wrap={wrap} />
              ))}
            </tbody>
          </table>
        )}
        {live && connection === "reconnecting" ? (
          <div className="flex items-center gap-2 px-3 py-2 text-warning" role="status">
            <span className="size-1.5 rounded-full bg-warning" />
            {jobCopy.reconnecting}
          </div>
        ) : live ? (
          <div className="flex items-center gap-2 px-3 py-2 text-muted-foreground">
            <span className="size-1.5 animate-pulse-dot rounded-full bg-primary motion-reduce:animate-none" />
            {jobCopy.streaming}
          </div>
        ) : null}
      </div>
    </div>
  );
}
