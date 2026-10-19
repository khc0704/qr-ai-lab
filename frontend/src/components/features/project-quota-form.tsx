"use client";

// quota.manage (superadmin): the project's own quota, edited on its settings tab.
import { Save, TriangleAlert } from "lucide-react";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { updateQuotaAction } from "@/lib/actions";
import { formatMb } from "@/lib/format";
import type { Project, ResourcePool } from "@/types/domain";

type Quota = {
  gpu_limit: number;
  cpu_limit: number;
  memory_limit_mb: number;
  storage_quota_mb: number;
  max_concurrent_jobs: number;
};

const FIELDS: { key: keyof Quota; label: string; step?: number; min?: number; format?: (n: number) => string }[] = [
  { key: "gpu_limit", label: "GPU", min: 0 },
  { key: "cpu_limit", label: "CPU 核數", step: 0.5, min: 0.5 },
  { key: "memory_limit_mb", label: "記憶體（MB）", step: 1024, min: 512, format: formatMb },
  { key: "storage_quota_mb", label: "儲存（MB）", step: 1024, min: 1024, format: formatMb },
  { key: "max_concurrent_jobs", label: "同時任務數", min: 1 },
];

export function ProjectQuotaForm({ project, pool }: { project: Project; pool: ResourcePool }) {
  const initial: Quota = {
    gpu_limit: project.gpuLimit,
    cpu_limit: project.cpuLimit,
    memory_limit_mb: project.memoryLimitMb,
    storage_quota_mb: project.storageQuotaMb,
    max_concurrent_jobs: project.maxConcurrentJobs,
  };
  const [v, setV] = useState(initial);
  const [pending, startTransition] = useTransition();
  const dirty = JSON.stringify(v) !== JSON.stringify(initial);
  const over = v.gpu_limit > pool.gpuIndices.length || v.cpu_limit > pool.cpuCores || v.memory_limit_mb > pool.memoryMb;
  const save = () =>
    startTransition(async () => {
      const r = await updateQuotaAction(project.slug, v);
      if (!r.ok) toast.error(r.error);
      else toast.success("配額已更新，之後啟動的任務會依新配額排程");
    });
  return (
    <Card>
      <CardHeader>
        <CardTitle>配額</CardTitle>
        <CardDescription>
          這個專案同時可用的上限（superadmin 可調整）。總資源池：
          <span className="font-mono text-foreground tabular-nums">
            {pool.gpuIndices.length} GPU · {pool.cpuCores} CPU · {formatMb(pool.memoryMb)}
          </span>
          ；實際排程仍以資源池為準。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {FIELDS.map((f) => (
            <div key={f.key} className="grid gap-1">
              <Label htmlFor={`quota-${f.key}`} className="text-xs">
                {f.label}
              </Label>
              <Input
                id={`quota-${f.key}`}
                type="number"
                step={f.step}
                min={f.min}
                className="text-right font-mono"
                value={v[f.key]}
                onChange={(e) => setV({ ...v, [f.key]: Number(e.target.value) })}
              />
              {f.format ? <span className="text-[11px] text-muted-foreground">{f.format(v[f.key])}</span> : null}
            </div>
          ))}
        </div>
        {over ? (
          <p className="flex items-center gap-1 text-xs text-warning">
            <TriangleAlert className="size-3.5" />
            超過總資源池；可以儲存，但任務會等到資源釋出才排程。
          </p>
        ) : null}
        <div className="flex justify-end">
          <Button size="sm" disabled={!dirty || pending} onClick={save} data-testid="save-quota">
            <Save />
            儲存配額
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
