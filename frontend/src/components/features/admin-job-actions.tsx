"use client";

// Admin controls on a job page (jobs.control): force-stop a running job, re-queue a finished one. Members keep
// their own "取消" in JobStatusBar; deleting is JobDeleteButton (creators, maintainers and admins alike).
import { OctagonX, RotateCcw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { toast } from "sonner";
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
import { Textarea } from "@/components/ui/textarea";
import { jobCopy } from "@/i18n/zh-TW";
import { restartJobAction, stopJobAction } from "@/lib/actions";
import type { Job } from "@/types/domain";

export function AdminJobActions({ job }: { job: Job }) {
  const router = useRouter();
  const [dialog, setDialog] = useState<"stop" | "restart" | null>(null);
  const [reason, setReason] = useState("");
  const [pending, startTransition] = useTransition();
  const active = job.status === "queued" || job.status === "scheduled" || job.status === "running";
  const uploadInput = job.input.kind === "upload";
  const close = () => {
    setDialog(null);
    setReason("");
  };
  const stop = () =>
    startTransition(async () => {
      const r = await stopJobAction(job.id, reason.trim(), job.projectSlug);
      if (!r.ok) toast.error(r.error);
      else toast.success(`已送出強制中斷：任務 #${job.id}`);
      close();
    });
  const restart = () =>
    startTransition(async () => {
      const r = await restartJobAction(job.id, job.projectSlug);
      if (!r.ok) toast.error(r.error);
      else {
        toast.success(`已重新排入佇列：新任務 #${r.data.id}`);
        router.push(`/projects/${job.projectSlug}/jobs/${r.data.id}`);
      }
      close();
    });
  return (
    <>
      {active ? (
        <Button variant="destructive" size="sm" onClick={() => setDialog("stop")} data-testid="admin-stop">
          <OctagonX />
          強制中斷
        </Button>
      ) : (
        <>
          <Button
            variant="outline"
            size="sm"
            disabled={uploadInput}
            title={uploadInput ? "一次性上傳的資料已刪除，請用「複製設定」重新上傳" : undefined}
            onClick={() => setDialog("restart")}
            data-testid="admin-restart"
          >
            <RotateCcw />
            重新執行
          </Button>
        </>
      )}
      <AlertDialog open={dialog === "stop"} onOpenChange={(o) => !o && close()}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>強制中斷任務 #{job.id}？</AlertDialogTitle>
            <AlertDialogDescription>{jobCopy.forceStopDescription}</AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-2">
            <Label htmlFor="admin-stop-reason">理由（必填）</Label>
            <Textarea
              id="admin-stop-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="例：讓位給上線訓練；佔用 GPU 過久"
              rows={3}
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>返回</AlertDialogCancel>
            <AlertDialogAction
              disabled={reason.trim().length < 2 || pending}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={stop}
            >
              強制中斷
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <AlertDialog open={dialog === "restart"} onOpenChange={(o) => !o && close()}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>重新執行任務 #{job.id}？</AlertDialogTitle>
            <AlertDialogDescription>
              會以相同的輸入、資源與設定建立一個新任務排入佇列（AutoML 的候選模型會依目前的模型庫重新計算）；原任務與其
              log 保留。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>返回</AlertDialogCancel>
            <AlertDialogAction disabled={pending} onClick={restart}>
              重新排入佇列
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
