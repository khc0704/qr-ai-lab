"use client";

import { CircleCheck, CircleX, Eye } from "lucide-react";
import { useRouter } from "next/navigation";
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
import { approveRequestAction, rejectRequestAction, reviewRequestAction } from "@/lib/actions";
import { formatMb } from "@/lib/format";
import type { ProjectRequest, ResourcePool } from "@/types/domain";

export function RequestReviewPanel({ request, pool }: { request: ProjectRequest; pool: ResourcePool }) {
  const [approveOpen, setApproveOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [slug, setSlug] = useState(request.proposedSlug ?? "");
  const [gpu, setGpu] = useState(request.requestedGpu);
  const [cpu, setCpu] = useState(request.requestedCpu);
  const [mem, setMem] = useState(request.requestedMemoryMb);
  const [storage, setStorage] = useState(request.requestedStorageMb);
  const [reason, setReason] = useState("");
  const [memberEmails, setMemberEmails] = useState<string[]>(request.members.map((m) => m.email));
  const [pending, startTransition] = useTransition();
  const router = useRouter();
  const terminal = request.status === "approved" || request.status === "rejected" || request.status === "withdrawn";
  if (terminal) return null;
  const overPool = gpu > pool.gpuIndices.length;
  const review = () =>
    startTransition(async () => {
      const r = await reviewRequestAction(request.id);
      if (!r.ok) toast.error(r.error);
      else toast.success("已標記為審核中");
    });
  const approve = () =>
    startTransition(async () => {
      const r = await approveRequestAction(request.id, {
        slug,
        gpu_limit: gpu,
        cpu_limit: cpu,
        memory_limit_mb: mem,
        storage_quota_mb: storage,
        max_concurrent_jobs: 1,
        members: request.members.filter((m) => memberEmails.includes(m.email)),
      });
      if (!r.ok) {
        toast.error(r.error);
        return;
      }
      setApproveOpen(false);
      toast.success(`已核准，專案 ${r.data.slug} 已建立`);
      router.push(`/projects/${r.data.slug}`);
    });
  const reject = () =>
    startTransition(async () => {
      const r = await rejectRequestAction(request.id, reason);
      if (!r.ok) {
        toast.error(r.error);
        return;
      }
      setRejectOpen(false);
      setReason("");
      toast.success("已退回申請");
    });

  return (
    <div className="space-y-2 rounded-xl border border-primary/30 bg-primary/5 p-4">
      <div className="text-label">管理員審核</div>
      <div className="flex flex-wrap gap-2">
        {request.status === "submitted" ? (
          <Button variant="outline" size="sm" onClick={review} disabled={pending}>
            <Eye />
            開始審核
          </Button>
        ) : null}
        <Button size="sm" onClick={() => setApproveOpen(true)}>
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
            <DialogTitle>核准並建立專案</DialogTitle>
            <DialogDescription>
              確認後立即建立專案、加入成員並通知申請人。配額之後仍可在「專案配額」調整。
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="slug">專案 slug</Label>
              <Input
                id="slug"
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                className="font-mono"
                placeholder="lowercase-with-dashes"
              />
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
                <p className="text-xs text-muted-foreground">{formatMb(mem || 0)}</p>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="q-sto">Storage (MB)</Label>
                <Input
                  id="q-sto"
                  type="number"
                  step={1024}
                  value={storage}
                  onChange={(e) => setStorage(Number(e.target.value))}
                  className="text-right font-mono"
                />
                <p className="text-xs text-muted-foreground">{formatMb(storage || 0)}</p>
              </div>
            </div>
            {request.members.length ? (
              <div className="grid gap-2">
                <Label>成員</Label>
                {request.members.map((m) => (
                  <label key={m.email} className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={memberEmails.includes(m.email)}
                      onCheckedChange={(c) =>
                        setMemberEmails(c ? [...memberEmails, m.email] : memberEmails.filter((e) => e !== m.email))
                      }
                    />
                    <span className="font-mono text-xs">{m.email}</span>
                    <span className="text-muted-foreground">{m.role}</span>
                  </label>
                ))}
              </div>
            ) : null}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setApproveOpen(false)}>
              取消
            </Button>
            <Button disabled={!slug || overPool || pending} onClick={approve}>
              核准並建立
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>退回申請</DialogTitle>
            <DialogDescription>理由會顯示給申請人；申請人修改後可重新送出。</DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor="reject-reason">理由（必填）</Label>
            <Textarea
              id="reject-reason"
              rows={4}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="例：資料尚未標註；GPU 申請量與資料量不符"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectOpen(false)}>
              取消
            </Button>
            <Button variant="destructive" disabled={!reason.trim() || pending} onClick={reject}>
              退回
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
