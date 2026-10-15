"use client";

// Per-GPU cards on the admin dashboard: driver memory vs what the scheduler reserved, the jobs placed there,
// and (superadmin) the force-reset dialog. The backend audits every reset.
import { RotateCcw } from "lucide-react";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { ResourceMeter } from "@/components/features/resource-meter";
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
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Textarea } from "@/components/ui/textarea";
import { resetGpuAction } from "@/lib/actions";
import { formatMb } from "@/lib/format";
import type { GpuResetMode, NodeGpu } from "@/types/domain";

const modes: { value: GpuResetMode; label: string; hint: string }[] = [
  {
    value: "jobs",
    label: "只中斷本系統的任務",
    hint: "排程器放在這張 GPU 上的任務會被強制中斷（SIGTERM，10 秒後 SIGKILL）。",
  },
  {
    value: "all",
    label: "連其他程序一起 kill",
    hint: "再把驅動程式看到的所有使用這張 GPU 的程序一併 SIGKILL（需要相同使用者或 root）。",
  },
  {
    value: "device",
    label: "重置裝置（nvidia-smi --gpu-reset）",
    hint: "以上全部，再執行伺服器設定的 GPU_RESET_COMMAND；卡上不能有任何程序。",
  },
];

export function GpuCards({
  gpus,
  poolIndices,
  canReset,
}: {
  gpus: NodeGpu[];
  poolIndices: number[];
  canReset: boolean;
}) {
  const [target, setTarget] = useState<NodeGpu | null>(null);
  const [mode, setMode] = useState<GpuResetMode>("jobs");
  const [reason, setReason] = useState("");
  const [pending, startTransition] = useTransition();
  if (gpus.length === 0) {
    return (
      <Card className="gap-2 p-5" data-testid="gpu-cards">
        <div className="text-label">GPU</div>
        <p className="text-sm text-muted-foreground">這台主機沒有偵測到 NVIDIA GPU（或 pynvml 無法讀取）。</p>
      </Card>
    );
  }
  const run = () => {
    const g = target;
    if (!g) return;
    startTransition(async () => {
      const r = await resetGpuAction(g.index, mode, reason.trim());
      if (!r.ok) toast.error(r.error);
      else {
        const d = r.data;
        toast.success(
          `GPU ${g.index} 已重置：中斷 ${d.stoppedJobs.length} 個任務、kill ${d.killedPids.length} 個程序` +
            (d.skippedPids.length ? `、${d.skippedPids.length} 個無權限略過` : "") +
            (d.memoryUsedMbAfter != null
              ? `；顯存 ${formatMb(d.memoryUsedMbBefore ?? 0)} → ${formatMb(d.memoryUsedMbAfter)}`
              : ""),
        );
        if (d.command && d.commandOk === false) toast.error(`裝置重置指令失敗：${d.commandOutput ?? ""}`);
      }
      setTarget(null);
      setReason("");
      setMode("jobs");
    });
  };
  return (
    <div className="grid gap-3 sm:grid-cols-2" data-testid="gpu-cards">
      {gpus.map((g) => {
        const inPool = poolIndices.includes(g.index);
        const exclusive = g.reservedMb != null && g.reservedMb >= g.memoryTotalMb && g.jobIds.length > 0;
        return (
          <Card key={g.index} className="gap-3 p-4">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="font-mono text-sm font-medium">
                  GPU {g.index}
                  {!inPool ? <span className="ml-2 text-xs font-normal text-muted-foreground">不在資源池</span> : null}
                </div>
                <div className="truncate text-xs text-muted-foreground" title={g.name}>
                  {g.name}
                </div>
              </div>
              {canReset ? (
                <Button variant="outline" size="sm" onClick={() => setTarget(g)} data-testid={`gpu-reset-${g.index}`}>
                  <RotateCcw />
                  重置
                </Button>
              ) : null}
            </div>
            <ResourceMeter
              label="顯存（驅動程式）"
              used={g.memoryUsedMb}
              total={g.memoryTotalMb}
              format={formatMb}
              compact
            />
            <ResourceMeter label="使用率" used={g.utilization} total={100} unit="%" compact />
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs text-muted-foreground tabular-nums">
              <span>任務 {g.jobIds.length ? g.jobIds.map((id) => `#${id}`).join(" ") : "—"}</span>
              <span>{exclusive ? "獨占" : g.reservedMb != null ? `保留 ${formatMb(g.reservedMb)}` : "未保留"}</span>
              {g.processes != null ? <span>程序 {g.processes}</span> : null}
            </div>
          </Card>
        );
      })}
      <AlertDialog open={!!target} onOpenChange={(o) => !o && setTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>強制釋放 GPU {target?.index} 的顯存？</AlertDialogTitle>
            <AlertDialogDescription>
              目前顯存 {formatMb(target?.memoryUsedMb ?? 0)} / {formatMb(target?.memoryTotalMb ?? 0)}，任務{" "}
              {target?.jobIds.length ? target.jobIds.map((id) => `#${id}`).join("、") : "無"}。操作會寫入稽核紀錄。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <RadioGroup value={mode} onValueChange={(v) => setMode(v as GpuResetMode)} className="gap-3">
            {modes.map((m) => (
              <div key={m.value} className="flex items-start gap-3 rounded-lg border border-border p-3">
                <RadioGroupItem value={m.value} id={`gpu-mode-${m.value}`} className="mt-0.5" />
                <div className="space-y-0.5">
                  <Label htmlFor={`gpu-mode-${m.value}`}>{m.label}</Label>
                  <p className="text-xs text-muted-foreground">{m.hint}</p>
                </div>
              </div>
            ))}
          </RadioGroup>
          <div className="space-y-2">
            <Label htmlFor="gpu-reset-reason">理由（必填）</Label>
            <Textarea
              id="gpu-reset-reason"
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="例：任務已結束但顯存沒有釋放"
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>返回</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={pending || reason.trim().length < 2}
              onClick={run}
            >
              重置 GPU
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
