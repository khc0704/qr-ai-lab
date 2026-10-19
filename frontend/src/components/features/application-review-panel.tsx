"use client";

import { CircleCheck, CircleX, Eye } from "lucide-react";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { Textarea } from "@/components/ui/textarea";
import { projectRoleLabel } from "@/i18n/zh-TW";
import { approveApplicationAction, rejectApplicationAction, reviewApplicationAction } from "@/lib/actions";
import { formatMb } from "@/lib/format";
import type { Project, ResourcePool } from "@/types/domain";

/** Admin controls on the 申請 tab: start the review, approve (set the quota and members) or reject. */
export function ApplicationReviewPanel({ project, pool }: { project: Project; pool: ResourcePool }) {
  const app = project.application;
  const [approveOpen, setApproveOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [name, setName] = useState(project.name);
  const [gpu, setGpu] = useState(app?.requestedGpu ?? 0);
  const [cpu, setCpu] = useState(app?.requestedCpu ?? 2);
  const [mem, setMem] = useState(app?.requestedMemoryMb ?? 4096);
  const [storage, setStorage] = useState(app?.requestedStorageMb ?? 10240);
  const [maxJobs, setMaxJobs] = useState(1);
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [memberEmails, setMemberEmails] = useState<string[]>((app?.members ?? []).map((m) => m.email));
  const [pending, startTransition] = useTransition();
  if (!app || (project.status !== "pending" && project.status !== "in_review")) return null;
  const overPool = gpu > pool.gpuIndices.length;
  const review = () =>
    startTransition(async () => {
      const r = await reviewApplicationAction(project.slug);
      if (!r.ok) toast.error(r.error);
      else toast.success("已標記為審核中");
    });
  const approve = () =>
    startTransition(async () => {
      const r = await approveApplicationAction(project.slug, {
        name: name.trim() || undefined,
        gpu_limit: gpu,
        cpu_limit: cpu,
        memory_limit_mb: mem,
        storage_quota_mb: storage,
        max_concurrent_jobs: maxJobs,
        members: app.members.filter((m) => memberEmails.includes(m.email)),
        review_note: note.trim() || undefined,
      });
      if (!r.ok) {
        toast.error(r.error);
        return;
      }
      setApproveOpen(false);
      toast.success(`已核准，專案 ${r.data.slug} 開始進行`);
    });
  const reject = () =>
    startTransition(async () => {
      const r = await rejectApplicationAction(project.slug, reason);
      if (!r.ok) {
        toast.error(r.error);
        return;
      }
      setRejectOpen(false);
      setReason("");
      toast.success("已退回申請");
    });

  return (
    <div className="space-y-2 rounded-xl border border-primary/30 bg-primary/5 p-4" data-testid="review-panel">
      <div className="text-label">管理員審核</div>
      <div className="flex flex-wrap gap-2">
        {project.status === "pending" ? (
          <Button variant="outline" size="sm" onClick={review} disabled={pending}>
            <Eye />
            開始審核
          </Button>
        ) : null}
        <Button size="sm" onClick={() => setApproveOpen(true)} data-testid="approve-open">
          <CircleCheck />
          核准
        </Button>
        <Button variant="destructive" size="sm" onClick={() => setRejectOpen(true)}>
          <CircleX />
          退回
        </Button>
      </div>

      <Dialog open={approveOpen} onOpenChange={setApproveOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>核准並設定配額</DialogTitle>
            <DialogDescription>
              核准後專案立即開始進行、加入成員並通知申請人。配額之後仍可在專案的「設定」分頁調整。
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="ap-name">專案名稱</Label>
              <Input id="ap-name" value={name} onChange={(e) => setName(e.target.value)} />
              <p className="text-xs text-muted-foreground">
                slug <span className="font-mono text-foreground">{project.slug}</span> 已在申請時決定。
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-2">
                <Label htmlFor="q-gpu">GPU</Label>
                <Input
                  id="q-gpu"
                  type="number"
                  min={0}
                  value={gpu}
                  onChange={(e) => setGpu(Number(e.target.value))}
                  className="text-right font-mono"
                  aria-invalid={overPool}
                />
                {overPool ? (
                  <p className="text-xs text-destructive">超過資源池（{pool.gpuIndices.length} GPU）</p>
                ) : null}
              </div>
              <div className="grid gap-2">
                <Label htmlFor="q-cpu">CPU 核</Label>
                <Input
                  id="q-cpu"
                  type="number"
                  min={1}
                  value={cpu}
                  onChange={(e) => setCpu(Number(e.target.value))}
                  className="text-right font-mono"
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="q-mem">Memory (MB)</Label>
                <Input
                  id="q-mem"
                  type="number"
                  step={1024}
                  value={mem}
                  onChange={(e) => setMem(Number(e.target.value))}
                  className="text-right font-mono"
                />
                <p className="text-xs text-muted-foreground">{formatMb(mem)}</p>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="q-storage">Storage (MB)</Label>
                <Input
                  id="q-storage"
                  type="number"
                  step={1024}
                  value={storage}
                  onChange={(e) => setStorage(Number(e.target.value))}
                  className="text-right font-mono"
                />
                <p className="text-xs text-muted-foreground">{formatMb(storage)}</p>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="q-jobs">同時任務數</Label>
                <Input
                  id="q-jobs"
                  type="number"
                  min={1}
                  max={32}
                  value={maxJobs}
                  onChange={(e) => setMaxJobs(Number(e.target.value))}
                  className="text-right font-mono"
                />
              </div>
            </div>
            {app.members.length ? (
              <div className="grid gap-2">
                <Label>加入成員</Label>
                <ul className="space-y-1">
                  {app.members.map((m) => (
                    <li key={m.email} className="flex items-center gap-2 text-sm">
                      <Checkbox
                        id={`m-${m.email}`}
                        checked={memberEmails.includes(m.email)}
                        onCheckedChange={(c) =>
                          setMemberEmails((prev) => (c ? [...prev, m.email] : prev.filter((x) => x !== m.email)))
                        }
                      />
                      <Label htmlFor={`m-${m.email}`} className="font-mono text-xs">
                        {m.email}
                      </Label>
                      <span className="text-xs text-muted-foreground">{projectRoleLabel[m.role]}</span>
                    </li>
                  ))}
                </ul>
                <p className="text-xs text-muted-foreground">尚未登入過的使用者會略過，之後可在「成員」分頁加入。</p>
              </div>
            ) : null}
            <div className="grid gap-2">
              <Label htmlFor="ap-note">給申請人的說明（可選）</Label>
              <Textarea id="ap-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setApproveOpen(false)}>
              取消
            </Button>
            <Button onClick={approve} disabled={pending || overPool} data-testid="approve-confirm">
              <CircleCheck />
              核准
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>退回申請</DialogTitle>
            <DialogDescription>申請人會看到理由，修改後可以重新送出。</DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor="reject-reason">退回理由</Label>
            <Textarea id="reject-reason" rows={4} value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectOpen(false)}>
              取消
            </Button>
            <Button variant="destructive" onClick={reject} disabled={pending || reason.trim().length === 0}>
              <CircleX />
              退回
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
