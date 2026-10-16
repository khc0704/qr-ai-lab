"use client";

import { Ban, Cpu, HardDrive, MemoryStick, Timer } from "lucide-react";
import { useState, useTransition } from "react";
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
import { jobCopy, jobStageLabel } from "@/i18n/zh-TW";
import { cancelJobAction } from "@/lib/actions";
import { isAdminRole } from "@/lib/roles";
import { Duration } from "@/components/features/time";
import { formatMb } from "@/lib/format";
import type { Job } from "@/types/domain";

export function JobStatusBar({
  job,
  queuePosition,
  canCancel = false,
}: {
  job: Job;
  queuePosition?: number;
  /** Computed by the page with `canCancelJob()` (members cancel their own, maintainer+ any; admins everywhere). */
  canCancel?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();
  const cancellable = canCancel && (job.status === "queued" || job.status === "scheduled" || job.status === "running");
  const cancel = () =>
    startTransition(async () => {
      const r = await cancelJobAction(job.id, job.projectSlug);
      if (!r.ok) toast.error(r.error);
      else toast.success(job.status === "queued" ? jobCopy.cancelRemovedFromQueue : jobCopy.cancelRequested);
    });
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4">
        <StatusBadge status={job.status} />
        <KindChip kind={job.kind} />
        {(job.status === "running" || job.status === "scheduled") && job.currentStage ? (
          <span className="text-sm text-muted-foreground">{jobStageLabel[job.currentStage]}</span>
        ) : null}
        {job.status === "queued" && (queuePosition ?? job.queuePosition) ? (
          <span className="font-mono text-sm text-muted-foreground tabular-nums">
            佇列 #{queuePosition ?? job.queuePosition}
            {job.waitReason ? <span className="ml-2 font-sans text-xs text-warning">{job.waitReason}</span> : null}
          </span>
        ) : null}
        {job.startedAt ? (
          <span className="inline-flex items-center gap-1 font-mono text-xs text-muted-foreground tabular-nums">
            <Timer className="size-3.5" />
            <Duration start={job.startedAt} end={job.finishedAt} />
          </span>
        ) : null}
        <span className="ml-auto flex flex-wrap items-center gap-2 font-mono text-xs text-muted-foreground tabular-nums">
          <span className="inline-flex items-center gap-1 rounded-sm bg-muted px-1.5 py-0.5">
            <HardDrive className="size-3" />
            {job.requestedGpu} GPU{job.assignedGpus?.length ? ` [${job.assignedGpus.join(",")}]` : ""}
            {job.requestedGpu > 0 && job.requestedGpuMemoryMb ? ` · ${formatMb(job.requestedGpuMemoryMb)} VRAM` : ""}
          </span>
          <span className="inline-flex items-center gap-1 rounded-sm bg-muted px-1.5 py-0.5">
            <Cpu className="size-3" />
            {job.requestedCpu} CPU{job.assignedCpus?.length ? ` [${job.assignedCpus.join(",")}]` : ""}
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
            此任務由{isAdminRole(job.cancelRequestedBy?.role) ? "管理員" : ""}
            {job.cancelRequestedBy ? ` ${job.cancelRequestedBy.displayName}` : ""} 取消
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
              {job.status === "running" ? jobCopy.cancelRunningDescription : jobCopy.cancelQueuedDescription}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>返回</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={pending}
              onClick={cancel}
            >
              取消任務
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
