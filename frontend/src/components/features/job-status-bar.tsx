"use client";

import { Ban, Cpu, HardDrive, MemoryStick, Timer } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { KindChip } from "@/components/features/chips";
import { StatusBadge } from "@/components/features/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import { jobStageLabel } from "@/i18n/zh-TW";
import { formatDuration, formatMb } from "@/lib/format";
import type { Job } from "@/types/domain";

export function JobStatusBar({ job, queuePosition }: { job: Job; queuePosition?: number }) {
  const [open, setOpen] = useState(false);
  const cancellable = job.status === "queued" || job.status === "scheduled" || job.status === "running";
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4">
        <StatusBadge status={job.status} />
        <KindChip kind={job.kind} />
        {job.status === "running" && job.currentStage ? (
          <span className="text-sm text-muted-foreground">{jobStageLabel[job.currentStage]}</span>
        ) : null}
        {job.status === "queued" && queuePosition ? (
          <span className="font-mono text-sm text-muted-foreground tabular-nums">
            佇列 #{queuePosition}
            {job.waitReason ? <span className="ml-2 font-sans text-xs text-warning">{job.waitReason}</span> : null}
          </span>
        ) : null}
        {job.startedAt ? (
          <span className="inline-flex items-center gap-1 font-mono text-xs text-muted-foreground tabular-nums">
            <Timer className="size-3.5" />
            {formatDuration(job.startedAt, job.finishedAt)}
          </span>
        ) : null}
        <span className="ml-auto flex flex-wrap items-center gap-2 font-mono text-xs text-muted-foreground tabular-nums">
          <span className="inline-flex items-center gap-1 rounded-sm bg-muted px-1.5 py-0.5">
            <HardDrive className="size-3" />
            {job.requestedGpu} GPU{job.assignedGpus?.length ? ` [${job.assignedGpus.join(",")}]` : ""}
          </span>
          <span className="inline-flex items-center gap-1 rounded-sm bg-muted px-1.5 py-0.5">
            <Cpu className="size-3" />
            {job.requestedCpu} CPU
          </span>
          <span className="inline-flex items-center gap-1 rounded-sm bg-muted px-1.5 py-0.5">
            <MemoryStick className="size-3" />
            {formatMb(job.requestedMemoryMb)}
          </span>
        </span>
        {cancellable ? (
          <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
            <Ban />
            取消
          </Button>
        ) : null}
      </div>
      {job.status === "cancelled" && job.cancelReason ? (
        <Alert className="border-warning/30 bg-warning/10 text-warning">
          <Ban />
          <AlertTitle>
            此任務由管理員{job.cancelRequestedBy ? ` ${job.cancelRequestedBy.displayName}` : ""}強制中斷
          </AlertTitle>
          <AlertDescription className="text-warning/90">{job.cancelReason}</AlertDescription>
        </Alert>
      ) : null}
      {job.status === "failed" && job.errorMessage ? (
        <Alert variant="destructive">
          <Ban />
          <AlertTitle>任務失敗</AlertTitle>
          <AlertDescription className="font-mono text-xs">{job.errorMessage}</AlertDescription>
        </Alert>
      ) : null}
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>取消任務 #{job.id}？</AlertDialogTitle>
            <AlertDialogDescription>
              {job.status === "running"
                ? "執行中的容器會被停止，已產生的指標會保留在 log，但不會產生產物。"
                : "任務會從佇列移除，可以之後重新建立。"}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>返回</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => toast.success(`已送出取消請求：任務 #${job.id}`)}
            >
              取消任務
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
