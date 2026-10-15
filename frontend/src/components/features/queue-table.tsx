"use client";

import { ArrowDown, ArrowDownToLine, ArrowUp, ArrowUpToLine, Eye, OctagonX } from "lucide-react";
import Link from "next/link";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { KindChip } from "@/components/features/chips";
import { LogViewer } from "@/components/features/log-viewer";
import { UserInline } from "@/components/features/member-avatars";
import { StatusBadge } from "@/components/features/status-badge";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { jobStageLabel } from "@/i18n/zh-TW";
import { moveQueueAction, stopJobAction } from "@/lib/actions";
import { Duration, RelativeTime } from "@/components/features/time";
import { formatMb } from "@/lib/format";
import type { Job, LogLine } from "@/types/domain";

function Resources({ job }: { job: Job }) {
  return (
    <span className="font-mono text-xs text-muted-foreground tabular-nums">
      {job.requestedGpu} GPU · {job.requestedCpu} CPU · {formatMb(job.requestedMemoryMb)}
    </span>
  );
}

export function QueueTable({
  running,
  queued,
  logs,
}: {
  running: Job[];
  queued: Job[];
  logs: Record<number, LogLine[]>;
}) {
  const order = queued;
  const [stopTarget, setStopTarget] = useState<Job | null>(null);
  const [reason, setReason] = useState("");
  const [sheetJob, setSheetJob] = useState<Job | null>(null);
  const [pending, startTransition] = useTransition();

  const move = (id: number, to: "top" | "up" | "down" | "bottom") =>
    startTransition(async () => {
      const r = await moveQueueAction(id, to);
      if (!r.ok) toast.error(r.error);
    });
  const stop = () => {
    const target = stopTarget;
    if (!target) return;
    startTransition(async () => {
      const r = await stopJobAction(target.id, reason.trim());
      if (!r.ok) toast.error(r.error);
      else toast.success(`已送出強制中斷：任務 #${target.id}`);
      setReason("");
      setStopTarget(null);
    });
  };

  const head = (label: string, cls?: string) => <TableHead className={cls}>{label}</TableHead>;

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-semibold tracking-tight">執行中</h2>
          <span className="font-mono text-xs text-muted-foreground tabular-nums">{running.length} 個</span>
        </div>
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                {head("任務")}
                {head("專案")}
                {head("階段")}
                {head("資源")}
                {head("GPU", "text-right")}
                {head("已執行", "text-right")}
                {head("", "w-32")}
              </TableRow>
            </TableHeader>
            <TableBody>
              {running.map((j) => (
                <TableRow key={j.id}>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <StatusBadge status={j.status} />
                      <KindChip kind={j.kind} />
                      <Link
                        href={`/projects/${j.projectSlug}/jobs/${j.id}`}
                        className="font-medium hover:text-brand-ink"
                      >
                        {j.name}
                      </Link>
                      <span className="font-mono text-xs text-subtle-foreground">#{j.id}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Link href={`/projects/${j.projectSlug}`} className="text-muted-foreground hover:text-brand-ink">
                      {j.projectName}
                    </Link>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {j.currentStage ? jobStageLabel[j.currentStage] : "—"}{" "}
                    <span className="font-mono text-xs tabular-nums">{j.progress}%</span>
                  </TableCell>
                  <TableCell>
                    <Resources job={j} />
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums">
                    {j.assignedGpus?.length ? `[${j.assignedGpus.join(",")}]` : "—"}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums">
                    {j.startedAt ? <Duration start={j.startedAt} /> : "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button variant="ghost" size="icon-sm" aria-label="檢視" onClick={() => setSheetJob(j)}>
                            <Eye />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>檢視與 Log</TooltipContent>
                      </Tooltip>
                      <Button variant="destructive" size="sm" onClick={() => setStopTarget(j)}>
                        <OctagonX />
                        強制中斷
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-semibold tracking-tight">等待中</h2>
          <span className="font-mono text-xs text-muted-foreground tabular-nums">
            {order.length} 個 · 依序執行，資源不足時允許 backfill
          </span>
        </div>
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                {head("#", "w-12 text-right")}
                {head("任務")}
                {head("專案")}
                {head("資源")}
                {head("等待原因")}
                {head("建立者")}
                {head("排入", "text-right")}
                {head("", "w-44")}
              </TableRow>
            </TableHeader>
            <TableBody>
              {order.map((j, i) => (
                <TableRow key={j.id}>
                  <TableCell className="text-right font-mono text-xs text-muted-foreground tabular-nums">
                    {i + 1}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <KindChip kind={j.kind} />
                      <Link
                        href={`/projects/${j.projectSlug}/jobs/${j.id}`}
                        className="font-medium hover:text-brand-ink"
                      >
                        {j.name}
                      </Link>
                      <span className="font-mono text-xs text-subtle-foreground">#{j.id}</span>
                    </div>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{j.projectName}</TableCell>
                  <TableCell>
                    <Resources job={j} />
                  </TableCell>
                  <TableCell className="text-xs text-warning">{j.waitReason ?? "—"}</TableCell>
                  <TableCell>
                    <UserInline user={j.createdBy} />
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs text-muted-foreground tabular-nums">
                    <RelativeTime iso={j.createdAt} />
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-0.5">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="置頂"
                        disabled={i === 0 || pending}
                        onClick={() => move(j.id, "top")}
                      >
                        <ArrowUpToLine />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="上移"
                        disabled={i === 0 || pending}
                        onClick={() => move(j.id, "up")}
                      >
                        <ArrowUp />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="下移"
                        disabled={i === order.length - 1 || pending}
                        onClick={() => move(j.id, "down")}
                      >
                        <ArrowDown />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="置底"
                        disabled={i === order.length - 1 || pending}
                        onClick={() => move(j.id, "bottom")}
                      >
                        <ArrowDownToLine />
                      </Button>
                      <Button variant="ghost" size="icon-sm" aria-label="檢視" onClick={() => setSheetJob(j)}>
                        <Eye />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>

      <AlertDialog open={!!stopTarget} onOpenChange={(o) => !o && setStopTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>強制中斷任務 #{stopTarget?.id}？</AlertDialogTitle>
            <AlertDialogDescription>
              容器會在 10 秒寬限後停止，任務標記為「已取消」，理由會寫入 log 與稽核紀錄並顯示給任務建立者。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-2">
            <Label htmlFor="stop-reason">理由（必填）</Label>
            <Textarea
              id="stop-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="例：讓位給上線訓練；佔用 GPU 過久"
              rows={3}
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>返回</AlertDialogCancel>
            <AlertDialogAction
              disabled={!reason.trim() || pending}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={stop}
            >
              強制中斷
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Sheet open={!!sheetJob} onOpenChange={(o) => !o && setSheetJob(null)}>
        <SheetContent className="w-full sm:max-w-2xl">
          {sheetJob ? (
            <>
              <SheetHeader>
                <SheetTitle className="flex items-center gap-2">
                  {sheetJob.name} <span className="font-mono text-sm text-subtle-foreground">#{sheetJob.id}</span>
                </SheetTitle>
                <SheetDescription className="flex flex-wrap items-center gap-2">
                  <StatusBadge status={sheetJob.status} />
                  <KindChip kind={sheetJob.kind} />
                  <span>{sheetJob.projectName}</span>
                  <Resources job={sheetJob} />
                </SheetDescription>
              </SheetHeader>
              <div className="px-4 pb-4">
                <LogViewer lines={logs[sheetJob.id] ?? []} status={sheetJob.status} maxHeight="max-h-[60vh]" />
              </div>
            </>
          ) : null}
        </SheetContent>
      </Sheet>
    </div>
  );
}
